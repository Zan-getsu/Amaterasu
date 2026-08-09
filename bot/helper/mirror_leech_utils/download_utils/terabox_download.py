import os
import posixpath
import re
from asyncio import Lock, sleep
from html import escape
from secrets import token_hex
from time import time

from aiofiles.os import makedirs, remove
from aiofiles.os import path as aiopath

try:
    from terabox import (
        TeraboxCancelled,
        TeraboxClient,
        TeraboxError,
        TeraboxFile,
        TeraboxPasswordError,
    )
except ImportError:
    TeraboxClient = None

from web.terabox_selection_store import (
    delete_state as _store_delete,
)
from web.terabox_selection_store import (
    read_state as _store_read,
)
from web.terabox_selection_store import (
    write_state as _store_write,
)

from .... import LOGGER, bot_loop, task_dict, task_dict_lock
from ....core.config_manager import Config
from ...ext_utils.bot_utils import get_valid_base_url, terabox_selection_buttons
from ...ext_utils.files_utils import check_storage_threshold
from ...ext_utils.status_utils import get_readable_file_size
from ...ext_utils.task_manager import (
    check_running_tasks,
    limit_checker,
    stop_duplicate_check,
)
from ...listeners.terabox_listener import TeraboxDownloadTracker
from ...telegram_helper.message_utils import send_message, send_status_message
from ..status_utils.queue_status import QueueStatus
from ..status_utils.terabox_status import TeraboxDownloadStatus

_SELECTION_TTL = 30 * 60
_UNSAFE_NAME_CHARS = re.compile(r'[/\\\x00:*?"<>|]')
_active_links = set()
_active_lock = Lock()
_selections = {}
_sweeper_task = None


def _sanitize_name(name):
    cleaned = _UNSAFE_NAME_CHARS.sub("_", str(name or "unnamed")).strip()
    return cleaned.rstrip(". ") or "unnamed"


async def _reserve_link(link):
    key = (link or "").strip().rstrip("/")
    async with _active_lock:
        if key in _active_links:
            return None
        _active_links.add(key)
    return key


async def _discard_link(key):
    if key:
        async with _active_lock:
            _active_links.discard(key)


async def _select_cookie(listener, purpose="Download"):
    cookie = getattr(listener, "terabox_cookie", "")
    if cookie and await aiopath.exists(cookie):
        return cookie
    selector = getattr(listener, "_terabox_cookie_path", None)
    if selector:
        cookie = await selector(purpose)
        if cookie:
            listener.terabox_cookie = cookie
            return cookie
    for path, label in (
        (f"terabox_cookies/{listener.user_id}.txt", "User Cookie"),
        ("terabox.txt", "Owner Cookie"),
    ):
        if await aiopath.exists(path):
            listener.terabox_cookie = path
            listener.terabox_cookie_source = label
            return path
    return ""


def _destination(base_path, root_name, original_top, file, single):
    if single:
        return os.path.join(base_path, _sanitize_name(root_name))
    parts = [part for part in file.path.lstrip("/").split("/") if part]
    if original_top and parts and parts[0] == original_top:
        parts = parts[1:]
    parts = [_sanitize_name(part) for part in parts] or [_sanitize_name(file.name)]
    return os.path.join(base_path, _sanitize_name(root_name), *parts)


async def _download_files(
    listener,
    client,
    path,
    files,
    tracker,
    *,
    single=False,
    original_top="",
    destinations=None,
):
    destinations = destinations or [
        _destination(path, listener.name, original_top, file, single)
        for file in files
    ]
    try:
        await client.reserve_files(
            list(zip(destinations, (file.size for file in files), strict=True))
        )
    except TeraboxError as error:
        await listener.on_download_error(str(error))
        return
    completed = 0
    failures = []
    for file, destination in zip(files, destinations, strict=True):
        if tracker.is_cancelled or listener.is_cancelled:
            return
        tracker.start_file()
        try:
            await client.download_file(
                file,
                destination,
                progress_cb=tracker.on_progress,
                cancel_event=tracker.cancel_event,
            )
            tracker.finish_file(file.size)
            completed += 1
        except TeraboxCancelled:
            return
        except TeraboxError as error:
            failures.append(f"{file.name}: {error}")
            for failed_path in (destination, destination + ".part"):
                if not await aiopath.exists(failed_path):
                    continue
                try:
                    await remove(failed_path)
                except OSError as cleanup_error:
                    LOGGER.warning(
                        "Could not remove failed TeraBox artifact %s: %s",
                        failed_path,
                        cleanup_error,
                    )
    if tracker.is_cancelled or listener.is_cancelled:
        return
    if not completed:
        await listener.on_download_error(
            f"All TeraBox files failed. {'; '.join(failures[:5])}"
        )
        return
    if failures:
        notice = (
            f"TeraBox downloaded {completed} file(s), but {len(failures)} failed. "
            f"Continuing with the completed files. {'; '.join(failures[:5])}"
        )
        try:
            await send_message(
                listener.message,
                f"<b>Partial TeraBox download</b>\n{escape(notice)}",
            )
        except Exception as error:
            LOGGER.warning("Could not send TeraBox partial-download notice: %s", error)
        await listener.on_download_complete()
        return
    await listener.on_download_complete()


async def _validate_and_queue(listener, gid):
    message, button = await stop_duplicate_check(listener)
    if message:
        await listener.on_download_error(message, button)
        return None
    if exceeded := await limit_checker(listener):
        await listener.on_download_error(exceeded, is_limit=True)
        return None
    queued, event = await check_running_tasks(listener)
    if queued:
        async with task_dict_lock:
            task_dict[listener.mid] = QueueStatus(listener, gid, "dl")
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)
        await event.wait()
        if listener.is_cancelled:
            return None
    reserve = Config.STORAGE_LIMIT * 1024**3
    if listener.size and not await check_storage_threshold(listener.size, reserve):
        await listener.on_download_error(
            "Insufficient disk space. Required with reserve: "
            f"{get_readable_file_size(listener.size + reserve)}",
            is_limit=True,
        )
        return None
    return queued


async def _sweep_selections():
    while True:
        await sleep(60)
        cutoff = time() - _SELECTION_TTL
        for gid, state in list(_selections.items()):
            if state.get("created_at", 0) > cutoff:
                continue
            _selections.pop(gid, None)
            _store_delete(gid)
            await _discard_link(state.get("link_key"))
            try:
                await state["client"].aclose()
            except Exception as error:
                LOGGER.warning("Could not close expired TeraBox client: %s", error)
            try:
                await state["listener"].on_download_error(
                    "TeraBox file selection expired. Re-run the command."
                )
            except Exception as error:
                LOGGER.warning("Could not notify expired TeraBox selection: %s", error)


def _ensure_sweeper():
    global _sweeper_task
    if _sweeper_task is None or _sweeper_task.done():
        _sweeper_task = bot_loop.create_task(_sweep_selections())


async def _start_web_selection(
    listener,
    client,
    result,
    path,
    gid,
    link_key,
    prompt,
):
    _ensure_sweeper()
    tracker = TeraboxDownloadTracker(listener)
    files = list(result.file_entries)
    _selections[gid] = {
        "result": result,
        "client": client,
        "listener": listener,
        "download_path": path,
        "link_key": link_key,
        "tracker": tracker,
        "created_at": time(),
    }

    async def cleanup():
        state = _selections.pop(gid, None)
        _store_delete(gid)
        await _discard_link(link_key)
        if state:
            await state["client"].aclose()

    tracker._cleanup_selection = cleanup
    metadata = [
        {
            "name": file.name,
            "path": file.path,
            "size": file.size,
            "is_dir": file.is_dir,
            "id": str(file.fs_id),
        }
        for file in files
    ]
    if not _store_write(gid, metadata, []):
        _selections.pop(gid, None)
        await listener.on_download_error("Failed to persist TeraBox selection state.")
        return False
    listener.size = sum(file.size for file in files)
    await listener.remove_processing()
    async with task_dict_lock:
        task_dict[listener.mid] = TeraboxDownloadStatus(
            listener,
            tracker,
            f"terabox_{gid}",
            "dl",
        )
    await send_message(
        listener.message,
        prompt,
        terabox_selection_buttons(f"terabox_{gid}"),
    )
    return True


def get_terabox_selection_owner_id(gid):
    state = _selections.get(gid)
    listener = state.get("listener") if state else None
    return getattr(listener, "user_id", None)


async def add_terabox_download(listener, path):
    if TeraboxClient is None:
        await listener.on_download_error(
            "teraboxSDK is not installed in this image. Rebuild with the SDK enabled."
        )
        return
    if not Config.TERABOX_ENABLED:
        await listener.on_download_error("TeraBox is disabled by the bot owner.")
        return
    cookie = await _select_cookie(listener)
    link_key = await _reserve_link(listener.link)
    if link_key is None:
        await listener.on_download_error(
            "This TeraBox link is already being downloaded."
        )
        return
    client = None
    handoff = False
    try:
        await makedirs(path, exist_ok=True)
        client = TeraboxClient(
            cookie_file=os.path.abspath(cookie) if cookie else "",
        )
        result = await client.resolve(listener.link, recursive=True)
        files = list(result.file_entries)
        if not files:
            await listener.on_download_error("No downloadable files found.")
            return
        listener.name = listener.name or _sanitize_name(result.name)
        gid = token_hex(5)
        if listener.select and result.is_folder and len(files) > 1:
            if not get_valid_base_url():
                await listener.on_download_error(
                    "A valid public BASE_URL is required for TeraBox selection."
                )
                return
            handoff = await _start_web_selection(
                listener,
                client,
                result,
                path,
                gid,
                link_key,
                "Your TeraBox folder is ready. Choose files, then press Done Selecting.",
            )
            return
        listener.size = sum(file.size for file in files)
        queued = await _validate_and_queue(listener, gid)
        if queued is None:
            return
        tracker = TeraboxDownloadTracker(listener)
        async with task_dict_lock:
            task_dict[listener.mid] = TeraboxDownloadStatus(
                listener, tracker, gid, "dl"
            )
        if not queued:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
        await _download_files(
            listener,
            client,
            path,
            files,
            tracker,
            single=not result.is_folder and len(files) == 1,
            original_top=result.name,
        )
    except TeraboxPasswordError as error:
        await listener.on_download_error(str(error))
    except TeraboxError as error:
        await listener.on_download_error(f"TeraBox: {error}")
    except Exception as error:
        LOGGER.exception("TeraBox download failed")
        await listener.on_download_error(f"TeraBox internal error: {error}")
    finally:
        if not handoff:
            await _discard_link(link_key)
            if client:
                await client.aclose()


async def _expand_account_selection(client, selection):
    multiple = len(selection) > 1
    pairs = []
    for selected in selection:
        if selected.get("is_dir"):
            folder = (selected.get("path") or "/").rstrip("/")
            result = await client.walk_account_dir(folder or "/")
            top = _sanitize_name(selected.get("name") or "TeraBox")
            for file in result.file_entries:
                inside = (
                    file.path[len(folder) :].lstrip("/")
                    if folder and file.path.startswith(folder)
                    else file.path.lstrip("/")
                )
                pairs.append(
                    (file, posixpath.join(top, inside) if multiple else inside)
                )
        else:
            file = TeraboxFile(
                name=selected.get("name") or "file",
                path=selected.get("path") or "",
                fs_id=str(selected.get("fs_id", "")),
                size=int(selected.get("size", 0) or 0),
                is_dir=False,
            )
            pairs.append((file, file.name))
    return pairs


async def add_terabox_account_download(listener, path):
    if TeraboxClient is None:
        await listener.on_download_error("teraboxSDK is not installed in this image.")
        return
    if not Config.TERABOX_ENABLED:
        await listener.on_download_error("TeraBox is disabled by the bot owner.")
        return
    cookie = await _select_cookie(listener)
    if not cookie:
        await listener.on_download_error("No TeraBox cookie found.")
        return
    web_selection = bool(listener._tbx_web and get_valid_base_url())
    selection = list(listener._tbx_selection or [])
    if not web_selection and not selection:
        await listener.on_download_error("No TeraBox selection was made.")
        return
    client = TeraboxClient(cookie_file=os.path.abspath(cookie))
    handoff = False
    try:
        await client.login()
        await makedirs(path, exist_ok=True)
        if web_selection:
            result = await client.walk_account_dir("/")
            if not result.file_entries:
                await listener.on_download_error("Your TeraBox account is empty.")
                return
            listener.name = listener.name or "TeraBox"
            gid = token_hex(5)
            handoff = await _start_web_selection(
                listener,
                client,
                result,
                path,
                gid,
                "",
                "Your TeraBox account is ready. Choose files, then press Done Selecting.",
            )
            return
        pairs = await _expand_account_selection(client, selection)
        files = [file for file, _ in pairs]
        if not files:
            await listener.on_download_error("No downloadable files selected.")
            return
        listener.name = listener.name or _sanitize_name(
            selection[0].get("name")
            if len(selection) == 1
            else f"TeraBox_{len(selection)}_items"
        )
        single = len(selection) == 1 and not selection[0].get("is_dir")
        destinations = (
            [os.path.join(path, _sanitize_name(listener.name))]
            if single
            else [
                os.path.join(
                    path,
                    _sanitize_name(listener.name),
                    *[_sanitize_name(part) for part in relative.split("/") if part],
                )
                for _, relative in pairs
            ]
        )
        listener.size = sum(file.size for file in files)
        gid = token_hex(5)
        queued = await _validate_and_queue(listener, gid)
        if queued is None:
            return
        tracker = TeraboxDownloadTracker(listener)
        async with task_dict_lock:
            task_dict[listener.mid] = TeraboxDownloadStatus(
                listener, tracker, gid, "dl"
            )
        if not queued:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
        await _download_files(
            listener,
            client,
            path,
            files,
            tracker,
            single=single,
            destinations=destinations,
        )
    except TeraboxError as error:
        await listener.on_download_error(f"TeraBox: {error}")
    except Exception as error:
        LOGGER.exception("TeraBox account download failed")
        await listener.on_download_error(f"TeraBox internal error: {error}")
    finally:
        if not handoff:
            await client.aclose()


async def resume_terabox_with_selection(gid):
    state = _selections.pop(gid, None)
    if not state:
        _store_delete(gid)
        return
    listener = state["listener"]
    client = state["client"]
    tracker = state["tracker"]
    tracker._cleanup_selection = None
    try:
        stored = _store_read(gid)
        selected_ids = set(stored.get("selected_ids", []) if stored else [])
        selected = [
            file
            for file in state["result"].file_entries
            if str(file.fs_id) in selected_ids
        ]
        if not selected:
            await listener.on_download_error("No valid files selected.")
            return
        listener.size = sum(file.size for file in selected)
        queued = await _validate_and_queue(listener, f"terabox_{gid}")
        if queued is None:
            return
        async with task_dict_lock:
            task_dict[listener.mid] = TeraboxDownloadStatus(
                listener, tracker, f"terabox_{gid}", "dl"
            )
        if not queued:
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
        await _download_files(
            listener,
            client,
            state["download_path"],
            selected,
            tracker,
            original_top=state["result"].name,
        )
    except Exception as error:
        LOGGER.exception("Could not resume TeraBox selection")
        await listener.on_download_error(f"TeraBox internal error: {error}")
    finally:
        _store_delete(gid)
        await _discard_link(state.get("link_key"))
        await client.aclose()


async def cancel_terabox_selection(gid):
    state = _selections.pop(gid, None)
    _store_delete(gid)
    if not state:
        return
    state["tracker"]._cleanup_selection = None
    await _discard_link(state.get("link_key"))
    await state["client"].aclose()
    await state["listener"].on_download_error("Cancelled by user")
