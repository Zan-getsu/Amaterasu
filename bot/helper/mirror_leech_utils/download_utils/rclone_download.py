from asyncio import gather, sleep
from json import loads
from secrets import token_hex
from time import time

from aiofiles import open as aiopen
from aiofiles.os import remove

from web.rclone_selection_store import (
    delete_state as _rcl_store_delete,
)
from web.rclone_selection_store import (
    read_state as _rcl_store_read,
)
from web.rclone_selection_store import (
    write_state as _rcl_store_write,
)

from .... import LOGGER, bot_loop, task_dict, task_dict_lock
from ....core.config_manager import BinConfig
from ...ext_utils.bot_utils import (
    cmd_exec,
    get_valid_base_url,
    rclone_selection_buttons,
)
from ...ext_utils.task_manager import (
    check_running_tasks,
    limit_checker,
    stop_duplicate_check,
)
from ...mirror_leech_utils.rclone_utils.transfer import RcloneTransferHelper
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...mirror_leech_utils.status_utils.rclone_status import RcloneStatus
from ...telegram_helper.message_utils import send_message, send_status_message

_RCLONE_SELECT_TTL = 30 * 60
_rclone_selections = {}
_rcl_sweeper_task = None


async def add_rclone_download(listener, path):
    if listener.link.startswith("mrcc:"):
        listener.link = listener.link.split("mrcc:", 1)[1]
        config_path = f"rclone/{listener.user_id}.conf"
    else:
        config_path = "rclone.conf"

    if ":" not in listener.link:
        await listener.on_download_error(
            "Invalid Rclone link — expected format `<remote>:<path>`."
        )
        return
    remote, listener.link = listener.link.split(":", 1)
    listener.link = listener.link.strip("/")
    rclone_select = False
    if listener.link.startswith("rclone_select"):
        rclone_select = True
        rpath = ""
    else:
        rpath = listener.link

    cmd1 = [
        BinConfig.RCLONE_NAME,
        "lsjson",
        "--fast-list",
        "--stat",
        "--no-mimetype",
        "--no-modtime",
        "--config",
        config_path,
        f"{remote}:{rpath}",
    ]
    cmd2 = [
        BinConfig.RCLONE_NAME,
        "size",
        "--fast-list",
        "--json",
        "--config",
        config_path,
        f"{remote}:{rpath}",
    ]
    if rclone_select:
        cmd2.extend(("--files-from", listener.link))
        res = await cmd_exec(cmd2)
        if res[2] != 0:
            if res[2] != -9:
                msg = f"Error: While getting rclone stat/size. Path: {remote}:{listener.link}. Stderr: {res[1][:4000]}"
                await listener.on_download_error(msg)
            return
        try:
            rsize = loads(res[0])
        except Exception as err:
            await listener.on_download_error(f"RcloneDownload JsonLoad: {err}")
            return
        if not listener.name:
            listener.name = listener.link
        path += listener.name
    else:
        res1, res2 = await gather(cmd_exec(cmd1), cmd_exec(cmd2))
        if res1[2] != 0 or res2[2] != 0:
            if res1[2] != -9:
                err = res1[1] or res2[1]
                msg = f"Error: While getting rclone stat/size. Path: {remote}:{listener.link}. Stderr: {err[:4000]}"
                await listener.on_download_error(msg)
            return
        try:
            rstat = loads(res1[0])
            rsize = loads(res2[0])
        except Exception as err:
            await listener.on_download_error(f"RcloneDownload JsonLoad: {err}")
            return
        if rstat["IsDir"]:
            if not listener.name:
                listener.name = (
                    listener.link.rsplit("/", 1)[-1] if listener.link else remote
                )
            path += listener.name
        else:
            listener.name = listener.name or listener.link.rsplit("/", 1)[-1]
    listener.size = rsize["bytes"]
    gid = token_hex(5)

    if not rclone_select:
        msg, button = await stop_duplicate_check(listener)
        if msg:
            await listener.on_download_error(msg, button)
            return
        if limit_exceeded := await limit_checker(listener):
            await listener.on_download_error(limit_exceeded, is_limit=True)
            return

    add_to_queue, event = await check_running_tasks(listener)
    if add_to_queue:
        LOGGER.info(f"Added to Queue/Download: {listener.name}")
        async with task_dict_lock:
            task_dict[listener.mid] = QueueStatus(listener, gid, "dl")
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)
        await event.wait()
        if listener.is_cancelled:
            return

    RCTransfer = RcloneTransferHelper(listener)
    async with task_dict_lock:
        task_dict[listener.mid] = RcloneStatus(listener, RCTransfer, gid, "dl")

    if add_to_queue:
        LOGGER.info(f"Start Queued Download with rclone: {listener.link}")
    else:
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)
        LOGGER.info(f"Download with rclone: {listener.link}")

    try:
        await RCTransfer.download(remote, config_path, path)
    finally:
        if rclone_select:
            try:
                await remove(listener.link)
            except FileNotFoundError:
                pass


async def _sweep_rclone_selections():
    while True:
        await sleep(60)
        now = time()
        stale = [
            gid
            for gid, state in list(_rclone_selections.items())
            if now - state.get("created_at", 0) >= _RCLONE_SELECT_TTL
        ]
        for gid in stale:
            state = _rclone_selections.pop(gid, None)
            _rcl_store_delete(gid)
            listener = state.get("listener") if state else None
            if listener is not None:
                try:
                    await listener.on_download_error(
                        "Rclone file selection expired. Re-run the command."
                    )
                except Exception as error:
                    LOGGER.error(f"Rclone selection expiry notification failed: {error}")


def _ensure_rcl_sweeper():
    global _rcl_sweeper_task
    if _rcl_sweeper_task is None or _rcl_sweeper_task.done():
        _rcl_sweeper_task = bot_loop.create_task(_sweep_rclone_selections())


def _parse_rclone_link(link, user_id):
    if link.startswith("mrcc:"):
        return link.split("mrcc:", 1)[1], f"rclone/{user_id}.conf", True
    return link, "rclone.conf", False


async def add_rclone_web_selection(listener, path):
    if not get_valid_base_url():
        await add_rclone_download(listener, path)
        return
    raw, config_path, user_config = _parse_rclone_link(
        listener.link, listener.user_id
    )
    if ":" not in raw or "rclone_select" in raw:
        await add_rclone_download(listener, path)
        return
    remote, remote_path = raw.split(":", 1)
    remote_path = remote_path.strip("/")
    target = f"{remote}:{remote_path}"
    stat_result = await cmd_exec(
        [
            BinConfig.RCLONE_NAME,
            "lsjson",
            "--stat",
            "--no-mimetype",
            "--no-modtime",
            "--config",
            config_path,
            target,
        ]
    )
    if stat_result[2] != 0:
        if stat_result[2] != -9:
            await listener.on_download_error(
                f"Rclone stat failed. Stderr: {stat_result[1][:3000]}"
            )
        return
    try:
        stat = loads(stat_result[0])
    except Exception:
        stat = {}
    if not stat.get("IsDir", False):
        await add_rclone_download(listener, path)
        return

    list_result = await cmd_exec(
        [
            BinConfig.RCLONE_NAME,
            "lsjson",
            "-R",
            "--files-only",
            "--fast-list",
            "--no-mimetype",
            "--no-modtime",
            "--config",
            config_path,
            target,
        ]
    )
    if list_result[2] != 0:
        if list_result[2] != -9:
            await listener.on_download_error(
                f"Rclone listing failed. Stderr: {list_result[1][:3000]}"
            )
        return
    try:
        entries = loads(list_result[0])
    except Exception as error:
        await listener.on_download_error(f"Rclone selection JSON error: {error}")
        return

    file_list = []
    for item in entries:
        relative = (item.get("Path") or "").strip("/")
        if item.get("IsDir") or not relative:
            continue
        full_path = f"{remote_path}/{relative}" if remote_path else relative
        file_list.append(
            {
                "name": item.get("Name") or relative.rsplit("/", 1)[-1],
                "path": full_path,
                "size": item.get("Size", 0) or 0,
                "is_dir": False,
                "id": full_path,
            }
        )
    if not file_list:
        await listener.on_download_error("No files found in this Rclone folder.")
        return

    _ensure_rcl_sweeper()
    gid = token_hex(5)
    _rclone_selections[gid] = {
        "listener": listener,
        "user_config": user_config,
        "remote": remote,
        "folder": remote_path,
        "download_path": path,
        "created_at": time(),
    }
    if not _rcl_store_write(gid, file_list, []):
        _rclone_selections.pop(gid, None)
        await listener.on_download_error("Failed to persist Rclone selection state.")
        return
    listener.size = sum(item["size"] for item in file_list)
    await listener.remove_processing()
    await send_message(
        listener.message,
        "Your Rclone folder is ready. Choose files, then press Done Selecting.",
        rclone_selection_buttons(f"rclone_{gid}"),
    )


def get_rclone_selection_owner_id(gid):
    state = _rclone_selections.get(gid)
    listener = state.get("listener") if state else None
    return getattr(listener, "user_id", None)


async def resume_rclone_with_selection(gid):
    state = _rclone_selections.pop(gid, None)
    if not state:
        _rcl_store_delete(gid)
        return
    listener = state["listener"]
    selection_file = f"rclone_select_{gid}.txt"
    try:
        stored = _rcl_store_read(gid)
        selected = list(stored.get("selected_ids", []) if stored else [])
        if not selected:
            await listener.on_download_error("No files selected")
            return
        metadata = stored.get("file_list", []) if stored else []
        selected_set = set(selected)
        listener.size = sum(
            int(item.get("size", 0) or 0)
            for item in metadata
            if item.get("id") in selected_set
        )
        if limit_exceeded := await limit_checker(listener):
            await listener.on_download_error(limit_exceeded, is_limit=True)
            return
        listener.name = listener.name or (
            state["folder"].rsplit("/", 1)[-1] if state["folder"] else state["remote"]
        )
        if duplicate := await stop_duplicate_check(listener):
            message, button = duplicate
            if message:
                await listener.on_download_error(message, button)
                return
        async with aiopen(selection_file, "w") as handle:
            await handle.write("\n".join(selected) + "\n")
        prefix = "mrcc:" if state["user_config"] else ""
        listener.link = f"{prefix}{state['remote']}:{selection_file}"
        await add_rclone_download(listener, state["download_path"])
    except Exception as error:
        LOGGER.error(f"Could not resume Rclone selection: {error}", exc_info=True)
        if not listener.is_cancelled:
            await listener.on_download_error(f"Internal error: {error}")
    finally:
        _rcl_store_delete(gid)
        try:
            await remove(selection_file)
        except FileNotFoundError:
            pass


async def cancel_rclone_selection(gid):
    state = _rclone_selections.pop(gid, None)
    _rcl_store_delete(gid)
    listener = state.get("listener") if state else None
    if listener is not None:
        await listener.on_download_error("Cancelled by user")
