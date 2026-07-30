from asyncio import sleep, gather

from .... import LOGGER, qb_torrents, qb_listener_lock
from ....core.torrent_manager import TorrentManager
from ...ext_utils.status_utils import (
    MirrorStatus,
    EngineStatus,
    get_readable_file_size,
    get_readable_time,
)
from ..qbit_compat import (
    CHECKING_STATES,
    PAUSED_STATES,
    QUEUE_DOWNLOAD_STATES,
    QUEUE_UPLOAD_STATES,
    SEEDING_STATES,
    first_torrent_tag,
    is_metadata_state,
    seconds_value,
)


async def get_download(tag, old_info=None):
    try:
        res = (await TorrentManager.qbittorrent.torrents.info(tag=tag))[0]
        return res or old_info
    except Exception as e:
        LOGGER.warning(f"{e}: Qbittorrent, while getting torrent info. Tag: {tag}")
        await TorrentManager.ensure_qbit()
        return old_info


class QbittorrentStatus:
    def __init__(self, listener, seeding=False, queued=False):
        self.queued = queued
        self.seeding = seeding
        self.listener = listener
        self._info = None
        self.engine = EngineStatus().STATUS_QBIT

    async def update(self):
        self._info = await get_download(f"{self.listener.mid}", self._info)

    def progress(self):
        if not self._info:
            return "0%"
        return f"{round(self._info.progress * 100, 2)}%"

    def processed_bytes(self):
        if not self._info:
            return "0 B"
        return get_readable_file_size(self._info.downloaded)

    def speed(self):
        if not self._info:
            return "0 B/s"
        return f"{get_readable_file_size(self._info.dlspeed)}/s"

    def name(self):
        if self._info and is_metadata_state(self._info.state):
            return f"[METADATA]{self.listener.name}"
        else:
            return self.listener.name

    def size(self):
        if not self._info:
            return get_readable_file_size(getattr(self.listener, "size", 0))
        return get_readable_file_size(self._info.size)

    def eta(self):
        if not self._info:
            return "-"
        return get_readable_time(seconds_value(self._info.eta))

    async def status(self):
        await self.update()
        if not self._info:
            return MirrorStatus.STATUS_DOWNLOAD
        state = self._info.state
        if state in QUEUE_DOWNLOAD_STATES or self.queued:
            return MirrorStatus.STATUS_QUEUEDL
        elif state in QUEUE_UPLOAD_STATES:
            return MirrorStatus.STATUS_QUEUEUP
        elif state in PAUSED_STATES:
            return MirrorStatus.STATUS_PAUSED
        elif state in CHECKING_STATES:
            return MirrorStatus.STATUS_CHECK
        elif state in SEEDING_STATES and self.seeding:
            return MirrorStatus.STATUS_SEED
        else:
            return MirrorStatus.STATUS_DOWNLOAD

    def seeders_num(self):
        return self._info.num_seeds if self._info else 0

    def leechers_num(self):
        return self._info.num_leechs if self._info else 0

    def uploaded_bytes(self):
        if not self._info:
            return "0 B"
        return get_readable_file_size(self._info.uploaded)

    def seed_speed(self):
        if not self._info:
            return "0 B/s"
        return f"{get_readable_file_size(self._info.upspeed)}/s"

    def ratio(self):
        if not self._info:
            return "0"
        return f"{round(self._info.ratio, 3)}"

    def seeding_time(self):
        if not self._info:
            return "-"
        return get_readable_time(seconds_value(self._info.seeding_time))

    def task(self):
        return self

    def gid(self):
        return self.hash()[:12]

    def hash(self):
        return self._info.hash if self._info else str(self.listener.mid)

    async def cancel_task(self):
        self.listener.is_cancelled = True
        await self.update()
        if not self._info:
            await self.listener.on_download_error("Stopped by user!")
            return
        if TorrentManager.qbittorrent is not None:
            await TorrentManager.qbittorrent.torrents.stop([self._info.hash])
        if not self.seeding:
            if self.queued:
                LOGGER.info(f"Cancelling QueueDL: {self.name()}")
                msg = "task have been removed from queue/download"
            else:
                LOGGER.info(f"Cancelling Download: {self._info.name}")
                msg = "Stopped by user!"
            await sleep(0.3)
            tag = first_torrent_tag(self._info)
            tasks = [self.listener.on_download_error(msg)]
            if TorrentManager.qbittorrent is not None:
                tasks.append(
                    TorrentManager.qbittorrent.torrents.delete([self._info.hash], True)
                )
                if tag:
                    tasks.append(
                        TorrentManager.qbittorrent.torrents.delete_tags(tags=[tag])
                    )
            await gather(*tasks)
            async with qb_listener_lock:
                if tag and tag in qb_torrents:
                    del qb_torrents[tag]
