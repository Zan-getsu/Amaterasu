from asyncio import Semaphore, TimeoutError, gather, sleep
from contextlib import suppress

from aiohttp.client_exceptions import ClientError

from ... import LOGGER
from ...core.config_manager import Config
from ...core.torrent_manager import TorrentManager, aria2_name


class DirectListener:
    def __init__(self, path, listener, a2c_opt):
        self.listener = listener
        self._path = path
        self._a2c_opt = a2c_opt
        self._proc_bytes = 0
        self._failed = 0
        self.download_tasks = {}
        self.name = self.listener.name
        self.parallelism = min(max(int(Config.DIRECT_PARALLELISM), 1), 16)

    @property
    def download_task(self):
        """Keep compatibility with status consumers that expect one active task."""
        return next(iter(self.download_tasks.values()), None)

    @property
    def processed_bytes(self):
        return self._proc_bytes + sum(
            int(task.get("completedLength", "0") or 0) for task in self.download_tasks.values()
        )

    @property
    def speed(self):
        return sum(
            int(task.get("downloadSpeed", "0") or 0) for task in self.download_tasks.values()
        )

    @property
    def all_waiting(self):
        return bool(self.download_tasks) and all(
            task.get("status", "") == "waiting" for task in self.download_tasks.values()
        )

    async def _remove_download(self, download):
        with suppress(Exception):
            await TorrentManager.aria2_remove(download)

    async def _download_one(self, content):
        if self.listener.is_cancelled:
            return

        filename = content["filename"]
        options = self._a2c_opt.copy()
        options["dir"] = f"{self._path}/{content['path']}" if content["path"] else self._path
        options["out"] = filename
        gid = ""
        download = None

        try:
            gid = await TorrentManager.aria2.addUri(
                uris=[content["url"]], options=options, position=0
            )
            download = await TorrentManager.aria2.tellStatus(gid)
            self.download_tasks[gid] = download

            while not self.listener.is_cancelled:
                download = await TorrentManager.aria2.tellStatus(gid)
                self.download_tasks[gid] = download
                if error_message := download.get("errorMessage"):
                    self._failed += 1
                    failed_name = aria2_name(download) or filename
                    LOGGER.error(f"Unable to download {failed_name} due to: {error_message}")
                    await self._remove_download(download)
                    return
                if download.get("status", "") == "complete":
                    # Move completed bytes from the live aggregate into the
                    # durable counter without briefly counting them twice.
                    self.download_tasks.pop(gid, None)
                    self._proc_bytes += int(download.get("totalLength", "0") or 0)
                    await self._remove_download(download)
                    return
                await sleep(1)

            if download:
                await self._remove_download(download)
        except (TimeoutError, ClientError, Exception) as e:
            self._failed += 1
            LOGGER.error(f"Unable to download {filename} due to: {e}")
            if download:
                await self._remove_download(download)
            elif gid:
                # addUri succeeded but the first status request failed. Remove
                # the unseen job so it cannot keep downloading as an orphan.
                await self._remove_download({"gid": gid, "status": "active"})
        finally:
            if gid:
                self.download_tasks.pop(gid, None)

    async def download(self, contents):
        self.is_downloading = True
        contents = list(contents)
        parallelism = min(self.parallelism, len(contents))
        LOGGER.info(f"Downloading {len(contents)} direct files with {parallelism} parallel slots")
        slots = Semaphore(parallelism)

        async def run(content):
            async with slots:
                await self._download_one(content)

        await gather(*(run(content) for content in contents))
        if self.listener.is_cancelled:
            return
        if self._failed == len(contents):
            await self.listener.on_download_error("All files are failed to download!")
            return
        await self.listener.on_download_complete()
        return

    async def cancel_task(self):
        self.listener.is_cancelled = True
        LOGGER.info(f"Cancelling Download: {self.listener.name}")
        await gather(*(self._remove_download(task) for task in list(self.download_tasks.values())))
        await self.listener.on_download_error("Download Cancelled by User!")
