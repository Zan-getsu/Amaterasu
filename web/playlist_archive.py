"""Bounded, deduplicated ZIP preparation; completed archives are immutable."""

import asyncio
import json
import logging
import os
import re
import shutil
import time
from contextlib import aclosing, suppress
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from zipfile import ZipFile


def entry_name(index, name):
    name = re.sub(r'[\x00-\x1f\x7f/\\:<>"|?*]', "_", str(name))
    return f"{index:03d}-{name[:180].rstrip('. ') or 'file'}"


class PlaylistArchives:
    AGE = 86400
    READ_TIMEOUT = 60

    def __init__(self, root, max_bytes, usage, prune):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.usage = usage
        self.prune = prune
        self.jobs = {}
        self.lock = asyncio.Lock()

    @property
    def reserved(self):
        return sum(
            job["reservation"]
            for job in list(self.jobs.values())
            if job.get("task") is None or not job["task"].done()
        )

    def path(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Invalid ZIP link")
        return self.root / f"{key}.zip"

    def status(self, key):
        path = self.path(key)
        try:
            meta = json.loads(path.with_suffix(".json").read_text())
            if meta["expires"] > time.time() and path.stat().st_size == meta["bytes"]:
                return {**meta, "state": "ready"}
        except (OSError, ValueError, KeyError):
            pass
        job = self.jobs.get(key)
        if job and not job["task"].done():
            return {k: job[k] for k in ("state", "bytes", "total", "expires", "playlist")}
        return dict(state="missing", bytes=0, total=0)

    def cleanup(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for key, job in list(self.jobs.items()):
            if job["task"].done():
                del self.jobs[key]
        for path in self.root.iterdir():
            if path.suffix == ".part" and path.name.split(".")[0] not in self.jobs:
                path.unlink(missing_ok=True)
            elif path.suffix == ".json":
                try:
                    expired = json.loads(path.read_text())["expires"] <= time.time()
                except (OSError, ValueError, KeyError):
                    expired = True
                if expired:
                    with suppress(OSError):
                        path.with_suffix(".zip").unlink(missing_ok=True)
                        path.unlink(missing_ok=True)
            elif (
                path.suffix == ".zip"
                and path.stem not in self.jobs
                and not path.with_suffix(".json").exists()
            ):
                path.unlink(missing_ok=True)

    async def start(self, playlist, files, read):
        if not 1 <= len(files) <= 100 or any(int(f["size"]) <= 0 for f in files):
            raise ValueError("A ZIP needs between 1 and 100 available files.")
        key = sha256(json.dumps([playlist, files], sort_keys=True).encode()).hexdigest()
        async with self.lock:
            await asyncio.to_thread(self.cleanup)
            state = self.status(key)
            if state["state"] != "missing":
                return key
            if sum(not j["task"].done() for j in self.jobs.values()) >= 2:
                raise ValueError("Two ZIPs are being prepared. Try again after one finishes.")
            total = sum(int(f["size"]) for f in files) + 4096 * len(files) + 65536
            if total + self.reserved > self.max_bytes:
                raise ValueError(
                    "This ZIP exceeds the available cache budget. Use individual downloads."
                )
            await asyncio.to_thread(self.prune, total)
            used = await asyncio.to_thread(self.usage)
            free = (await asyncio.to_thread(shutil.disk_usage, self.root)).free
            if (
                total + used + self.reserved > self.max_bytes
                or total + self.reserved + 64 * 1024**2 > free
            ):
                raise ValueError(
                    "Not enough ZIP cache space. Use individual downloads or increase the cache budget."
                )
            job = dict(
                state="preparing",
                bytes=0,
                total=sum(f["size"] for f in files),
                reservation=total,
                expires=time.time() + self.AGE,
                playlist=playlist,
            )
            self.jobs[key] = job
            job["task"] = asyncio.create_task(self._build(key, files, read, job))
            return key

    async def _build(self, key, files, read, job):
        path = self.path(key)
        partial = path.with_suffix(".part")
        try:
            with ZipFile(partial, "w", allowZip64=True) as archive:
                os.chmod(partial, 0o600)
                for index, item in enumerate(files, 1):
                    done = 0
                    with archive.open(
                        entry_name(index, item["name"]), "w", force_zip64=True
                    ) as entry:
                        async with aclosing(read(item)) as source:
                            while True:
                                try:
                                    chunk = await asyncio.wait_for(anext(source), self.READ_TIMEOUT)
                                except StopAsyncIteration:
                                    break
                                if (
                                    done + len(chunk) > item["size"]
                                    or time.time() >= job["expires"]
                                ):
                                    raise OSError("ZIP source changed or preparation expired")
                                writing = asyncio.create_task(asyncio.to_thread(entry.write, chunk))
                                try:
                                    await asyncio.shield(writing)
                                except asyncio.CancelledError:
                                    await (
                                        writing
                                    )  # Close the ZIP only after its disk writer has stopped.
                                    raise
                                done += len(chunk)
                                job["bytes"] += len(chunk)
                    if done != item["size"]:
                        raise OSError("ZIP source ended early")
            size = partial.stat().st_size
            if size > job["reservation"]:
                raise OSError("ZIP exceeded its reservation")
            partial.replace(path)
            metadata = {k: job[k] for k in ("expires", "playlist")}
            metadata.update(bytes=size, total=size)
            metadata["version"] = token_hex(16)
            meta_path = path.with_suffix(".json")
            temporary = meta_path.with_suffix(".json.part")
            temporary.write_text(json.dumps(metadata))
            os.chmod(temporary, 0o600)
            temporary.replace(meta_path)
            job.update(state="ready", bytes=size, total=size)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            job["state"] = "failed"
            logging.getLogger(__name__).warning(
                "Playlist ZIP preparation failed (%s).", type(exc).__name__
            )
        finally:
            with suppress(OSError):
                partial.unlink(missing_ok=True)

    async def close(self):
        tasks = [j["task"] for j in self.jobs.values() if not j["task"].done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
