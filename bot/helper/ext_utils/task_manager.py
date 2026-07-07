from asyncio import Event, Semaphore
from time import time

from ... import (
    LOGGER,
    bot_cache,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
    queued_dl,
    queued_up,
    user_data,
)
from ...core.config_manager import Config
from ..mirror_leech_utils.gdrive_utils.search import GoogleDriveSearch
from ..telegram_helper.filters import CustomFilters
from ..telegram_helper.tg_utils import check_botpm, forcesub, verify_token
from .bot_utils import get_telegraph_list, sync_to_async, safe_int
from .files_utils import get_base_name, check_storage_threshold
from .links_utils import is_gdrive_id
from .status_utils import get_readable_time, get_readable_file_size, get_specific_tasks

# Phase 3.5 — upload parallelism semaphore. Limits concurrent uploads
# to Config.UPLOAD_PARALLELISM (default 3). Downloads proceed at their
# own pace; the download→upload handoff acquires this semaphore.
_upload_semaphore = None


def get_upload_semaphore():
    """Return the upload semaphore, creating it lazily on first use.
    Reads Config.UPLOAD_PARALLELISM at creation time — operators who
    change this config must restart the bot for it to take effect."""
    global _upload_semaphore
    if _upload_semaphore is None:
        limit = max(1, int(getattr(Config, "UPLOAD_PARALLELISM", 3) or 3))
        _upload_semaphore = Semaphore(limit)
        LOGGER.info(f"Upload parallelism: {limit} concurrent uploads")
    return _upload_semaphore


async def stop_duplicate_check(listener):
    if (
        isinstance(listener.up_dest, int)
        or listener.is_leech
        or listener.select
        or not is_gdrive_id(listener.up_dest)
        or (listener.up_dest.startswith("mtp:") and listener.stop_duplicate)
        or not listener.stop_duplicate
        or listener.same_dir
    ):
        return False, None

    name = listener.name
    LOGGER.info(f"Checking File/Folder if already in Drive: {name}")

    if listener.compress:
        name = f"{name}.zip"
    elif listener.extract:
        try:
            name = get_base_name(name)
        except Exception:
            name = None

    if name is not None:
        telegraph_content, contents_no = await sync_to_async(
            GoogleDriveSearch(stop_dup=True, no_multi=listener.is_clone).drive_list,
            name,
            listener.up_dest,
            listener.user_id,
        )
        if telegraph_content:
            msg = f"File/Folder is already available in Drive.\nHere are {contents_no} list results:"
            button = await get_telegraph_list(telegraph_content)
            return msg, button

    return False, None


async def check_running_tasks(listener, state="dl"):
    all_limit = safe_int(Config.QUEUE_ALL)
    state_limit = (
        safe_int(Config.QUEUE_DOWNLOAD)
        if state == "dl"
        else safe_int(Config.QUEUE_UPLOAD)
    )
    event = None
    is_over_limit = False
    async with queue_dict_lock:
        if state == "up" and listener.mid in non_queued_dl:
            non_queued_dl.remove(listener.mid)
        if (
            (all_limit or state_limit)
            and not listener.force_run
            and not (listener.force_upload and state == "up")
            and not (listener.force_download and state == "dl")
        ):
            dl_count = len(non_queued_dl)
            up_count = len(non_queued_up)
            t_count = dl_count if state == "dl" else up_count
            is_over_limit = (
                all_limit
                and dl_count + up_count >= all_limit
                and (not state_limit or t_count >= state_limit)
            ) or (state_limit and t_count >= state_limit)
            if is_over_limit:
                event = Event()
                if state == "dl":
                    queued_dl[listener.mid] = event
                else:
                    queued_up[listener.mid] = event
        if not is_over_limit:
            if state == "up":
                non_queued_up.add(listener.mid)
            else:
                non_queued_dl.add(listener.mid)

    return is_over_limit, event


async def start_dl_from_queued(mid: int):
    queued_dl[mid].set()
    del queued_dl[mid]
    non_queued_dl.add(mid)


async def start_up_from_queued(mid: int):
    queued_up[mid].set()
    del queued_up[mid]
    non_queued_up.add(mid)


async def start_from_queued():
    if all_limit := safe_int(Config.QUEUE_ALL):
        dl_limit = safe_int(Config.QUEUE_DOWNLOAD)
        up_limit = safe_int(Config.QUEUE_UPLOAD)
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            up = len(non_queued_up)
            all_ = dl + up
            if all_ < all_limit:
                f_tasks = all_limit - all_
                if queued_up and (not up_limit or up < up_limit):
                    for index, mid in enumerate(list(queued_up.keys()), start=1):
                        await start_up_from_queued(mid)
                        f_tasks -= 1
                        if f_tasks == 0 or (up_limit and index >= up_limit - up):
                            break
                if queued_dl and (not dl_limit or dl < dl_limit) and f_tasks != 0:
                    # Phase 3.4 — sort queued downloads by priority (DESC)
                    # then by insertion order (ASC = FIFO for same priority).
                    # task_dict[mid] holds the status object; .listener holds
                    # the TaskConfig with .priority attribute.
                    sorted_mids = _sort_queue_by_priority(queued_dl)
                    for index, mid in enumerate(sorted_mids, start=1):
                        await start_dl_from_queued(mid)
                        if (dl_limit and index >= dl_limit - dl) or index == f_tasks:
                            break
        return

    if up_limit := safe_int(Config.QUEUE_UPLOAD):
        async with queue_dict_lock:
            up = len(non_queued_up)
            if queued_up and up < up_limit:
                f_tasks = up_limit - up
                # Phase 3.4 — sort upload queue by priority too
                sorted_mids = _sort_queue_by_priority(queued_up)
                for index, mid in enumerate(sorted_mids, start=1):
                    await start_up_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_up:
                # Phase 3.4 — sort by priority even when unlimited
                sorted_mids = _sort_queue_by_priority(queued_up)
                for mid in sorted_mids:
                    await start_up_from_queued(mid)

    if dl_limit := safe_int(Config.QUEUE_DOWNLOAD):
        async with queue_dict_lock:
            dl = len(non_queued_dl)
            if queued_dl and dl < dl_limit:
                f_tasks = dl_limit - dl
                # Phase 3.4 — sort by priority
                sorted_mids = _sort_queue_by_priority(queued_dl)
                for index, mid in enumerate(sorted_mids, start=1):
                    await start_dl_from_queued(mid)
                    if index == f_tasks:
                        break
    else:
        async with queue_dict_lock:
            if queued_dl:
                # Phase 3.4 — sort by priority even when unlimited
                sorted_mids = _sort_queue_by_priority(queued_dl)
                for mid in sorted_mids:
                    await start_dl_from_queued(mid)


def _sort_queue_by_priority(queue_dict):
    """Phase 3.4 — Sort a queue dict's keys by priority (DESC) then
    insertion order (ASC = FIFO for same priority).

    queue_dict is {mid: event} — insertion-ordered in Python 3.7+.
    We look up each mid in task_dict to get the listener.priority.
    Mids not in task_dict get priority 0 (default).
    """
    try:
        def priority_of(mid):
            status = task_dict.get(mid)
            if status is None:
                return 0
            listener = getattr(status, "listener", None)
            if listener is None:
                return 0
            return getattr(listener, "priority", 0) or 0
        # Sort by (-priority, insertion_order) — Python's sort is stable,
        # so same-priority items keep insertion order.
        return sorted(list(queue_dict.keys()), key=lambda m: -priority_of(m))
    except Exception:
        # Fallback to insertion order on any error
        return list(queue_dict.keys())


async def limit_checker(listener, yt_playlist=0):
    LOGGER.info("Checking Size Limit...")
    if await CustomFilters.sudo("", listener.message):
        LOGGER.info("SUDO User. Skipping Size Limit...")
        return

    size = listener.size

    async def recurr_limits(limits):
        limit_exceeded = ""
        for condition, attr, name in limits:
            if condition and (limit := getattr(Config, attr, 0)):
                if attr == "PLAYLIST_LIMIT":
                    if yt_playlist >= limit:
                        limit_exceeded = f"┠ <b>{name} Limit Count</b> → {limit}"
                else:
                    byte_limit = limit * 1024**3
                    if size >= byte_limit:
                        limit_exceeded = f"┠ <b>{name} Limit</b> → {get_readable_file_size(byte_limit)}"

                LOGGER.info(
                    f"{name} Limit Breached: {listener.name} & Size: {get_readable_file_size(size)}"
                )
                break
        return limit_exceeded

    limits = [
        (listener.is_torrent or listener.is_qbit, "TORRENT_LIMIT", "Torrent"),
        (listener.is_mega, "MEGA_LIMIT", "Mega"),
        (listener.is_gdrive, "GD_DL_LIMIT", "GDriveDL"),
        (listener.is_clone, "CLONE_LIMIT", "Clone"),
        (listener.is_jd, "JD_LIMIT", "JDownloader"),
        (listener.is_nzb, "NZB_LIMIT", "SABnzbd"),
        (listener.is_rclone, "RC_DL_LIMIT", "RCloneDL"),
        (listener.is_ytdlp, "YTDLP_LIMIT", "YT-DLP"),
        (bool(yt_playlist), "PLAYLIST_LIMIT", "Playlist"),
        (True, "DIRECT_LIMIT", "Direct"),
    ]
    limit_exceeded = await recurr_limits(limits)

    if not limit_exceeded:
        extra_limits = [
            (listener.is_leech, "LEECH_LIMIT", "Leech"),
            (listener.compress, "ARCHIVE_LIMIT", "Archive"),
            (listener.extract, "EXTRACT_LIMIT", "Extract"),
        ]
        limit_exceeded = await recurr_limits(extra_limits)

        if Config.STORAGE_LIMIT and not listener.is_clone:
            limit = Config.STORAGE_LIMIT * 1024**3
            if not await check_storage_threshold(
                size, limit, any([listener.compress, listener.extract])
            ):
                limit_exceeded = f"┠ <b>Threshold Storage Limit</b> → {get_readable_file_size(limit)}"

    if limit_exceeded:
        return limit_exceeded + f"\n┖ <b>Task By</b> → {listener.tag}"


"""
class UsageChecks: # TODO: Dynamic Check for All Task

class DailyUsageChecks:
"""


async def user_interval_check(user_id):
    bot_cache.setdefault("time_interval", {})
    if (time_interval := bot_cache["time_interval"].get(user_id, False)) and (
        time() - time_interval
    ) < (UTI := Config.USER_TIME_INTERVAL):
        return UTI - (time() - time_interval)
    bot_cache["time_interval"][user_id] = time()
    return None


async def pre_task_check(message):
    LOGGER.info("Running Pre Task Checks ...")
    msg = []
    button = None
    if await CustomFilters.sudo("", message):
        return msg, button
    user_id = (message.from_user or message.sender_chat).id
    if Config.RSS_CHAT and user_id == int(Config.RSS_CHAT):
        return msg, button
    user_dict = user_data.get(user_id, {})
    if message.chat.type != message.chat.type.BOT:
        if ids := Config.FORCE_SUB_IDS:
            _msg, button = await forcesub(message, ids, button)
            if _msg:
                msg.append(_msg)
        if Config.BOT_PM or user_dict.get("BOT_PM"):  # or config_dict['SAFE_MODE']:
            _msg, button = await check_botpm(message, button)
            if _msg:
                msg.append(_msg)
    if (uti := Config.USER_TIME_INTERVAL) and (
        ut := await user_interval_check(user_id)
    ):
        msg.append(
            f"┠ <b>Waiting Time</b> → {get_readable_time(ut)}\n┠ <i>User's Time Interval Restrictions</i> → {get_readable_time(uti)}"
        )
    bmax_tasks = safe_int(user_dict.get("bmax_tasks", Config.BOT_MAX_TASKS))
    if bmax_tasks > 0 and len(await get_specific_tasks("All", False)) >= bmax_tasks:
        msg.append(
            f"┠ Max Concurrent Bot's Tasks Limit exceeded.\n┠ Bot Tasks Limit : {bmax_tasks} task"
        )

    maxtask = safe_int(user_dict.get("maxtask", Config.USER_MAX_TASKS))
    if maxtask > 0 and len(await get_specific_tasks("All", user_id)) >= maxtask:
        msg.append(
            f"┠ Max Concurrent User's Task(s) Limit exceeded! \n┠ User Task Limit : {maxtask} tasks"
        )

    token_msg, button = await verify_token(user_id, button)
    if token_msg is not None:
        msg.append(token_msg)

    # Phase 5.5 — per-user quota check. Sudo users bypass. If the user
    # has exceeded their daily or monthly quota, block the task with a
    # clear message including when the quota resets.
    quota_msg = await _check_user_quota(user_id)
    if quota_msg:
        msg.append(quota_msg)

    if msg:
        _user = message.from_user or message.sender_chat
        username = _user.mention if hasattr(_user, 'mention') else _user.title
        final_msg = f"⌬ <b>Task Checks :</b>\n│\n┟ <b>Name</b> → {username}\n┃\n"
        for i, m_part in enumerate(msg, 1):
            final_msg += f"{m_part}\n"
        if button is not None:
            button = button.build_menu(2)
        return final_msg, button

    return None, None


async def _check_user_quota(user_id):
    """Phase 5.5 — Check if user has exceeded their daily/monthly quota.

    Returns a message string if quota exceeded, or None if OK.
    Sudo users bypass — checked by caller (pre_task_check returns early
    for sudo). Reads Config.USER_DAILY_QUOTA_GB and USER_MONTHLY_QUOTA_GB.
    Uses database.get_user_quota_usage() which lazily resets expired
    counters.
    """
    try:
        from .db_handler import database
        daily_limit_gb = safe_int(Config.USER_DAILY_QUOTA_GB)
        monthly_limit_gb = safe_int(Config.USER_MONTHLY_QUOTA_GB)
        if daily_limit_gb <= 0 and monthly_limit_gb <= 0:
            return None  # no quota configured
        if database.db is None:
            return None  # DB not connected — can't check quota
        daily_bytes, monthly_bytes, daily_reset, monthly_reset = (
            await database.get_user_quota_usage(user_id)
        )
        from .status_utils import get_readable_file_size
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        msgs = []
        if daily_limit_gb > 0:
            daily_limit_bytes = daily_limit_gb * 1024 ** 3
            if daily_bytes >= daily_limit_bytes:
                # Calculate reset time
                if daily_reset:
                    reset_in = 86400 - (now - daily_reset).total_seconds()
                    reset_str = get_readable_time(max(0, int(reset_in)))
                else:
                    reset_str = "24h"
                msgs.append(
                    f"┠ <b>Daily quota exceeded</b> → "
                    f"{get_readable_file_size(daily_bytes)} / "
                    f"{daily_limit_gb} GB\n"
                    f"┠ <i>Resets in</i> → {reset_str}"
                )
        if monthly_limit_gb > 0:
            monthly_limit_bytes = monthly_limit_gb * 1024 ** 3
            if monthly_bytes >= monthly_limit_bytes:
                if monthly_reset:
                    reset_in = 30 * 86400 - (now - monthly_reset).total_seconds()
                    reset_str = get_readable_time(max(0, int(reset_in)))
                else:
                    reset_str = "30d"
                msgs.append(
                    f"┠ <b>Monthly quota exceeded</b> → "
                    f"{get_readable_file_size(monthly_bytes)} / "
                    f"{monthly_limit_gb} GB\n"
                    f"┠ <i>Resets in</i> → {reset_str}"
                )
        return "\n".join(msgs) if msgs else None
    except Exception as e:
        LOGGER.warning(f"Quota check error for user {user_id}: {e}")
        return None  # don't block on quota check errors
