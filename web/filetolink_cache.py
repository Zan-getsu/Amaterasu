"""Immutable opening/ending chunks in the existing FileToLink disk budget."""

from asyncio import Lock, to_thread
from contextlib import suppress
from hashlib import sha256
from os import chmod, replace
from pathlib import Path
from secrets import token_hex


class EdgeCache:
    def __init__(self, root, budget, prune):
        self.root = Path(root)
        self.budget = budget
        self.prune = prune
        self.lock = Lock()

    def path(self, identity, size, offset, limit):
        key = sha256(f"{identity}:{size}:{offset}:{limit}".encode()).hexdigest()
        return self.root / f"{key}.edge"

    def eligible(self, identity, size, offset, limit):
        return bool(
            identity
            and self.budget > 0
            and 0 < limit <= 1024**2
            and 0 <= offset < size
            and (offset < 4 * 1024**2 or offset + limit > size - 2 * 1024**2)
        )

    async def get(self, identity, size, offset, limit):
        if not self.eligible(identity, size, offset, limit):
            return None
        path = self.path(identity, size, offset, limit)

        def read():
            try:
                data = path.read_bytes()
                if len(data) == min(limit, size - offset):
                    path.touch()
                    return data
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

        return await to_thread(read)

    async def put(self, identity, size, offset, limit, data):
        if (
            not self.eligible(identity, size, offset, limit)
            or len(data) > self.budget
            or len(data) != min(limit, size - offset)
        ):
            return
        path = self.path(identity, size, offset, limit)
        async with self.lock:

            def write():
                temporary = path.with_suffix(f".{token_hex(8)}.part")
                try:
                    self.root.mkdir(parents=True, exist_ok=True)
                    self.prune(len(data))
                    temporary.write_bytes(data)
                    chmod(temporary, 0o600)
                    replace(temporary, path)
                except OSError:
                    pass  # A cache outage must never interrupt playback.
                finally:
                    with suppress(OSError):
                        temporary.unlink(missing_ok=True)

            await to_thread(write)
