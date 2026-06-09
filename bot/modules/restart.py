from asyncio import create_subprocess_exec, gather, sleep
from datetime import datetime
from html import escape
from os import execl as osexecl
from sys import executable

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove
from pytz import timezone

from bot.version import get_version

from .. import LOGGER, intervals, sabnzbd_client, scheduler, user_data
from ..core.config_manager import Config, BinConfig
from ..core.jdownloader_booter import jdownloader
from ..core.tg_client import TgClient
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import new_task, resolve_command
from ..helper.ext_utils.db_handler import database
from ..helper.ext_utils.files_utils import clean_all
from ..helper.listeners.mega_listener import mega_cleanup
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper import button_build
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    get_tg_link_message,
    send_message,
)


@new_task
async def restart_bot(_, message):
    buttons = button_build.ButtonMaker()
    buttons.data_button("Yes!", "botrestart confirm")
    buttons.data_button("No!", "botrestart cancel")
    button = buttons.build_menu(2)
    await send_message(
        message, "<i>Are you really sure you want to restart the bot ?</i>", button
    )


@new_task
async def restart_sessions(_, message):
    buttons = button_build.ButtonMaker()
    buttons.data_button("Yes!", "sessionrestart confirm")
    buttons.data_button("No!", "sessionrestart cancel")
    button = buttons.build_menu(2)
    await send_message(
        message,
        "<i>Are you really sure you want to restart the session(s) ?!</>",
        button,
    )


async def send_incomplete_task_message(cid, msg_id, msg):
    try:
        if msg.startswith("⌬ <b><i>Restarted Successfully!</i></b>"):
            await TgClient.bot.edit_message_text(
                chat_id=cid,
                message_id=msg_id,
                text=msg,
                disable_web_page_preview=True,
            )
            await remove(".restartmsg")
        else:
            await TgClient.bot.send_message(
                chat_id=cid,
                text=msg,
                disable_web_page_preview=True,
                disable_notification=True,
            )
    except Exception as e:
        LOGGER.error(e)


def _truncate(text, limit=110):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _task_command(text):
    if not text:
        return ""
    command = text.split(maxsplit=1)[0].lstrip("/")
    return command.split("@", 1)[0]


def _command_matches(command, commands):
    if isinstance(commands, str):
        commands = [commands]
    return command in commands


def _task_title(message, task):
    if message and message.text:
        return message.text.split("\n", 1)[0]
    return task["_id"]


async def _get_task_message(task):
    try:
        message, client_name = await get_tg_link_message(task["_id"])
    except Exception as e:
        LOGGER.error(f"Failed to fetch incomplete task message {task['_id']}: {e}")
        return None, None
    if isinstance(message, list):
        return None, None
    client = TgClient.user if client_name == "user" and TgClient.user else TgClient.bot
    return message, client


async def _hydrate_incomplete_task(task):
    update = {}
    message = None
    if not task.get("user_id") or not task.get("name"):
        message, _ = await _get_task_message(task)
    if not task.get("user_id") and message:
        user = message.from_user or message.sender_chat
        if user:
            update["user_id"] = user.id
    if not task.get("name"):
        update["name"] = _task_title(message, task)
    if update:
        await database.update_incomplete_task(task["_id"], update)
        task.update(update)
    return task


async def _send_recovery_message(user_id, tasks, now):
    buttons = button_build.ButtonMaker()
    buttons.data_button("▶️ Resume All", f"resume_tasks_{user_id}")
    buttons.data_button("🗑️ Clear All", f"clear_tasks_{user_id}")

    msg = (
        "☀️ <b>Bot Restarted</b>\n\n"
        f"You had <code>{len(tasks)}</code> incomplete task(s):"
    )
    for index, task in enumerate(tasks[:20], start=1):
        title = escape(_truncate(task.get("name") or task["_id"]))
        msg += f"\n{index}. <a href='{task['_id']}'>{title}</a>"
    if len(tasks) > 20:
        msg += f"\n...and {len(tasks) - 20} more."
    msg += (
        "\n\nWhat would you like to do?"
        f"\n\n<code>{now.strftime('%d/%m/%y %I:%M:%S %p')} {Config.TIMEZONE}</code>"
    )

    user_dict = user_data.get(user_id, {})
    target = user_id if Config.BOT_PM or user_dict.get("BOT_PM") else tasks[0]["cid"]
    return await send_message(target, msg, buttons.build_menu(2))


async def notify_incomplete_tasks():
    if not (Config.INCOMPLETE_TASK_NOTIFIER and Config.DATABASE_URL):
        return

    tasks = await database.get_incomplete_task_docs(notified=False)
    if not tasks:
        return

    by_user = {}
    for task in tasks:
        task = await _hydrate_incomplete_task(task)
        user_id = task.get("user_id")
        if not user_id:
            LOGGER.warning(f"Skipping incomplete task without user_id: {task['_id']}")
            continue
        by_user.setdefault(user_id, []).append(task)

    now = datetime.now(timezone(Config.TIMEZONE))
    for user_id, user_tasks in by_user.items():
        try:
            result = await _send_recovery_message(user_id, user_tasks, now)
            if not isinstance(result, str):
                await database.mark_incomplete_tasks_notified(
                    [task["_id"] for task in user_tasks]
                )
            await sleep(1)
        except Exception as e:
            LOGGER.error(f"Failed to send incomplete task recovery to {user_id}: {e}")


async def _resume_from_command(task):
    command = task.get("command", "")
    user_id = task.get("user_id", 0)
    reply_to_msg_id = task.get("reply_to_msg_id", 0)
    if not command or not user_id:
        return False

    handler = resolve_command(command)
    if handler is None:
        return False

    try:
        user = await TgClient.bot.get_users(user_id)
    except Exception as e:
        LOGGER.warning(f"Resume: cannot get user {user_id}: {e}")
        return False

    try:
        msg = await TgClient.bot.send_message(
            chat_id=task["cid"],
            text=command,
            disable_notification=True,
        )
        msg.text = command
        msg.from_user = user
        if reply_to_msg_id:
            try:
                reply_msg = await TgClient.bot.get_messages(
                    chat_id=task["cid"], message_ids=reply_to_msg_id
                )
                if reply_msg:
                    msg.reply_to_message = reply_msg
            except Exception as e:
                LOGGER.warning(f"Resume: cannot fetch reply msg {reply_to_msg_id}: {e}")
        await handler(TgClient.bot, msg)
        await delete_message(msg)
        return True
    except Exception as e:
        LOGGER.error(f"Resume: failed for '{command}' in {task['cid']}: {e}")
        return False


async def auto_resume_incomplete_tasks():
    if not (Config.INC_TASK_RESUME and Config.DATABASE_URL):
        return

    tasks = await database.get_incomplete_task_docs(notified=True)
    if not tasks:
        return

    await database.clear_incomplete_tasks_by_links([task["_id"] for task in tasks])
    resumed = 0
    skipped = 0
    for task in tasks:
        task = await _hydrate_incomplete_task(task)
        if await _resume_from_command(task):
            resumed += 1
        else:
            message, client = await _get_task_message(task)
            if message and getattr(message, "text", None) and await _requeue_task(client, message):
                resumed += 1
            else:
                skipped += 1
        await sleep(1)
    LOGGER.info(f"Auto-resumed incomplete tasks: {resumed}; skipped: {skipped}")


async def _requeue_task(client, message):
    from .clone import clone_node
    from .mirror_leech import (
        jd_leech,
        jd_mirror,
        leech,
        mirror,
        nzb_leech,
        nzb_mirror,
        qb_leech,
        qb_mirror,
    )
    from .uphoster import uphoster
    from .ytdlp import ytdl, ytdl_leech

    command = _task_command(message.text)
    handlers = (
        (BotCommands.MirrorCommand, mirror),
        (BotCommands.QbMirrorCommand, qb_mirror),
        (BotCommands.JdMirrorCommand, jd_mirror),
        (BotCommands.NzbMirrorCommand, nzb_mirror),
        (BotCommands.LeechCommand, leech),
        (BotCommands.QbLeechCommand, qb_leech),
        (BotCommands.JdLeechCommand, jd_leech),
        (BotCommands.NzbLeechCommand, nzb_leech),
        (BotCommands.YtdlCommand, ytdl),
        (BotCommands.YtdlLeechCommand, ytdl_leech),
        (BotCommands.CloneCommand, clone_node),
        (BotCommands.UpHosterCommand, uphoster),
    )
    for commands, handler in handlers:
        if _command_matches(command, commands):
            await handler(client, message)
            return True
    return False


def _callback_user_id(data):
    try:
        return int(data.rsplit("_", 1)[1])
    except Exception:
        return 0


async def _reject_wrong_user(query, user_id):
    if not query.from_user or query.from_user.id != user_id:
        await query.answer(
            "This recovery action belongs to another user.",
            show_alert=True,
        )
        return True
    return False


@new_task
async def resume_incomplete_tasks(_, query):
    user_id = _callback_user_id(query.data)
    if await _reject_wrong_user(query, user_id):
        return
    await query.answer()

    tasks = await database.get_user_incomplete_tasks(user_id)
    if not tasks:
        await edit_message(
            query.message,
            "<b>No incomplete tasks found.</b>\nThey may have already been handled.",
        )
        return

    await database.clear_incomplete_tasks_by_links([task["_id"] for task in tasks])

    resumed = 0
    skipped = 0
    for task in tasks:
        message, client = await _get_task_message(task)
        if not message or not getattr(message, "text", None):
            skipped += 1
            continue
        if await _requeue_task(client, message):
            resumed += 1
        else:
            skipped += 1
        await sleep(1)

    await edit_message(
        query.message,
        "<b>Incomplete Task Recovery</b>\n"
        f"Re-queued: <code>{resumed}</code>\n"
        f"Skipped: <code>{skipped}</code>",
    )


@new_task
async def clear_incomplete_tasks(_, query):
    user_id = _callback_user_id(query.data)
    if await _reject_wrong_user(query, user_id):
        return
    await query.answer()

    cleared = await database.clear_user_incomplete_tasks(user_id)
    await edit_message(
        query.message,
        "<b>Incomplete Task Recovery</b>\n"
        f"Cleared <code>{cleared}</code> incomplete task record(s).",
    )


async def restart_notification():
    if await aiopath.isfile(".restartmsg"):
        with open(".restartmsg") as f:
            chat_id, msg_id = map(int, f)
    else:
        chat_id, msg_id = 0, 0

    now = datetime.now(timezone(Config.TIMEZONE))

    if Config.INC_TASK_RESUME:
        await auto_resume_incomplete_tasks()
    else:
        await notify_incomplete_tasks()

    if await aiopath.isfile(".restartmsg"):
        try:
            await TgClient.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"""⌬ <b><i>Restarted Successfully!</i></b>
┟ <b>Date:</b> {now.strftime("%d/%m/%y")}
┠ <b>Time:</b> {now.strftime("%I:%M:%S %p")}
┠ <b>TimeZone:</b> {Config.TIMEZONE}
┖ <b>Version:</b> {get_version()}""",
            )
        except Exception as e:
            LOGGER.error(e)
        await remove(".restartmsg")


@new_task
async def confirm_restart(_, query):
    await query.answer()
    data = query.data.split()
    message = query.message
    reply_to = message.reply_to_message
    await delete_message(message)
    if data[1] == "confirm":
        intervals["stopAll"] = True
        restart_message = await send_message(reply_to, "<i>Restarting...</i>")
        await delete_message(message)
        await TgClient.stop()
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if qb := intervals["qb"]:
            qb.cancel()
        if jd := intervals["jd"]:
            jd.cancel()
        if nzb := intervals["nzb"]:
            nzb.cancel()
        if st := intervals["status"]:
            for intvl in list(st.values()):
                intvl.cancel()
        await mega_cleanup()
        await clean_all()
        await TorrentManager.close_all()
        if sabnzbd_client.LOGGED_IN:
            await gather(
                sabnzbd_client.pause_all(),
                sabnzbd_client.delete_job("all", True),
                sabnzbd_client.purge_all(True),
                sabnzbd_client.delete_history("all", delete_files=True),
            )
            await sabnzbd_client.close()
        if jdownloader.is_connected:
            await gather(
                jdownloader.device.downloadcontroller.stop_downloads(),
                jdownloader.device.linkgrabber.clear_list(),
                jdownloader.device.downloads.cleanup(
                    "DELETE_ALL",
                    "REMOVE_LINKS_AND_DELETE_FILES",
                    "ALL",
                ),
            )
            await jdownloader.close()
        proc1 = await create_subprocess_exec(
            "pkill",
            "-9",
            "-f",
            f"gunicorn|{BinConfig.ARIA2_NAME}|{BinConfig.QBIT_NAME}|{BinConfig.FFMPEG_NAME}|{BinConfig.RCLONE_NAME}|java|{BinConfig.SABNZBD_NAME}|7z|split",
        )
        proc2 = await create_subprocess_exec("python3", "update.py")
        await gather(proc1.wait(), proc2.wait())
        async with aiopen(".restartmsg", "w") as f:
            await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
        osexecl(executable, executable, "-m", "bot")
    else:
        await delete_message(message, reply_to)
