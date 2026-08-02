from asyncio import gather, iscoroutinefunction

from pyrogram.errors import QueryIdInvalid

from .. import (
    task_dict_lock,
    status_dict,
    task_dict,
    intervals,
    sabnzbd_client,
)
from ..core.config_manager import Config
from ..core.torrent_manager import TorrentManager
from ..core.jdownloader_booter import jdownloader
from ..helper.ext_utils.bot_utils import new_task
from ..helper.ext_utils.status_utils import (
    EngineStatus,
    MirrorStatus,
    get_readable_file_size,
    get_idle_status_message,
    speed_string_to_bytes,
)
from ..helper.telegram_helper.message_utils import (
    delete_message,
    send_status_message,
    update_status_message,
    edit_message,
)
from ..helper.telegram_helper.button_build import ButtonMaker
from .filetolink import build_filetolink_status


@new_task
async def task_status(_, message):
    async with task_dict_lock:
        count = len(task_dict)
    if count == 0:
        await send_status_message(message)
        await delete_message(message)
    else:
        text = message.text.split()
        if len(text) > 1:
            if text[1] == "me":
                user_id = message.from_user.id
            elif text[1].lstrip("-").isdigit():
                user_id = int(text[1])
            else:
                user_id = 0
        elif text[0].split('@')[0].endswith("_me"):
            user_id = message.from_user.id
        else:
            user_id = 0
            sid = message.chat.id
            if obj := intervals["status"].get(sid):
                obj.cancel()
                del intervals["status"][sid]
        await send_status_message(message, user_id)
        await delete_message(message)


async def get_download_status(download):
    eng = download.engine
    speed = (
        download.speed()
        if eng.startswith(("WzPyro", "yt-dlp", "RClone", "Google-API"))
        else 0
    )
    return (
        (
            await download.status()
            if iscoroutinefunction(download.status)
            else download.status()
        ),
        speed,
        eng,
    )


@new_task
async def status_pages(_, query):
    data = query.data.split()
    key = int(data[1])
    if data[2] in {"fl", "flp"}:
        requested_page = int(data[3]) if data[2] == "flp" and len(data) > 3 else 1
        msg, button = build_filetolink_status(key, page_no=requested_page)
        async with task_dict_lock:
            previous_view = None
            previous_page = 1
            if key in status_dict:
                previous_view = status_dict[key].get("view", "tasks")
                previous_page = status_dict[key].get("filetolink_page", 1)
                status_dict[key]["view"] = "filetolink"
                status_dict[key]["filetolink_page"] = requested_page
        result = await edit_message(query.message, msg, button)
        if isinstance(result, str) and previous_view is not None:
            async with task_dict_lock:
                if key in status_dict:
                    status_dict[key]["view"] = previous_view
                    status_dict[key]["filetolink_page"] = previous_page
    elif data[2] == "home":
        async with task_dict_lock:
            has_status = key in status_dict
            if has_status:
                status_dict[key]["view"] = "tasks"
        if has_status:
            await update_status_message(key, force=True)
            async with task_dict_lock:
                has_status = key in status_dict
            if not has_status:
                msg, button = get_idle_status_message(key)
                await edit_message(query.message, msg, button)
        else:
            msg, button = get_idle_status_message(key)
            await edit_message(query.message, msg, button)
    elif data[2] == "dismiss":
        await delete_message(query.message)
    elif data[2] == "ref":
        await update_status_message(key, force=True)
    elif data[2] in ["nex", "pre"]:
        async with task_dict_lock:
            if key in status_dict:
                if data[2] == "nex":
                    status_dict[key]["page_no"] += status_dict[key]["page_step"]
                else:
                    status_dict[key]["page_no"] -= status_dict[key]["page_step"]
    elif data[2] == "ps":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["page_step"] = int(data[3])
    elif data[2] == "st":
        async with task_dict_lock:
            if key in status_dict:
                status_dict[key]["status"] = data[3]
        await update_status_message(key, force=True)
    elif data[2] == "ov":
        message = query.message
        tasks = {
            "Download": 0,
            "Upload": 0,
            "Seed": 0,
            "Archive": 0,
            "Extract": 0,
            "Split": 0,
            "QueueDl": 0,
            "QueueUp": 0,
            "Clone": 0,
            "CheckUp": 0,
            "Pause": 0,
            "SamVid": 0,
            "ConvertMedia": 0,
            "FFmpeg": 0,
            "Encode": 0,
        }
        dl_speed = 0
        up_speed = 0
        seed_speed = 0

        async with task_dict_lock:
            status_results = await gather(
                *(get_download_status(download) for download in task_dict.values())
            )

        eng_status = EngineStatus()
        if any(
            eng in (eng_status.STATUS_ARIA2, eng_status.STATUS_QBIT)
            for _, __, eng in status_results
        ):
            dl_speed, seed_speed = await TorrentManager.overall_speed()

        if any(eng == eng_status.STATUS_SABNZBD for _, __, eng in status_results):
            if not Config.DISABLE_NZB and sabnzbd_client.LOGGED_IN:
                dl_speed += (
                    int(
                        float(
                            (await sabnzbd_client.get_downloads())["queue"].get(
                                "kbpersec", "0"
                            )
                        )
                    )
                    * 1024
                )

        if any(eng == eng_status.STATUS_JD for _, __, eng in status_results):
            if not Config.DISABLE_JD and jdownloader.is_connected:
                dl_speed += (
                    await jdownloader.device.downloadcontroller.get_speed_in_bytes()
                )

        for status, speed, _ in status_results:
            match status:
                case MirrorStatus.STATUS_DOWNLOAD:
                    tasks["Download"] += 1
                    if speed:
                        dl_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_UPLOAD:
                    tasks["Upload"] += 1
                    up_speed += speed_string_to_bytes(speed)
                case MirrorStatus.STATUS_SEED:
                    tasks["Seed"] += 1
                case MirrorStatus.STATUS_ARCHIVE:
                    tasks["Archive"] += 1
                case MirrorStatus.STATUS_EXTRACT:
                    tasks["Extract"] += 1
                case MirrorStatus.STATUS_SPLIT:
                    tasks["Split"] += 1
                case MirrorStatus.STATUS_QUEUEDL:
                    tasks["QueueDl"] += 1
                case MirrorStatus.STATUS_QUEUEUP:
                    tasks["QueueUp"] += 1
                case MirrorStatus.STATUS_CLONE:
                    tasks["Clone"] += 1
                case MirrorStatus.STATUS_CHECK:
                    tasks["CheckUp"] += 1
                case MirrorStatus.STATUS_PAUSED:
                    tasks["Pause"] += 1
                case MirrorStatus.STATUS_SAMVID:
                    tasks["SamVid"] += 1
                case MirrorStatus.STATUS_CONVERT:
                    tasks["ConvertMedia"] += 1
                case MirrorStatus.STATUS_FFMPEG:
                    tasks["FFmpeg"] += 1
                case MirrorStatus.STATUS_ENCODE:
                    tasks["Encode"] += 1
                case _:
                    tasks["Download"] += 1

        msg = f"""<b>✦ TASKS OVERVIEW</b>
<pre>
┌─ {'Download':<9}: {tasks["Download"]} | {'Upload':<9}: {tasks["Upload"]}
├─ {'Seed':<9}: {tasks["Seed"]} | {'Archive':<9}: {tasks["Archive"]}
├─ {'Extract':<9}: {tasks["Extract"]} | {'Split':<9}: {tasks["Split"]}
├─ {'QueueDL':<9}: {tasks["QueueDl"]} | {'QueueUP':<9}: {tasks["QueueUp"]}
├─ {'Clone':<9}: {tasks["Clone"]} | {'CheckUp':<9}: {tasks["CheckUp"]}
├─ {'Paused':<9}: {tasks["Pause"]} | {'SamVideo':<9}: {tasks["SamVid"]}
├─ {'Convert':<9}: {tasks["ConvertMedia"]} | {'FFmpeg':<9}: {tasks["FFmpeg"]}
├─ {'Encode':<9}: {tasks["Encode"]}
├─ ─── TOTAL SPEEDS ─────────────
├─ {'Download':<9}: {get_readable_file_size(dl_speed)}/s
├─ {'Upload':<9}: {get_readable_file_size(up_speed)}/s
└─ {'Seeding':<9}: {get_readable_file_size(seed_speed)}/s
</pre>
"""
        button = ButtonMaker()
        button.data_button("↩ BACK", f"status {data[1]} ref")
        await edit_message(message, msg, button.build_menu())

    try:
        await query.answer()
    except QueryIdInvalid:
        pass
