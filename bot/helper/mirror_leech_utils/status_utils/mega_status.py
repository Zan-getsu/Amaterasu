from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)


class MegaDownloadStatus:
    def __init__(self, listener, obj, gid, status=""):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._status = status
        self._size = self.listener.size
        self.engine = EngineStatus().STATUS_MEGA

    def name(self):
        return self.listener.name

    def progress_raw(self):
        try:
            return round(self._obj.downloaded_bytes / self._size * 100, 2)
        except ZeroDivisionError:
            return 0.0

    def progress(self):
        return f"{self.progress_raw()}%"

    def status(self):
        if self._status == "up":
            return MirrorStatus.STATUS_UPLOAD
        elif self._status == "dl":
            return MirrorStatus.STATUS_DOWNLOAD

    def processed_bytes(self):
        return get_readable_file_size(self._obj.downloaded_bytes)

    def eta(self):
        try:
            seconds = (self._size - self._obj.downloaded_bytes) / max(self._obj.speed, 1)
            return get_readable_time(seconds)
        except ZeroDivisionError:
            return "-"

    def size(self):
        return get_readable_file_size(self._size)

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def gid(self):
        return self._gid

    def task(self):
        return self

    async def cancel_task(self):
        await self._obj.cancel_task()
        await self.listener.on_download_error(f"{self._status} stopped by user!")
