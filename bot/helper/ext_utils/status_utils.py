from asyncio import gather, iscoroutinefunction
from html import escape
from pyrogram.enums import ButtonStyle
from re import findall
from time import time

from psutil import cpu_percent, disk_usage, virtual_memory

from ... import (
    DOWNLOAD_DIR,
    bot_cache,
    bot_start_time,
    status_dict,
    task_dict,
    task_dict_lock,
)
from ...core.config_manager import Config
from .network_utils import system_network_rate
from ..telegram_helper.button_build import ButtonMaker
from ..telegram_helper.compat import get_user_mention

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


class MirrorStatus:
    STATUS_UPLOAD = "Upload"
    STATUS_DOWNLOAD = "Download"
    STATUS_CLONE = "Clone"
    STATUS_QUEUEDL = "QueueDl"
    STATUS_QUEUEUP = "QueueUp"
    STATUS_PAUSED = "Pause"
    STATUS_ARCHIVE = "Archive"
    STATUS_EXTRACT = "Extract"
    STATUS_SPLIT = "Split"
    STATUS_CHECK = "CheckUp"
    STATUS_SEED = "Seed"
    STATUS_SAMVID = "SamVid"
    STATUS_CONVERT = "Convert"
    STATUS_FFMPEG = "FFmpeg"
    STATUS_YT = "YouTube"
    STATUS_METADATA = "Metadata"
    STATUS_ENCODE = "Encode"


class EngineStatus:
    def __init__(self):
        ver = bot_cache.get("eng_versions", {})
        self.STATUS_ARIA2 = f"Aria2 v{ver.get('aria2', 'N/A')}"
        self.STATUS_AIOHTTP = f"AioHttp v{ver.get('aiohttp', 'N/A')}"
        self.STATUS_GDAPI = f"Google-API v{ver.get('gapi', 'N/A')}"
        self.STATUS_QBIT = f"qBit v{ver.get('qBittorrent', 'N/A')}"
        self.STATUS_TGRAM = f"WzPyro v{ver.get('wzgram', 'N/A')}"
        self.STATUS_MEGA = f"MegaSDK v{ver.get('mega', 'N/A')}"
        self.STATUS_TERABOX = f"teraboxSDK v{ver.get('terabox', 'N/A')}"
        self.STATUS_YTDLP = f"yt-dlp v{ver.get('yt-dlp', 'N/A')}"
        self.STATUS_FFMPEG = f"ffmpeg v{ver.get('ffmpeg', 'N/A')}"
        self.STATUS_7Z = f"7z v{ver.get('7z', 'N/A')}"
        self.STATUS_RCLONE = f"RClone v{ver.get('rclone', 'N/A')}"
        self.STATUS_SABNZBD = f"SABnzbd+ v{ver.get('SABnzbd+', 'N/A')}"
        self.STATUS_QUEUE = "QSystem v2"
        self.STATUS_JD = "JDownloader v2"
        self.STATUS_YT = "Youtube-Api"
        self.STATUS_METADATA = "Metadata"
        self.STATUS_UPHOSTER = "Uphoster"


STATUSES = {
    "ALL": "All",
    "DL": MirrorStatus.STATUS_DOWNLOAD,
    "UP": MirrorStatus.STATUS_UPLOAD,
    "QD": MirrorStatus.STATUS_QUEUEDL,
    "QU": MirrorStatus.STATUS_QUEUEUP,
    "AR": MirrorStatus.STATUS_ARCHIVE,
    "EX": MirrorStatus.STATUS_EXTRACT,
    "SD": MirrorStatus.STATUS_SEED,
    "CL": MirrorStatus.STATUS_CLONE,
    "CM": MirrorStatus.STATUS_CONVERT,
    "SP": MirrorStatus.STATUS_SPLIT,
    "SV": MirrorStatus.STATUS_SAMVID,
    "FF": MirrorStatus.STATUS_FFMPEG,
    "PA": MirrorStatus.STATUS_PAUSED,
    "CK": MirrorStatus.STATUS_CHECK,
    "EN": MirrorStatus.STATUS_ENCODE,
}


async def get_task_by_gid(gid: str):
    async with task_dict_lock:
        for tk in task_dict.values():
            if hasattr(tk, "seeding"):
                await tk.update()
            if tk.gid() == gid or tk.gid().startswith(gid):
                return tk
        return None


async def get_specific_tasks(status, user_id):
    if status == "All":
        if user_id:
            return [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        else:
            return list(task_dict.values())
    tasks_to_check = (
        [tk for tk in task_dict.values() if tk.listener.user_id == user_id]
        if user_id
        else list(task_dict.values())
    )
    coro_tasks = []
    coro_tasks.extend(tk for tk in tasks_to_check if iscoroutinefunction(tk.status))
    coro_statuses = await gather(*[tk.status() for tk in coro_tasks])
    result = []
    coro_index = 0
    for tk in tasks_to_check:
        if tk in coro_tasks:
            st = coro_statuses[coro_index]
            coro_index += 1
        else:
            st = tk.status()
        if (st == status) or (
            status == MirrorStatus.STATUS_DOWNLOAD and st not in STATUSES.values()
        ):
            result.append(tk)
    return result


async def get_all_tasks(req_status: str, user_id):
    async with task_dict_lock:
        return await get_specific_tasks(req_status, user_id)


def get_raw_file_size(size):
    num, unit = size.split()
    return int(float(num) * (1024 ** SIZE_UNITS.index(unit)))


def get_readable_file_size(size_in_bytes):
    if not size_in_bytes:
        return "0B"
    if size_in_bytes < 0:
        return "Unknown"

    index = 0
    while size_in_bytes >= 1024 and index < len(SIZE_UNITS) - 1:
        size_in_bytes /= 1024
        index += 1

    return f"{size_in_bytes:.2f}{SIZE_UNITS[index]}"


def get_readable_time(seconds: int):
    periods = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
    result = ""
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f"{int(period_value)}{period_name}"
    return result


def get_raw_time(time_str: str) -> int:
    time_units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(
        int(value) * time_units[unit]
        for value, unit in findall(r"(\d+)([dhms])", time_str)
    )


def time_to_seconds(time_duration):
    try:
        parts = time_duration.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(float, parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = map(float, parts)
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = float(parts[0])
        else:
            return 0
        return hours * 3600 + minutes * 60 + seconds
    except Exception:
        return 0


def speed_string_to_bytes(size_text: str):
    size = 0
    size_text = size_text.lower()
    if "k" in size_text:
        size += float(size_text.split("k")[0]) * 1024
    elif "m" in size_text:
        size += float(size_text.split("m")[0]) * 1048576
    elif "g" in size_text:
        size += float(size_text.split("g")[0]) * 1073741824
    elif "t" in size_text:
        size += float(size_text.split("t")[0]) * 1099511627776
    elif "b" in size_text:
        size += float(size_text.split("b")[0])
    return size


def get_progress_bar_string(pct):
    pct = float(str(pct).strip("%"))
    p = min(max(pct, 0), 100)
    slots = 10
    full = int(p * slots / 100)
    filled, empty = _get_progress_bar_icons()
    return f"{filled * full}{empty * (slots - full)}"


def _get_progress_bar_icons():
    icons = str(Config.PROGRESS_BAR or "").strip()
    filled, empty = "█", "░"
    if ":" in icons:
        custom_filled, custom_empty = icons.split(":", 1)
        if custom_filled and custom_empty:
            filled, empty = custom_filled, custom_empty
    elif len(icons) >= 2:
        filled, empty = icons[0], icons[1]
    return escape(filled, quote=False), escape(empty, quote=False)


def _get_status_icon(status):
    status_text = str(status).casefold()
    status_icons = (
        ("download", "📥"),
        ("upload", "📤"),
        ("seed", "🌱"),
        ("queue", "⏳"),
        ("pause", "⏸"),
        ("archive", "🗜"),
        ("extract", "📦"),
        ("split", "✂"),
        ("clone", "♻"),
        ("check", "🔎"),
        ("encode", "🎞"),
        ("ffmpeg", "🎬"),
    )
    return next(
        (icon for keyword, icon in status_icons if keyword in status_text),
        "⚙",
    )


async def get_readable_message(sid, is_user, page_no=1, status="All", page_step=1):
    msg = ""
    button = None

    tasks = await get_specific_tasks(status, sid if is_user else None)

    STATUS_LIMIT = Config.STATUS_LIMIT if Config.STATUS_LIMIT > 0 else 10
    tasks_no = len(tasks)
    pages = (max(tasks_no, 1) + STATUS_LIMIT - 1) // STATUS_LIMIT
    if page_no > pages:
        page_no = (page_no - 1) % pages + 1
        status_dict[sid]["page_no"] = page_no
    elif page_no < 1:
        page_no = pages - (abs(page_no) % pages)
        status_dict[sid]["page_no"] = page_no
    start_position = (page_no - 1) * STATUS_LIMIT

    msg = "<b>✦ ACTIVE TASKS</b>\n\n"

    for index, task in enumerate(
        tasks[start_position : STATUS_LIMIT + start_position], start=1
    ):
        if status != "All":
            tstatus = status
        elif iscoroutinefunction(task.status):
            tstatus = await task.status()
        else:
            tstatus = task.status()
            
        task_name = escape(task.name())
        task_number = index + start_position
        msg += (
            f"<b>{_get_status_icon(tstatus)} {task_number:02d}. "
            f"<i>{task_name}</i></b>"
        )
        
        if getattr(task.listener, "subname", False):
            sub_name = escape(task.listener.subname)
            msg += f"\n • <b>Subtask:</b> <code>{sub_name}</code>"

        elapsed = time() - task.listener.message.date.timestamp()

        _user = task.listener.message.from_user or task.listener.message.sender_chat
        _user_mention = get_user_mention(_user)
        _user_id = _user.id

        if (
            tstatus not in [MirrorStatus.STATUS_SEED, MirrorStatus.STATUS_QUEUEUP]
            and task.listener.progress
        ):
            progress = task.progress()
            if task.listener.subname:
                subsize = f" / {get_readable_file_size(task.listener.subsize)}"
                ac = len(task.listener.files_to_proceed)
                count = f"( {task.listener.proceed_count} / {ac or '?'} )"
            else:
                subsize = ""
                count = ""
            
            msg += f"\n • <b>Status:</b> <code>{escape(str(tstatus))}</code>"
            msg += (
                f"\n • <b>Progress:</b> {get_progress_bar_string(progress)} "
                f"<code>{escape(str(progress))}</code>"
            )
            msg += (
                f"\n • <b>Processed:</b> "
                f"<code>{escape(str(task.processed_bytes()))}{subsize} "
                f"of {escape(str(task.size()))}</code>"
            )
            if count:
                msg += f"\n • <b>Files:</b> <code>{count}</code>"
            msg += (
                f"\n • <b>Speed:</b> <code>{escape(str(task.speed()))}</code>"
                f"  •  <b>ETA:</b> <code>{escape(str(task.eta()))}</code>"
            )
            msg += (
                f"\n • <b>Elapsed:</b> "
                f"<code>{get_readable_time(elapsed)}</code>"
            )
            
            if tstatus == MirrorStatus.STATUS_DOWNLOAD and (
                task.listener.is_torrent or task.listener.is_qbit
            ):
                try:
                    msg += (
                        f"\n • <b>Peers:</b> "
                        f"<code>{task.seeders_num()} seeders · "
                        f"{task.leechers_num()} leechers</code>"
                    )
                except Exception:
                    pass
        elif tstatus == MirrorStatus.STATUS_SEED:
            msg += f"\n • <b>Status:</b> <code>{escape(str(tstatus))}</code>"
            msg += f"\n • <b>Size:</b> <code>{escape(str(task.size()))}</code>"
            msg += (
                f"\n • <b>Uploaded:</b> "
                f"<code>{escape(str(task.uploaded_bytes()))}</code>"
            )
            msg += (
                f"\n • <b>Speed:</b> "
                f"<code>{escape(str(task.seed_speed()))}</code>"
                f"  •  <b>Ratio:</b> "
                f"<code>{escape(str(task.ratio()))}</code>"
            )
            msg += (
                f"\n • <b>Seed time:</b> "
                f"<code>{escape(str(task.seeding_time()))}</code>"
            )
        else:
            msg += f"\n • <b>Status:</b> <code>{escape(str(tstatus))}</code>"
            msg += f"\n • <b>Size:</b> <code>{escape(str(task.size()))}</code>"
        msg += (
            f"\n • <b>Engine:</b> <code>{escape(str(task.engine))}</code>"
        )
        msg += (
            f"\n • <b>Mode:</b> "
            f"<code>{escape(str(task.listener.mode[0]))} → "
            f"{escape(str(task.listener.mode[1]))}</code>"
        )
        from ..telegram_helper.bot_commands import BotCommands

        select_action = ""
        if tstatus in [
            MirrorStatus.STATUS_DOWNLOAD,
            MirrorStatus.STATUS_PAUSED,
            MirrorStatus.STATUS_QUEUEDL,
        ]:
            if (
                task.listener.is_torrent
                or task.listener.is_qbit
                or task.listener.is_nzb
            ):
                select_action = (
                    f"/{BotCommands.SelectCommand[1]}_{task.gid()[:8]}"
                )

        msg += (
            f"\n • <b>User:</b> {_user_mention} "
            f"<code>{_user_id}</code>"
        )
        if select_action:
            msg += f"\n • <b>Select:</b> {select_action}"
        msg += (
            f"\n • <b>Stop:</b> "
            f"/{BotCommands.CancelTaskCommand[1]}_{task.gid()[:8]}\n\n"
        )

    if len(msg) == 0:
        if status == "All":
            return None, None
        else:
            msg += f"<code>No Active {status} Tasks!</code>\n\n"

    msg += "<b>✦ SYSTEM METRICS</b>\n<pre>\n"
    
    buttons = ButtonMaker()
    if not is_user:
        buttons.data_button("📜 TSTATS", f"status {sid} ov", position="header", style=ButtonStyle.PRIMARY)
    if len(tasks) > STATUS_LIMIT:
        buttons.data_button("❮ PREV", f"status {sid} pre", position="header")
        buttons.data_button("NEXT ❯", f"status {sid} nex", position="header")
        if tasks_no > 30:
            for i in [1, 2, 4, 6, 8, 10, 15]:
                buttons.data_button(str(i), f"status {sid} ps {i}", position="footer")
    if status != "All" or tasks_no > 20:
        for label, status_value in list(STATUSES.items()):
            if status_value != status:
                buttons.data_button(f"▸ {label.upper()}", f"status {sid} st {status_value}")
    buttons.data_button("↻ REFRESH", f"status {sid} ref", position="header", style=ButtonStyle.PRIMARY)
    button = buttons.build_menu(8)

    metrics = []
    if len(tasks) > STATUS_LIMIT:
        metrics.append(f"{'Tasks':<9}: {tasks_no}")
        metrics.append(f"{'Page':<9}: {page_no} / {pages}")
        metrics.append(f"{'Step':<9}: {page_step}")

    download_rate, upload_rate = system_network_rate.sample()
    metrics.append(f"{'CPU':<9}: {cpu_percent()}%")
    metrics.append(f"{'RAM':<9}: {virtual_memory().percent}%")
    metrics.append(
        f"{'DL':<9}: ↓ {get_readable_file_size(download_rate)}/s"
    )
    metrics.append(
        f"{'UP':<9}: ↑ {get_readable_file_size(upload_rate)}/s"
    )
    metrics.append(f"{'Storage':<9}: 💾 {get_readable_file_size(disk_usage(DOWNLOAD_DIR).free)} Free")
    metrics.append(f"{'Uptime':<9}: ◷ {get_readable_time(time() - bot_start_time)}")

    for i, m in enumerate(metrics):
        if i == 0:
            msg += f"┌─ {m}\n"
        elif i == len(metrics) - 1:
            msg += f"└─ {m}\n</pre>"
        else:
            msg += f"├─ {m}\n"
    return msg, button
