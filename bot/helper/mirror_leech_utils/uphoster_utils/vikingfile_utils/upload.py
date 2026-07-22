from io import BufferedReader
from logging import getLogger
from os import path as ospath
from os import walk as oswalk
from pathlib import Path

from aiofiles.os import path as aiopath
from aiohttp import ClientSession, FormData
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import SetInterval, sync_to_async
from bot.helper.ext_utils.telegraph_helper import telegraph

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


class VikingFileUpload:
    def __init__(self, listener, path, folder_name=""):
        self.listener = listener
        self._path = path
        self.folder_name = folder_name
        self._updater = None
        self._is_errored = False
        self.base_url = "https://vikingfile.com/api"
        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.total_time = 0
        self.total_files = 0
        self.total_folders = 0
        self.is_uploading = True
        self.update_interval = 3
        self._server = None

        from bot import user_data

        user_dict = user_data.get(self.listener.user_id, {})
        self.token = user_dict.get("VIKINGFILE_HASH") or Config.VIKINGFILE_HASH
        self.folder_path = (
            user_dict.get("VIKINGFILE_FOLDER") or Config.VIKINGFILE_FOLDER or ""
        )

    @property
    def speed(self):
        try:
            return self.__processed_bytes / self.total_time
        except Exception:
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    def __progress_callback(self, current):
        chunk_size = current - self.last_uploaded
        self.last_uploaded = current
        self.__processed_bytes += chunk_size

    async def progress(self):
        self.total_time += self.update_interval

    async def __get_server(self):
        if self._server:
            return self._server
        async with ClientSession() as session:
            async with session.get(f"{self.base_url}/get-server") as resp:
                result = await resp.json(content_type=None)
        self._server = result.get("server", "https://upload.vikingfile.com")
        return self._server

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_file(self, path, folder_path=""):
        if self.listener.is_cancelled:
            return None
        server = await self.__get_server()
        file_name = ospath.basename(path)
        with ProgressFileReader(
            filename=path, read_callback=self.__progress_callback
        ) as file:
            data = FormData()
            data.add_field("file", file, filename=file_name)
            data.add_field("user", self.token or "")
            if folder_path:
                data.add_field("path", folder_path)
            async with ClientSession() as session:
                async with session.post(server, data=data) as resp:
                    result = await resp.json(content_type=None)
        url = result.get("url")
        if url:
            return url
        raise Exception(f"VikingFile upload failed: {result}")

    async def _upload_dir(self, input_directory):
        links = []
        for root, _, files in await sync_to_async(oswalk, input_directory):
            for file in sorted(files):
                if self.listener.is_cancelled:
                    return links
                file_path = ospath.join(root, file)
                rel_root = ospath.relpath(root, ospath.dirname(input_directory))
                folder_path = (
                    f"{self.folder_path}/{rel_root}" if self.folder_path else rel_root
                )
                url = await self.upload_file(file_path, folder_path=folder_path)
                if url:
                    links.append((file, url))
                    self.total_files += 1
        return links

    async def _make_telegraph_page(self, links):
        content = "".join(
            f'<p>{i}. <a href="{url}">{name}</a></p>'
            for i, (name, url) in enumerate(links, 1)
        )
        page = await telegraph.create_page(title=self.listener.name, content=content)
        return f"https://telegra.ph/{page['path']}"

    async def upload(self):
        try:
            LOGGER.info(f"VikingFile Uploading: {self._path}")
            self._updater = SetInterval(self.update_interval, self.progress)
            if not self.token:
                LOGGER.warning("VikingFile hash not set. Uploading anonymously.")
            await self._upload_process()
        except Exception as err:
            if isinstance(err, RetryError):
                LOGGER.info(f"Total Attempts: {err.last_attempt.attempt_number}")
                err = err.last_attempt.exception()
            err = str(err).replace(">", "").replace("<", "")
            LOGGER.error(err)
            await self.listener.on_upload_error(err)
            self._is_errored = True
        finally:
            if self._updater:
                self._updater.cancel()

    async def _upload_process(self):
        if await aiopath.isfile(self._path):
            link = await self.upload_file(self._path, folder_path=self.folder_path)
            if not link:
                raise ValueError("Failed to upload file to VikingFile")
            mime_type = "File"
            self.total_files = 1
        elif await aiopath.isdir(self._path):
            links = await self._upload_dir(self._path)
            if not links:
                raise ValueError("Failed to upload folder to VikingFile")
            mime_type = "Folder"
            self.total_folders = 1
            link = links[0][1] if len(links) == 1 else await self._make_telegraph_page(links)
        else:
            raise ValueError("Invalid file path.")

        if not self.listener.is_cancelled:
            LOGGER.info(f"Uploaded To VikingFile: {self.listener.name}")
            await self.listener.on_upload_complete(
                link, self.total_files, self.total_folders, mime_type, dir_id=""
            )

    async def cancel_task(self):
        self.listener.is_cancelled = True
        if self.is_uploading:
            LOGGER.info(f"Cancelling VikingFile Upload: {self.listener.name}")
            await self.listener.on_upload_error("VikingFile upload has been cancelled.")
