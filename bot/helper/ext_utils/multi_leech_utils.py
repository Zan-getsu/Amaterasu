from asyncio import Lock
from dataclasses import dataclass
from time import time


def _nonnegative_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def should_collect_multi_leech(
    is_leech, multi, folder_name="", is_youtube_upload=False
):
    try:
        multi = int(multi or 0)
    except (TypeError, ValueError):
        return False
    return bool(
        is_leech and multi > 1 and not folder_name and not is_youtube_upload
    )


def paginate_text_blocks(header, blocks, continuation_header, max_bytes=4000):
    """Pack complete HTML blocks without repeating a potentially large header."""

    pages = []
    current = header
    for block in blocks:
        if len((current + block).encode()) <= max_bytes:
            current += block
            continue
        if current:
            pages.append(current)
        current = continuation_header + block
    if current:
        pages.append(current)
    return tuple(pages)


@dataclass(frozen=True)
class MultiLeechFile:
    position: int
    link: str
    name: str


@dataclass(frozen=True)
class MultiLeechFailure:
    position: int
    name: str
    error: str


@dataclass(frozen=True)
class MultiLeechSnapshot:
    total: int
    succeeded: int
    failed: int
    total_size: int
    corrupted: int
    files: tuple[MultiLeechFile, ...]
    failures: tuple[MultiLeechFailure, ...]
    elapsed: float
    tag: str


class MultiLeechSummary:
    """Concurrency-safe result collector shared by one leech ``-i`` chain."""

    def __init__(self, total, anchor_message):
        self.total = max(1, int(total))
        self.anchor_message = anchor_message
        self.started_at = time()
        self._lock = Lock()
        self._terminal = set()
        self._successes = []
        self._failures = []
        self._emitted = False
        self._tag = ""

    async def record_success(
        self,
        task_id,
        position,
        name,
        size,
        files,
        corrupted=0,
        tag="",
    ):
        async with self._lock:
            key = ("task", task_id)
            if key in self._terminal:
                return None
            self._terminal.add(key)
            self._tag = tag or self._tag
            file_items = tuple(files.items()) if isinstance(files, dict) else ()
            self._successes.append(
                {
                    "position": int(position),
                    "name": str(name or "Unknown Task"),
                    "size": _nonnegative_int(size),
                    "files": file_items,
                    "corrupted": _nonnegative_int(corrupted),
                }
            )
            return self._snapshot_if_complete()

    async def record_failure(self, task_id, position, name, error, tag=""):
        async with self._lock:
            key = ("task", task_id)
            if key in self._terminal:
                return None
            self._terminal.add(key)
            self._tag = tag or self._tag
            self._failures.append(
                MultiLeechFailure(
                    int(position),
                    str(name or "Unknown Task"),
                    str(error or "Task failed"),
                )
            )
            return self._snapshot_if_complete()

    async def record_unstarted(self, count, position, error, tag=""):
        async with self._lock:
            self._tag = tag or self._tag
            for offset in range(max(0, int(count))):
                key = ("unstarted", int(position) + offset)
                if key in self._terminal:
                    continue
                self._terminal.add(key)
                self._failures.append(
                    MultiLeechFailure(
                        int(position) + offset,
                        "Not started",
                        str(error or "Task was not started"),
                    )
                )
            return self._snapshot_if_complete()

    def _snapshot_if_complete(self):
        if self._emitted or len(self._terminal) < self.total:
            return None
        self._emitted = True
        successes = sorted(self._successes, key=lambda item: item["position"])
        failures = tuple(sorted(self._failures, key=lambda item: item.position))
        files = tuple(
            MultiLeechFile(item["position"], str(link), str(name))
            for item in successes
            for link, name in item["files"]
        )
        return MultiLeechSnapshot(
            total=self.total,
            succeeded=len(successes),
            failed=len(failures),
            total_size=sum(item["size"] for item in successes),
            corrupted=sum(item["corrupted"] for item in successes),
            files=files,
            failures=failures,
            elapsed=max(0, time() - self.started_at),
            tag=self._tag,
        )
