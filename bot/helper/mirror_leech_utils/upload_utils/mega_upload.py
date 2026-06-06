import os
from contextlib import suppress
from mimetypes import guess_type
from secrets import token_hex

from aiofiles.os import makedirs, path as aiopath
from aioshutil import rmtree
from mega import MegaApi, MegaCancelToken

from .... import LOGGER, task_dict, task_dict_lock
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.status_utils import get_readable_file_size
from ...listeners.mega_listener import AsyncMega, MegaAppListener, _mega_error_format
from ...mirror_leech_utils.status_utils.mega_status import MegaDownloadStatus
from ...telegram_helper.message_utils import update_status_message


def _make_cancel_token():
    if MegaCancelToken is None:
        return None
    try:
        return MegaCancelToken.createInstance()
    except Exception as e:
        LOGGER.error(f"Mega: failed to create cancel token: {e}")
        return None


async def _cleanup_dir(directory: str):
    if directory and await aiopath.exists(directory):
        await rmtree(directory, ignore_errors=True)


async def _upload_file(
    async_api, mega_listener, file_path, parent_node, custom_name
):
    cancel_token = _make_cancel_token()
    mega_listener._cancel_token = cancel_token
    mega_listener.error = None
    mega_listener.retryable_error = None
    mega_listener._bytes_transferred = 0
    mega_listener._total_downloaded_bytes = 0
    mega_listener._caller_manages_completion = True
    mega_listener._size = await sync_to_async(os.path.getsize, file_path)

    LOGGER.info(
        f"MegaUpload: uploading {custom_name} ({get_readable_file_size(mega_listener._size)})"
    )

    await async_api.startUpload(
        file_path,
        parent_node,
        custom_name,
        cancel_token,
    )
    await async_api.wait_for_transfer()

    if mega_listener.is_cancelled:
        return False
    if mega_listener.error:
        msg = _mega_error_format(mega_listener.error)
        LOGGER.error(f"MegaUpload error: {msg}")
        return False

    LOGGER.info(f"MegaUpload: completed {custom_name}")
    return True


async def add_mega_upload(listener, path, mega_email, mega_password, gid):
    if not mega_email or not mega_password:
        await listener.on_upload_error(
            "Mega credentials not configured for this user."
        )
        return

    mega_base = ""
    sdk_gid = token_hex(5)
    mega_base = os.path.join(
        os.path.dirname(path.rstrip("/")), ".mega_sdk", sdk_gid
    )
    mega_dir = os.path.join(mega_base, "main")
    await makedirs(mega_dir, exist_ok=True)

    async_api = AsyncMega()
    async_api.api = api = MegaApi("", mega_dir, "WZML-X", 4)
    mega_listener = MegaAppListener(async_api, listener)
    mega_listener._upload_mode = True
    async_api._mega_listener = mega_listener
    api.addListener(mega_listener)

    try:
        async with task_dict_lock:
            task_dict[listener.mid] = MegaDownloadStatus(listener, mega_listener, gid, "up")
        await update_status_message(listener.message.chat.id)

        await async_api.login(mega_email, mega_password)
        if mega_listener.error:
            await listener.on_upload_error(
                f"Mega login failed: {_mega_error_format(mega_listener.error)}"
            )
            return

        await async_api.fetchNodes()
        if mega_listener.error:
            await listener.on_upload_error(
                f"Mega fetch nodes failed: {_mega_error_format(mega_listener.error)}"
            )
            return

        root_node = mega_listener.node
        if not root_node:
            await listener.on_upload_error(
                "Failed to get Mega root node."
            )
            return

        LOGGER.info(f"MegaUpload: root node obtained, uploading from {path}")

        total_files = 0
        uploaded_files = 0
        mime_type = "application/octet-stream"

        if await aiopath.isdir(path):
            entries = await sync_to_async(os.listdir, path)
            for entry in entries:
                entry_path = os.path.join(path, entry)
                if await sync_to_async(os.path.isfile, entry_path):
                    total_files += 1

            if total_files == 0:
                await listener.on_upload_error(
                    f"MegaUpload: no files to upload in {path}"
                )
                return

            for entry in entries:
                if listener.is_cancelled:
                    return
                entry_path = os.path.join(path, entry)
                if await sync_to_async(os.path.isfile, entry_path):
                    ok = await _upload_file(
                        async_api, mega_listener, entry_path, root_node, entry
                    )
                    if ok:
                        uploaded_files += 1
                    else:
                        if not listener.is_cancelled:
                            await listener.on_upload_error(
                                f"MegaUpload failed for {entry}"
                            )
                        return

            mime_type = "Folder"

        else:
            total_files = 1
            file_name = os.path.basename(path)
            ok = await _upload_file(
                async_api, mega_listener, path, root_node, file_name
            )
            if ok:
                uploaded_files = 1
                mime_type = guess_type(file_name)[0] or "application/octet-stream"
            else:
                if not listener.is_cancelled:
                    await listener.on_upload_error(
                        f"MegaUpload failed for {file_name}"
                    )
                return

        if uploaded_files > 0 and not listener.is_cancelled:
            LOGGER.info(
                f"MegaUpload: completed, {uploaded_files}/{total_files} files"
            )
            await listener.on_upload_complete(
                None, uploaded_files, 0, mime_type
            )

    except Exception as e:
        LOGGER.error(
            f"Unexpected error in add_mega_upload: {e}", exc_info=True
        )
        if not listener.is_cancelled:
            await listener.on_upload_error(f"Internal error: {e}")
    finally:
        if async_api is not None:
            with suppress(Exception):
                await async_api.logout()
        await _cleanup_dir(mega_base)
