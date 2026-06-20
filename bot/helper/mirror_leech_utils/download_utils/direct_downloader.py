from secrets import token_hex

from .... import (
    LOGGER,
    task_dict,
    task_dict_lock,
)
from ...ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
    limit_checker,
)
from ...ext_utils.bot_utils import DEFAULT_BROWSER_USER_AGENT
from ...listeners.direct_listener import DirectListener
from ...mirror_leech_utils.status_utils.direct_status import DirectStatus
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...telegram_helper.message_utils import send_status_message


async def add_direct_download(listener, path):
    details = listener.link
    if not (contents := details.get("contents")):
        await listener.on_download_error(
            "Could not find any downloadable content at the provided URL. "
            "The link may be expired, behind a paywall, or unsupported. "
            "Supported sources: gdrive, mega, magnet, direct URL, telegram. "
            "Run /help mirror for the full list."
        )
        return
    listener.size = details["total_size"]

    # Phase 2.3 — disk space pre-check. Fail fast with a clear message
    # instead of failing mid-download with a confusing OSError.
    from ...ext_utils.disk_utils import check_disk_space, format_bytes
    from .... import DOWNLOAD_DIR
    if listener.size and not check_disk_space(listener.size, DOWNLOAD_DIR):
        from ...ext_utils.disk_utils import get_free_space_gb
        free_gb = get_free_space_gb(DOWNLOAD_DIR)
        required_gb = listener.size / (1024 ** 3)
        from ...ext_utils.error_messages import disk_full
        await listener.on_download_error(
            disk_full(required_gb, free_gb, DOWNLOAD_DIR).to_user_message()
        )
        return

    if not listener.name:
        listener.name = details["title"]
    path = f"{path}/{listener.name}"

    msg, button = await stop_duplicate_check(listener)
    if msg:
        await listener.on_download_error(msg, button)
        return

    if limit_exceeded := await limit_checker(listener):
        await listener.on_download_error(limit_exceeded, is_limit=True)
        return

    gid = token_hex(5)
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

    # Phase 2.2 — HTTP Range resume is handled natively by aria2 via
    # `continue=true` in configs/aria2/aria2.conf. When aria2 detects a
    # partial .aria2 control file at the target path, it resumes from
    # the last completed byte. No custom resume logic needed here.
    a2c_opt = {"follow-torrent": "false", "follow-metalink": "false"}
    if header := details.get("header"):
        a2c_opt["header"] = header
    if "user-agent" not in str(header).lower():
        a2c_opt["user-agent"] = DEFAULT_BROWSER_USER_AGENT
    directListener = DirectListener(path, listener, a2c_opt)

    async with task_dict_lock:
        task_dict[listener.mid] = DirectStatus(listener, directListener, gid)

    if add_to_queue:
        LOGGER.info(f"Start Queued Download from Direct Download: {listener.name}")
    else:
        LOGGER.info(f"Download from Direct Download: {listener.name}")
        await listener.on_download_start()
        if listener.multi <= 1:
            await send_status_message(listener.message)

    await directListener.download(contents)
