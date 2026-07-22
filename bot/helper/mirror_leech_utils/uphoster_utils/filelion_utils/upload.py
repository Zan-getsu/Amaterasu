"""Phase 1.2 — FileLion uploader.

Uploads files to FileLion (filelion.xyz) via their API.
Requires Config.FILELION_API to be set. If not set, the upload
fails silently with a clear log message (Rule 2 — no UI noise).

FileLion API docs: https://filelion.xyz/api
Upload endpoint: POST /api/v1/upload
"""

from io import BufferedReader
from logging import getLogger
from os import path as ospath
from os import walk as oswalk
from pathlib import Path

from aiofiles.os import path as aiopath
from aiohttp import ClientSession
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import SetInterval, sync_to_async

LOGGER = getLogger(__name__)


class ProgressFileReader(BufferedReader):
    def __init__(self, filename, read_callback=None):
        super().__init__(open(filename, "rb"))
        self.__read_callback = read_callback
        self.length = Path(filename).stat().st_size

    def read(self, size=None):
        size = size or (self.length - self.tell())
        if self.__read_callback:
            self.__read_callback(self.tell())
        return super().read(size)

    def __len__(self):
        return self.length


class FileLionUpload:
    """Upload to FileLion. Requires Config.FILELION_API."""

    def __init__(self, listener, path, folder_name=""):
        self.listener = listener
        self._updater = None
        self._path = path
        self.folder_name = folder_name
        self._is_errored = False
        self.api_url = "https://filelion.xyz/api/v1"
        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3

        from bot import user_data
        user_dict = user_data.get(self.listener.user_id, {})
        self.api_key = user_dict.get("FILELION_API") or Config.FILELION_API

    @property
    def speed(self):
        try:
            return self.__processed_bytes / self.total_time
        except (ZeroDivisionError, AttributeError):
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    async def _progress(self):
        if self._updater is not None:
            chunk_size = 1024 * 1024
            self.__processed_bytes = self.__processed_bytes + chunk_size

    async def _upload_file(self, session, file_path):
        """Upload a single file to FileLion."""
        if not self.api_key:
            raise Exception("FileLion API key not configured")
        file_size = Path(file_path).stat().st_size
        self.__processed_bytes = 0
        self.last_uploaded = 0

        url = f"{self.api_url}/upload"
        data = {
            "key": self.api_key,
        }
        try:
            with open(file_path, "rb") as f:
                async with session.post(url, data=data, files={"file": f}) as resp:
                    result = await resp.json()
                    if result.get("status") != 200:
                        raise Exception(
                            f"FileLion upload failed: {result.get('msg', 'unknown error')}"
                        )
                    file_code = result.get("result", {}).get("filecode")
                    download_url = f"https://filelion.xyz/{file_code}"
                    return download_url
        except Exception as e:
            LOGGER.error(f"FileLion upload error: {e}")
            raise

    async def _upload_dir(self, input_directory):
        for root, _, files in oswalk(input_directory):
            for file in files:
                file_path = ospath.join(root, file)
                await self._upload_file(None, file_path)
                self.total_files += 1

    async def upload(self):
        if not self.api_key:
            await self.listener.on_upload_error(
                "FileLion API key not configured. Set FILELION_API in config."
            )
            return

        self._updater = SetInterval(self.update_interval, self._progress)
        async with ClientSession() as session:
            try:
                if await aiopath.isdir(self._path):
                    await self._upload_dir(self._path)
                else:
                    download_url = await self._upload_file(session, self._path)
                    self.total_files = 1
                    await self.listener.on_upload_complete(
                        download_url,
                        self.total_files,
                        self.total_folders,
                        "application/octet-stream",
                        "",
                    )
            except Exception as e:
                await self.listener.on_upload_error(f"FileLion upload failed: {e}")
        self._updater.cancel()

    async def cancel_task(self):
        self.is_uploading = False
        if self._updater is not None:
            self._updater.cancel()
        await self.listener.on_upload_error("FileLion upload cancelled")
