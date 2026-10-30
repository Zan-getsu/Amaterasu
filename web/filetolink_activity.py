"""Single-web-worker checkpoints and bounded download range coverage."""

from asyncio import Lock
from collections import OrderedDict
from contextlib import aclosing
from time import monotonic


class TransferTotals:
    # shortcut: one web writer (the shipped gunicorn -w 1), use per-worker records for replicas.
    def __init__(self):
        self.values = dict(
            bytes=0, completed=0, failed=0, incomplete=0, downloads=0, zip_downloads=0
        )
        self.active = 0
        self.loaded = False
        self.saved = None
        self.state = "pending"
        self.coverage = OrderedDict()
        # shortcut: range coverage resets on restart; persist sessions if cross-restart counting is needed.
        self.lock = Lock()

    def snapshot(self):
        return {**self.values, "persistence": self.state}

    async def flush(self, collection):
        async with self.lock:
            try:
                if collection is None:
                    raise RuntimeError("MongoDB unavailable")
                if not self.loaded:
                    record = await collection.find_one({"_id": "totals"}) or {}
                    restored = {key: max(0, int(record.get(key, 0))) for key in self.values}
                    restored["incomplete"] += max(0, int(record.get("active", 0)))
                    for key, value in restored.items():
                        self.values[key] += value
                    self.loaded = True
                checkpoint = {**self.values, "active": self.active}
                if checkpoint != self.saved:
                    await collection.update_one(
                        {"_id": "totals"}, {"$set": checkpoint}, upsert=True
                    )
                    self.saved = checkpoint
                self.state = "saved"
            except Exception:
                self.state = "unavailable"

    def delivered(self, key, start, stop, size, kind):
        now = monotonic()
        while self.coverage and (
            len(self.coverage) >= 1024 or next(iter(self.coverage.values()))["seen"] < now - 86400
        ):
            self.coverage.popitem(last=False)
        entry = self.coverage.pop(key, dict(ranges=[], complete=False, seen=now))
        if entry["complete"]:
            if start or now - entry["seen"] < 10:
                entry["seen"] = now
                self.coverage[key] = entry
                return
            entry.update(ranges=[], complete=False)
        merged = []
        for left, right in sorted(entry["ranges"] + [(start, min(stop, size))]):
            if left >= right:
                continue
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
            else:
                merged.append((left, right))
        if merged == [(0, size)]:
            self.values["zip_downloads" if kind == "zip" else "downloads"] += 1
            entry["complete"] = True
            merged = []
        entry.update(ranges=merged, seen=now)
        if len(merged) <= 256:
            self.coverage[key] = entry

    async def track(self, source, length, *, key, start=0, size=0, kind=None):
        done = 0
        outcome = "incomplete"
        self.active += 1
        try:
            async with aclosing(source):
                async for chunk in source:
                    previous = done
                    done += len(chunk)
                    self.values["bytes"] += len(chunk)
                    if kind:
                        self.delivered(key, start + previous, start + done, size, kind)
                    yield chunk
            if done < length:
                raise OSError("Transfer ended before Content-Length")
            outcome = "completed"
        except Exception:
            outcome = "failed"
            raise
        finally:
            if outcome == "incomplete" and done >= length:
                outcome = "completed"
            self.values[outcome] += 1
            self.active -= 1


totals = TransferTotals()
