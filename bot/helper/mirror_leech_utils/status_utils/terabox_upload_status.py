from ...ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
)


class TeraboxUploadStatus:
    def __init__(self, listener, obj, gid, status):
        self.listener = listener
        self._obj = obj
        self._gid = gid
        self._status = status
        self.engine = EngineStatus().STATUS_TERABOX

    def name(self):
        return self.listener.name

    def progress_raw(self):
        return round(self._obj.processed_bytes / self.listener.size * 100, 2) if self.listener.size else 0

    def progress(self):
        return f"{self.progress_raw()}%"

    def status(self):
        return MirrorStatus.STATUS_UPLOAD

    def processed_bytes(self):
        return get_readable_file_size(self._obj.processed_bytes)

    def eta(self):
        if not self._obj.speed:
            return "-"
        return get_readable_time(
            (self.listener.size - self._obj.processed_bytes) / self._obj.speed
        )

    def size(self):
        return get_readable_file_size(self.listener.size)

    def speed(self):
        return f"{get_readable_file_size(self._obj.speed)}/s"

    def gid(self):
        return self._gid

    def task(self):
        return self._obj
