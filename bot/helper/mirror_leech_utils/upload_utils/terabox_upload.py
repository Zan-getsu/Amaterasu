import os
from asyncio import Event
from mimetypes import guess_type
from time import time

from aiofiles.os import path as aiopath

from .... import LOGGER

try:
    from terabox import (
        TeraboxCancelled,
        TeraboxClient,
        TeraboxError,
        __version__ as TERABOX_ADAPTER_VERSION,
        sanitize_remote_path,
    )
except ImportError:
    TeraboxClient = None


def _posix_join(base, *parts):
    joined = "/".join(
        segment.strip("/")
        for segment in (base, *parts)
        if segment and segment.strip("/")
    )
    return sanitize_remote_path(f"/{joined}" if joined else "/")


class TeraboxUpload:
    def __init__(self, listener, path):
        self.listener = listener
        self._path = path
        self._completed = 0
        self._current = 0
        self.speed = 0.0
        self._ema = 0.0
        self._last_total = 0
        self._last_time = time()
        self.is_cancelled = False
        self._cancel_event = Event()
        self._client = None

    @property
    def processed_bytes(self):
        return self._completed + self._current

    def _on_progress(self, done, _total):
        self._current = max(0, int(done or 0))
        now = time()
        elapsed = now - self._last_time
        if elapsed >= 1:
            current = self._completed + self._current
            instant = (current - self._last_total) / elapsed
            self._ema = 0.3 * instant + 0.7 * self._ema if self._ema else instant
            self.speed = max(0.0, self._ema)
            self._last_total = current
            self._last_time = now

    def _gather_files(self):
        base = self.listener.terabox_upload_path or "/"
        name = (self.listener.name or os.path.basename(self._path)).strip("/")
        if os.path.isfile(self._path):
            return [(self._path, _posix_join(base, name))], 1, 0
        items = []
        folders = 0
        for root, directories, files in os.walk(self._path):
            folders += len(directories)
            for filename in files:
                local = os.path.join(root, filename)
                relative = os.path.relpath(local, self._path).replace(os.sep, "/")
                items.append((local, _posix_join(base, name, relative)))
        return items, len(items), folders + 1

    async def _make_share_link(self, uploaded, base, name):
        if not uploaded:
            return ""
        try:
            if self.listener.is_file:
                file_id, path = uploaded[0]
                return await self._client.create_share_link([file_id], [path])
            folder_path = _posix_join(base, name)
            for entry in await self._client.region_list_dir(base or "/"):
                if (
                    entry.get("server_filename") == name
                    and int(entry.get("isdir", 0)) == 1
                ):
                    return await self._client.create_share_link(
                        [entry["fs_id"]], [folder_path]
                    )
            return await self._client.create_share_link(
                [file_id for file_id, _ in uploaded],
                [path for _, path in uploaded],
            )
        except Exception:
            return ""

    async def upload(self):
        if TeraboxClient is None:
            await self.listener.on_upload_error(
                "teraboxSDK is not installed in this image; cannot upload to TeraBox."
            )
            return
        cookie_file = getattr(self.listener, "terabox_cookie", "")
        if not cookie_file or not await aiopath.exists(cookie_file):
            await self.listener.on_upload_error(
                "No TeraBox cookie configured for upload."
            )
            return
        self._client = TeraboxClient(
            cookie_file=os.path.abspath(cookie_file),
            session_path=".terabox_upload_session.json",
        )
        try:
            LOGGER.info("TeraBox adapter version: %s", TERABOX_ADAPTER_VERSION)
            await self._client.ensure_upload_ready()
            items, total_files, total_folders = self._gather_files()
            if not items:
                await self.listener.on_upload_error("Nothing to upload.")
                return
            uploaded = []
            for local, remote in items:
                if self.is_cancelled or self.listener.is_cancelled:
                    return
                size = os.path.getsize(local)
                self._current = 0
                info = await self._client.upload_file(
                    local,
                    remote,
                    progress_cb=self._on_progress,
                    cancel_event=self._cancel_event,
                )
                self._completed += size
                self._current = 0
                if info.get("fs_id"):
                    uploaded.append((info["fs_id"], remote))
            if self.is_cancelled or self.listener.is_cancelled:
                return
            self.listener.private_link = True
            base = self.listener.terabox_upload_path or "/"
            name = (self.listener.name or "").strip("/")
            mime_type = (
                guess_type(self._path)[0] or "application/octet-stream"
                if self.listener.is_file
                else "Folder"
            )
            display = (
                uploaded[0][1]
                if self.listener.is_file and uploaded
                else _posix_join(base, name)
            )
            link = await self._make_share_link(uploaded, base, name)
            await self.listener.on_upload_complete(
                link or None,
                total_files,
                total_folders,
                mime_type,
                rclone_path=display,
            )
        except TeraboxCancelled:
            return
        except TeraboxError as error:
            await self.listener.on_upload_error(f"TeraBox upload failed: {error}")
        except Exception as error:
            await self.listener.on_upload_error(f"TeraBox upload error: {error}")
        finally:
            if self._client:
                try:
                    await self._client.aclose()
                except Exception as error:
                    LOGGER.warning("Could not close TeraBox upload client: %s", error)

    async def cancel_task(self):
        if self.is_cancelled:
            return
        self.is_cancelled = True
        self._cancel_event.set()
        await self.listener.on_upload_error("Upload stopped by user!")
