import os
from asyncio import Lock as AsyncLock, sleep
from contextlib import suppress
from secrets import token_hex

from aiofiles.os import makedirs, path as aiopath
from aioshutil import rmtree
from mega import MegaApi, MegaCancelToken

from .... import LOGGER, task_dict, task_dict_lock, user_data
from ....core.config_manager import Config
from ...telegram_helper.message_utils import send_status_message
from ...ext_utils.task_manager import (
    check_running_tasks,
    limit_checker,
    stop_duplicate_check,
)
from ...listeners.mega_listener import AsyncMega, MegaAppListener, MegaFolderListener, _mega_error_format
from ...mirror_leech_utils.status_utils.mega_status import MegaDownloadStatus
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus


_ACTIVE_MEGA_LINKS = set()
_ACTIVE_MEGA_LINKS_LOCK = AsyncLock()


def _is_folder_link(link: str) -> bool:
    if not link:
        return False
    return "/folder/" in link or "#F!" in link


def _get_subfolder_handle(link: str) -> str | None:
    if not link:
        return None
    # /folder/X/folder/Y format
    parts = link.split("/folder/")
    if len(parts) >= 3:
        handle = parts[-1].split("#")[0].split("/")[0].split("?")[0]
        if handle:
            return handle
    # #F!X#F!Y format
    parts = link.split("#F!")
    if len(parts) >= 3:
        handle = parts[-1].split("!")[0].split("/")[0].split("?")[0]
        if handle:
            return handle
    return None


def _make_cancel_token():
    if MegaCancelToken is None:
        return None
    try:
        return MegaCancelToken.createInstance()
    except Exception as e:
        LOGGER.error(f"Mega: failed to create cancel token: {e}")
        return None


async def _reserve_link(link: str):
    async with _ACTIVE_MEGA_LINKS_LOCK:
        if link in _ACTIVE_MEGA_LINKS:
            return False
        _ACTIVE_MEGA_LINKS.add(link)
        return True


async def _release_link(link: str):
    async with _ACTIVE_MEGA_LINKS_LOCK:
        _ACTIVE_MEGA_LINKS.discard(link)


async def _cleanup_dir(directory: str):
    if directory and await aiopath.exists(directory):
        await rmtree(directory, ignore_errors=True)


async def add_mega_download(listener, path):
    if Config.DISABLE_MEGA:
        await listener.on_download_error("Mega Link downloads are currently disabled by the Bot Owner.")
        return

    user_dict = user_data.get(listener.user_id, {})
    mega_email = user_dict.get("MEGA_EMAIL") or Config.MEGA_EMAIL
    mega_password = user_dict.get("MEGA_PASSWORD") or Config.MEGA_PASSWORD

    if not await _reserve_link(listener.link):
        await listener.on_download_error("This Mega link is already being downloaded! Wait for it to finish.")
        return

    async_api = None
    mega_base = ""
    try:
        sdk_gid = token_hex(5)
        await makedirs(path, exist_ok=True)
        mega_base = os.path.join(os.path.dirname(path.rstrip("/")), ".mega_sdk", sdk_gid)
        mega_dir = os.path.join(mega_base, "main")
        await makedirs(mega_dir, exist_ok=True)

        async_api = AsyncMega()
        async_api.api = api = MegaApi("", mega_dir, "WZML-X", 4)
        mega_listener = MegaAppListener(async_api, listener)
        async_api._mega_listener = mega_listener
        api.addListener(mega_listener)

        if _is_folder_link(listener.link):
            mega_folder_dir = os.path.join(mega_base, "folder")
            await makedirs(mega_folder_dir, exist_ok=True)
            async_api.folder_api = MegaApi("", mega_folder_dir, "WZML-X", 4)
            folder_listener = MegaFolderListener(mega_listener)
            async_api._folder_listener = folder_listener
            async_api.folder_api.addListener(folder_listener)

        if mega_email and mega_password:
            await async_api.login(mega_email, mega_password)
            if mega_listener.error:
                await listener.on_download_error(_mega_error_format(mega_listener.error))
                return
            await async_api.fetchNodes()
            if mega_listener.error:
                await listener.on_download_error(_mega_error_format(mega_listener.error))
                return

        if _is_folder_link(listener.link):
            await async_api.loginToFolder(listener.link)
            if mega_listener.error:
                await listener.on_download_error(_mega_error_format(mega_listener.error))
                return
            subfolder_handle = _get_subfolder_handle(listener.link)
            if subfolder_handle:
                try:
                    mega_listener._subfolder_target = async_api.folder_api.base64ToHandle(subfolder_handle)
                except Exception as e:
                    LOGGER.warning(f"Mega subfolder handle conversion failed: {e}")
            await async_api.fetchNodes(async_api.folder_api, source="folder")
            node = mega_listener.node
            if not node:
                await listener.on_download_error("Failed to get folder root node", is_limit=False)
                return
        else:
            await async_api.getPublicNode(listener.link)
            node = mega_listener.public_node
        if not node:
            await listener.on_download_error("Failed to resolve MEGA link")
            return

        listener.name = listener.name or mega_listener._name or f"MEGA_Download_{token_hex(5)}"
        listener.size = mega_listener._size
        gid = token_hex(5)

        msg, button = await stop_duplicate_check(listener)
        if msg:
            await listener.on_download_error(msg, button)
            return

        if limit_exceeded := await limit_checker(listener):
            await listener.on_download_error(limit_exceeded, is_limit=True)
            return

        added_to_queue, event = await check_running_tasks(listener)
        if added_to_queue:
            async with task_dict_lock:
                task_dict[listener.mid] = QueueStatus(listener, gid, "dl")
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
            await event.wait()
            if listener.is_cancelled:
                return

        async with task_dict_lock:
            task_dict[listener.mid] = MegaDownloadStatus(listener, mega_listener, gid, "dl")

        if added_to_queue:
            await listener.on_download_start()
        else:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)

        download_path = path
        if _is_folder_link(listener.link):
            download_path = os.path.join(path, listener.name)
            await makedirs(download_path, exist_ok=True)

        for attempt in range(5):
            cancel_token = _make_cancel_token()
            mega_listener._cancel_token = cancel_token
            mega_listener.error = None
            mega_listener.retryable_error = None
            mega_listener._bytes_transferred = 0
            mega_listener._total_downloaded_bytes = 0
            mega_listener._caller_manages_completion = False

            await async_api.startDownload(
                node,
                download_path,
                listener.name,
                None,
                False,
                cancel_token,
                3,
                2,
                False,
            )
            await async_api.wait_for_transfer()

            if listener.is_cancelled or mega_listener.is_cancelled:
                return
            if not mega_listener.retryable_error:
                return
            if attempt >= 4:
                await listener.on_download_error(_mega_error_format(mega_listener.retryable_error))
                return
            await _cleanup_dir(download_path)
            await sleep(2 ** attempt)

    except Exception as e:
        LOGGER.error(f"Unexpected error in add_mega_download: {e}", exc_info=True)
        if not listener.is_cancelled:
            await listener.on_download_error(f"Internal error: {e}")
    finally:
        await _release_link(listener.link)
        if async_api is not None:
            with suppress(Exception):
                await async_api.logout()
        await _cleanup_dir(mega_base)
