from asyncio import create_subprocess_exec, gather, get_event_loop, sleep
from datetime import datetime
from html import escape
from os import execl as osexecl
from sys import executable

from aiofiles import open as aiopen
from aiofiles.os import path as aiopath, remove
from pytz import timezone
from datetime import timezone as dt_timezone

from bot.version import get_version

from .. import LOGGER, intervals, sabnzbd_client, scheduler, user_data
from ..core.config_manager import Config, BinConfig
from ..core.jdownloader_booter import jdownloader
from ..core.tg_client import TgClient
from ..core.torrent_manager import TorrentManager
from ..helper.ext_utils.bot_utils import THREAD_POOL, new_task, resolve_command
from ..helper.ext_utils.db_handler import database
from ..helper.listeners.mega_listener import mega_cleanup
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper import button_build
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    get_tg_link_message,
    send_message,
)

RECOVERY_TASK_DELAY = 5


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


def _parse_pm_task_id(task_id):
    parts = str(task_id).split(":")
    if len(parts) == 3 and parts[0] == "pm" and parts[1].isdigit() and parts[2].isdigit():
        return int(parts[1]), int(parts[2])
    return None, None


def _task_line(index, task):
    type_str = _get_task_type(task.get("command", ""))
    title = escape(_truncate(task.get("name") or task.get("command") or task["_id"]))
    task_id = str(task["_id"])
    if task_id.startswith("pm:"):
        return f"\n{index}. {type_str} {title}"
    return f"\n{index}. {type_str} <a href='{task_id}'>{title}</a>"


async def _get_task_message(task):
    if str(task["_id"]).startswith("pm:") and not TgClient.user:
        LOGGER.warning(
            "Skipping private incomplete task message fetch without USER_SESSION_STRING: %s",
            task["_id"],
        )
        return None, None
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
    pm_user_id, _ = _parse_pm_task_id(task["_id"])
    if not task.get("user_id") and pm_user_id:
        update["user_id"] = pm_user_id
    if not task.get("name") and task.get("command"):
        update["name"] = task["command"].split("\n", 1)[0]
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


def _get_task_type(command):
    if not command:
        return "[Unknown]"
    cmd = command.split()[0].lstrip("/").split("@")[0].lower()
    
    if _command_matches(cmd, BotCommands.MirrorCommand): return "[Mirror]"
    if _command_matches(cmd, BotCommands.QbMirrorCommand): return "[QbMirror]"
    if _command_matches(cmd, BotCommands.JdMirrorCommand): return "[JdMirror]"
    if _command_matches(cmd, BotCommands.NzbMirrorCommand): return "[NzbMirror]"
    if _command_matches(cmd, BotCommands.LeechCommand): return "[Leech]"
    if _command_matches(cmd, BotCommands.QbLeechCommand): return "[QbLeech]"
    if _command_matches(cmd, BotCommands.JdLeechCommand): return "[JdLeech]"
    if _command_matches(cmd, BotCommands.NzbLeechCommand): return "[NzbLeech]"
    if _command_matches(cmd, BotCommands.YtdlCommand): return "[YTDL]"
    if _command_matches(cmd, BotCommands.YtdlLeechCommand): return "[YTDL Leech]"
    if _command_matches(cmd, BotCommands.CloneCommand): return "[Clone]"
    if _command_matches(cmd, BotCommands.UpHosterCommand): return "[UpHoster]"
    return "[Task]"


async def _send_recovery_message_ui(message_or_target, user_id, tasks, now, is_edit=False):
    buttons = button_build.ButtonMaker()
    buttons.data_button("▶️ Resume All", f"resume_tasks_{user_id}")
    buttons.data_button("🗑️ Clear All", f"clear_tasks_{user_id}")
    buttons.data_button("⚙️ Manage Tasks", f"manage_tasks_{user_id}_1")

    msg = (
        "☀️ <b>Bot Restarted</b>\n\n"
        f"You had <code>{len(tasks)}</code> incomplete task(s):"
    )
    for index, task in enumerate(tasks[:20], start=1):
        msg += _task_line(index, task)
    if len(tasks) > 20:
        msg += f"\n...and {len(tasks) - 20} more."
    msg += (
        "\n\nWhat would you like to do?"
        f"\n\n<code>{now.strftime('%d/%m/%y %I:%M:%S %p')} {Config.TIMEZONE}</code>"
    )

    if is_edit:
        return await edit_message(message_or_target, msg, buttons.build_menu(2))
    else:
        return await send_message(message_or_target, msg, buttons.build_menu(2))


async def _send_recovery_message(user_id, tasks, now):
    return await _send_recovery_message_ui(user_id, user_id, tasks, now, is_edit=False)


async def _send_recovery_message_to_chat(cid, user_id, tasks, now):
    buttons = button_build.ButtonMaker()
    buttons.data_button("▶️ Resume All", f"resume_tasks_{user_id}")
    buttons.data_button("🗑️ Clear All", f"clear_tasks_{user_id}")

    msg = (
        f"☀️ <b>Bot Restarted</b>\n\n"
        f"⚠️ <a href='tg://user?id={user_id}'>User</a>, I couldn't PM you! "
        f"Please start the bot here: @{TgClient.bot.me.username} so I can DM you next time.\n\n"
        f"You had <code>{len(tasks)}</code> incomplete task(s):"
    )
    for index, task in enumerate(tasks[:20], start=1):
        msg += _task_line(index, task)
    if len(tasks) > 20:
        msg += f"\n...and {len(tasks) - 20} more."
    msg += (
        "\n\nWhat would you like to do?"
        f"\n\n<code>{now.strftime('%d/%m/%y %I:%M:%S %p')} {Config.TIMEZONE}</code>"
    )
    
    buttons.url_button("💬 Start Bot in PM", f"tg://resolve?domain={TgClient.bot.me.username}")

    return await send_message(cid, msg, buttons.build_menu(2))


async def notify_incomplete_tasks():
    if not ((Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME) and Config.DATABASE_URL):
        return

    tasks = await database.get_incomplete_task_docs(notified=False)
    if not tasks:
        return

    ttl_seconds = getattr(Config, "INCOMPLETE_TASK_TTL", 86400)
    by_user = {}
    for task in tasks:
        created_at = task.get("created_at")
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=dt_timezone.utc)
            if (datetime.now(dt_timezone.utc) - created_at).total_seconds() > ttl_seconds:
                await database.rm_complete_task(task["_id"])
                continue

        task = await _hydrate_incomplete_task(task)
        user_id = task.get("user_id")
        if not user_id:
            LOGGER.warning(f"Skipping task without user_id: {task['_id']}")
            continue
        by_user.setdefault(user_id, []).append(task)

    now = datetime.now(timezone(Config.TIMEZONE))
    for user_id, user_tasks in by_user.items():
        delivered = False
        try:
            # Always attempt PM delivery first
            result = await _send_recovery_message(user_id, user_tasks, now)
            delivered = result is not None and not isinstance(result, str)
        except Exception as e:
            LOGGER.warning(f"PM notify failed for {user_id}: {e}")
            # Fallback: try the original chat
            try:
                cid = user_tasks[0]["cid"]
                if cid != user_id and not any(t.get("is_pm") for t in user_tasks):  # don't retry same target
                    result = await _send_recovery_message_to_chat(cid, user_id, user_tasks, now)
                    delivered = result is not None and not isinstance(result, str)
            except Exception as e2:
                LOGGER.error(f"Group fallback notify failed for {user_id}: {e2}")
        if delivered:
            await database.mark_incomplete_tasks_notified(
                [task["_id"] for task in user_tasks]
            )
        else:
            LOGGER.warning("Incomplete task recovery notice was not delivered to %s", user_id)
        await sleep(1)


async def _resume_from_command(task):
    command = task.get("command", "")
    user_id = task.get("user_id", 0)
    reply_to_msg_id = task.get("reply_to_msg_id", 0)
    if not command or not user_id:
        return False

    try:
        handler = resolve_command(command)
    except Exception as error:
        LOGGER.error("Resume: command resolution failed for %r: %s", command, error)
        return False
    if handler is None:
        return False

    try:
        user = await TgClient.bot.get_users(user_id)
    except Exception as e:
        LOGGER.warning(f"Resume: cannot get user {user_id}: {e}")
        return False

    reply_msg = None
    if reply_to_msg_id:
        try:
            reply_msg = await TgClient.bot.get_messages(
                chat_id=task["cid"], message_ids=reply_to_msg_id
            )
            # If the original message was deleted (e.g. by DELETE_LINKS=True)
            if getattr(reply_msg, "empty", False):
                reply_msg = None
        except Exception as e:
            LOGGER.warning(f"Resume: cannot fetch reply msg {reply_to_msg_id}: {e}")

    # If there's no link in the command and the original file message is missing/deleted, it's unrecoverable
    if not reply_msg and len(command.split()) == 1:
        LOGGER.warning(f"Resume: Original message deleted and no link in command. Cannot resume task: {command}")
        return False

    try:
        msg = await TgClient.bot.send_message(
            chat_id=task["cid"],
            text=command,
            disable_notification=True,
        )
        msg.text = command
        msg.from_user = user
        if reply_msg:
            msg.reply_to_message = reply_msg
            
        await handler(TgClient.bot, msg)
        await delete_message(msg)
        return True
    except Exception as e:
        LOGGER.error(f"Resume: failed for '{command}' in {task['cid']}: {e}")
        return False


def _deduplicate_tasks(tasks):
    unique = []
    seen = set()
    for task in tasks:
        command = " ".join(str(task.get("command", "")).split())
        identity = (
            task.get("cid"),
            task.get("user_id"),
            task.get("reply_to_msg_id", 0),
            command or task.get("link") or task.get("_id"),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(task)
    return unique


async def auto_resume_incomplete_tasks():
    if not (Config.INC_TASK_RESUME and Config.DATABASE_URL):
        return

    discarded = await database.discard_legacy_incomplete_tasks()
    if discarded:
        LOGGER.warning(
            "Discarded %s stale incomplete task record(s) created before "
            "reliable completion tracking was enabled.",
            discarded,
        )

    tasks = await database.get_incomplete_task_docs(notified=None)
    if not tasks:
        return

    ttl_seconds = getattr(Config, "INCOMPLETE_TASK_TTL", 86400)
    valid_tasks = []
    for task in tasks:
        created_at = task.get("created_at")
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=dt_timezone.utc)
            if (datetime.now(dt_timezone.utc) - created_at).total_seconds() > ttl_seconds:
                await database.rm_complete_task(task["_id"])
                continue
        valid_tasks.append(task)
            
    if not valid_tasks:
        return

    unique_tasks = _deduplicate_tasks(valid_tasks)
    duplicates = len(valid_tasks) - len(unique_tasks)
    resumed = 0
    skipped = 0
    for task in unique_tasks:
        task = await _hydrate_incomplete_task(task)
        queued = False
        if await _resume_from_command(task):
            queued = True
        else:
            message, client = await _get_task_message(task)
            if message and getattr(message, "text", None) and await _requeue_task(client, message):
                queued = True
        if queued:
            resumed += 1
            await database.clear_incomplete_tasks_by_links([task["_id"]])
        else:
            skipped += 1
        await sleep(RECOVERY_TASK_DELAY)
    LOGGER.info(
        "Auto-resumed incomplete tasks: %s; skipped: %s; duplicates discarded: %s",
        resumed,
        skipped,
        duplicates,
    )


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
            "⚠️ No incomplete tasks found.\nThey may have already been handled.",
        )
        return
    unique_tasks = _deduplicate_tasks(tasks)
    duplicates = len(tasks) - len(unique_tasks)
    resumed = 0
    skipped = 0
    for task in unique_tasks:
        task = await _hydrate_incomplete_task(task)
        queued = False
        # Try command-based resume first (no message fetch required)
        if await _resume_from_command(task):
            queued = True
        else:
            # Fallback: original message
            message, client = await _get_task_message(task)
            if message and getattr(message, "text", None):
                if await _requeue_task(client, message):
                    queued = True
        if queued:
            resumed += 1
            await database.clear_incomplete_tasks_by_links([task["_id"]])
            await sleep(RECOVERY_TASK_DELAY)
            continue
        skipped += 1
        await sleep(RECOVERY_TASK_DELAY)
    await edit_message(
        query.message,
        f"✅ Incomplete Task Recovery\n"
        f"Re-queued: {resumed}\n"
        f"Skipped: {skipped}\n"
        f"Duplicates discarded: {duplicates}",
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

import hashlib
def _get_short_hash(text):
    return hashlib.md5(str(text).encode()).hexdigest()[:8]


@new_task
async def manage_incomplete_tasks(_, query):
    data = query.data.split("_")
    user_id = int(data[2])
    page = int(data[3])
    if await _reject_wrong_user(query, user_id):
        return
    
    tasks = await database.get_user_incomplete_tasks(user_id)
    if not tasks:
        await edit_message(
            query.message,
            "⚠️ No incomplete tasks found.\nThey may have already been handled.",
        )
        return

    unique_tasks = _deduplicate_tasks(tasks)
    total_tasks = len(unique_tasks)
    items_per_page = 5
    total_pages = (total_tasks + items_per_page - 1) // items_per_page
    page = min(max(page, 1), total_pages)
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_tasks = unique_tasks[start_idx:end_idx]

    buttons = button_build.ButtonMaker()
    msg = f"⚙️ <b>Manage Tasks</b> (Page {page}/{total_pages})\n\n"
    
    for i, task in enumerate(current_tasks, start=1):
        type_str = _get_task_type(task.get("command", ""))
        title = escape(_truncate(task.get("name") or task["_id"], limit=40))
        msg += f"<b>{start_idx + i}.</b> {type_str} <a href='{task['_id']}'>{title}</a>\n"
        
        short_id = _get_short_hash(task["_id"])
        buttons.data_button(f"▶️ Resume {start_idx + i}", f"rnt_{user_id}_{short_id}_{page}")
        buttons.data_button(f"🗑️ Discard {start_idx + i}", f"dlt_{user_id}_{short_id}_{page}")
    
    if total_pages > 1:
        if page > 1:
            buttons.data_button("◀️ Prev", f"manage_tasks_{user_id}_{page - 1}")
        if page < total_pages:
            buttons.data_button("Next ➡️", f"manage_tasks_{user_id}_{page + 1}")
            
    buttons.data_button("🔙 Back", f"back_manage_{user_id}")
    await edit_message(query.message, msg, buttons.build_menu(2))


@new_task
async def single_resume_task(_, query):
    data = query.data.split("_")
    user_id = int(data[1])
    short_id = data[2]
    page = int(data[3])
    if await _reject_wrong_user(query, user_id):
        return
    
    tasks = await database.get_user_incomplete_tasks(user_id)
    unique_tasks = _deduplicate_tasks(tasks)
    
    target_task = next((t for t in unique_tasks if _get_short_hash(t["_id"]) == short_id), None)
    if not target_task:
        await query.answer("Task not found or already processed.", show_alert=True)
        return
    link = target_task["_id"]
    
    await query.answer()
    target_task = await _hydrate_incomplete_task(target_task)
    
    resumed = False
    if await _resume_from_command(target_task):
        resumed = True
    else:
        message, client = await _get_task_message(target_task)
        if message and getattr(message, "text", None):
            if await _requeue_task(client, message):
                resumed = True

    if resumed:
        await database.clear_incomplete_tasks_by_links([link])
                
    query.data = f"manage_tasks_{user_id}_{page}"
    await manage_incomplete_tasks(_, query)


@new_task
async def single_delete_task(_, query):
    data = query.data.split("_")
    user_id = int(data[1])
    short_id = data[2]
    page = int(data[3])
    if await _reject_wrong_user(query, user_id):
        return
        
    tasks = await database.get_user_incomplete_tasks(user_id)
    unique_tasks = _deduplicate_tasks(tasks)
    
    target_task = next((t for t in unique_tasks if _get_short_hash(t["_id"]) == short_id), None)
    if not target_task:
        await query.answer("Task not found or already processed.", show_alert=True)
        return
    link = target_task["_id"]
    
    await query.answer("Task discarded.", show_alert=True)
    await database.clear_incomplete_tasks_by_links([link])
    
    query.data = f"manage_tasks_{user_id}_{page}"
    await manage_incomplete_tasks(_, query)


@new_task
async def back_manage_tasks(_, query):
    user_id = _callback_user_id(query.data)
    if await _reject_wrong_user(query, user_id):
        return
    await query.answer()
    
    tasks = await database.get_user_incomplete_tasks(user_id)
    unique_tasks = _deduplicate_tasks(tasks)
    if not unique_tasks:
        await edit_message(
            query.message,
            "⚠️ No incomplete tasks found.\nThey may have already been handled.",
        )
        return
        
    now = datetime.now(timezone(Config.TIMEZONE))
    await _send_recovery_message_ui(query.message, user_id, unique_tasks, now, is_edit=True)


async def restart_notification():
    if await aiopath.isfile(".restartmsg"):
        try:
            with open(".restartmsg") as f:
                chat_id, msg_id = map(int, f)
        except Exception:
            chat_id, msg_id = 0, 0
    else:
        chat_id, msg_id = 0, 0

    now = datetime.now(timezone(Config.TIMEZONE))

    if Config.DATABASE_URL and (Config.INCOMPLETE_TASK_NOTIFIER or Config.INC_TASK_RESUME):
        if Config.INC_TASK_RESUME:
            await auto_resume_incomplete_tasks()
        if Config.INCOMPLETE_TASK_NOTIFIER:
            await notify_incomplete_tasks()

    if await aiopath.isfile(".restartmsg"):
        try:
            await TgClient.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"""<b>❖ RESTARTED SUCCESSFULLY!</b>
<code>┌─ {'Date':<9}: {now.strftime("%d/%m/%y")}
├─ {'Time':<9}: {now.strftime("%I:%M:%S %p")}
├─ {'TimeZone':<9}: {Config.TIMEZONE}
└─ {'Version':<9}: {get_version()}
</code>""",
            )
        except Exception as e:
            LOGGER.error(e)
        await remove(".restartmsg")


async def _notify_tasks(notifier_dict, restart_chat_id, now):
    for cid, data in notifier_dict.items():
        is_restart_chat = cid == restart_chat_id
        header = _restart_header(now, is_restart_chat)
        msg = header + "\n\n⌬ <b><i>Incomplete Tasks!</i></b>"
        for tag, tasks in data.items():
            entry = f"\n➲ <b>User:</b> {tag}\n┖ <b>Tasks:</b>"
            for index, task in enumerate(tasks, start=1):
                link = task.get("link", "")
                entry += f" {index}. <a href='{link}'>L</a> |"
            if len((msg + entry).encode()) > 4000:
                await _send_msg(cid, msg)
                msg = header
            msg += entry
        if msg:
            await _send_msg(cid, msg)


async def _resume_tasks(notifier_dict):
    for cid, data in notifier_dict.items():
        for tag, tasks in data.items():
            for task in tasks:
                command = task.get("command", "")
                user_id = task.get("user_id", 0)
                reply_to_msg_id = task.get("reply_to_msg_id", 0)
                if not command or not user_id:
                    continue
                try:
                    user = await TgClient.bot.get_users(user_id)
                except Exception as e:
                    LOGGER.warning(f"Resume: cannot get user {user_id}: {e}")
                    continue
                handler = resolve_command(command)
                if handler is None:
                    continue
                try:
                    msg = await TgClient.bot.send_message(
                        chat_id=cid,
                        text=command,
                        disable_notification=True,
                    )
                    msg.text = command
                    msg.from_user = user
                    if reply_to_msg_id:
                        try:
                            reply_msg = await TgClient.bot.get_messages(
                                chat_id=cid, message_ids=reply_to_msg_id
                            )
                            if reply_msg:
                                msg.reply_to_message = reply_msg
                        except Exception as e:
                            LOGGER.warning(
                                f"Resume: cannot fetch reply msg {reply_to_msg_id}: {e}"
                            )
                    await handler(TgClient.bot, msg)
                    await sleep(1)
                except Exception as e:
                    LOGGER.error(f"Resume: failed for '{command}' in {cid}: {e}")


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

        if qb := intervals["qb"]:
            qb.cancel()
        if jd := intervals["jd"]:
            jd.cancel()
        if nzb := intervals["nzb"]:
            nzb.cancel()
        if st := intervals["status"]:
            for intvl in list(st.values()):
                intvl.cancel()

        if scheduler.running:
            scheduler.shutdown(wait=False)

        await mega_cleanup()

        sabnzbd_task = None
        jd_task = None
        if not Config.DISABLE_NZB and sabnzbd_client.LOGGED_IN:
            sabnzbd_task = gather(
                sabnzbd_client.pause_all(),
                sabnzbd_client.delete_job("all", True),
                sabnzbd_client.purge_all(True),
                sabnzbd_client.delete_history("all", delete_files=True),
            )
        if not Config.DISABLE_JD and jdownloader.is_connected:
            jd_task = gather(
                jdownloader.device.downloadcontroller.stop_downloads(),
                jdownloader.device.linkgrabber.clear_list(),
                jdownloader.device.downloads.cleanup(
                    "DELETE_ALL",
                    "REMOVE_LINKS_AND_DELETE_FILES",
                    "ALL",
                ),
            )

        try:
            await TorrentManager.remove_all()
        except Exception:
            pass
        await TorrentManager.close_all()

        if sabnzbd_task is not None:
            try:
                await sabnzbd_task
            except Exception:
                pass
            try:
                await sabnzbd_client.close()
            except Exception:
                pass
        if jd_task is not None:
            try:
                await jd_task
            except Exception:
                pass
            try:
                await jdownloader.close()
            except Exception:
                pass

        await TgClient.stop()

        THREAD_POOL.shutdown(wait=False)

        proc_cleanup = await create_subprocess_exec(
            "pkill",
            "-9",
            "-f",
            f"gunicorn|cloudflared|{BinConfig.ARIA2_NAME}|{BinConfig.QBIT_NAME}|{BinConfig.FFMPEG_NAME}|{BinConfig.RCLONE_NAME}|java|{BinConfig.SABNZBD_NAME}|7z|split",
        )
        await proc_cleanup.wait()

        proc_update = await create_subprocess_exec("python3", "update.py")
        await proc_update.wait()

        try:
            async with aiopen(".restartmsg", "w") as f:
                await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")
        except Exception:
            pass

        get_event_loop().create_task(_background_cleanup())

        osexecl(executable, executable, "-m", "bot")
    else:
        await delete_message(message, reply_to)


async def _background_cleanup():
    try:
        proc = await create_subprocess_exec("rm", "-rf", "/usr/src/app/downloads/")
        await proc.wait()
    except Exception:
        pass

