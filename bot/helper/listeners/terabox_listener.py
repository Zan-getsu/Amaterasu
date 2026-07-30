from asyncio import Event
from time import time

from ... import LOGGER


class TeraboxDownloadTracker:
    def __init__(self, listener):
        self.listener = listener
        self.cancel_event = Event()
        self.is_cancelled = False
        self._completed_bytes = 0
        self._current_bytes = 0
        self._speed = 0.0
        self._ema = 0.0
        self._last_total = 0
        self._last_time = time()
        self._cleanup_selection = None

    def start_file(self):
        self._current_bytes = 0

    def finish_file(self, size):
        self._completed_bytes += max(0, int(size or 0))
        self._current_bytes = 0

    def on_progress(self, written, _total):
        self._current_bytes = max(0, int(written or 0))
        now = time()
        elapsed = now - self._last_time
        if elapsed >= 1:
            current_total = self._completed_bytes + self._current_bytes
            instant = (current_total - self._last_total) / elapsed
            self._ema = 0.3 * instant + 0.7 * self._ema if self._ema else instant
            self._speed = max(0.0, self._ema)
            self._last_total = current_total
            self._last_time = now

    @property
    def downloaded_bytes(self):
        return self._completed_bytes + self._current_bytes

    @property
    def speed(self):
        return 0.0 if time() - self._last_time > 8 else self._speed

    async def cancel_task(self):
        if self.is_cancelled:
            return
        self.is_cancelled = True
        self.cancel_event.set()
        cleanup = self._cleanup_selection
        self._cleanup_selection = None
        if cleanup:
            try:
                await cleanup()
            except Exception as error:
                LOGGER.warning("TeraBox selection cleanup failed: %s", error)
        await self.listener.on_download_error("Download stopped by user!")
