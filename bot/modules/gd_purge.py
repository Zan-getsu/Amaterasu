from asyncio import Event, TimeoutError, sleep, wait_for
from html import escape
from time import time
from uuid import uuid4

from pyrogram.enums import ButtonStyle
from pyrogram.filters import create
from pyrogram.handlers import MessageHandler

from .. import LOGGER, bot_loop
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task, sync_to_async
from ..helper.ext_utils.status_utils import get_readable_file_size, get_readable_time
from ..helper.mirror_leech_utils.gdrive_utils.purge import GoogleDrivePurge
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.filters import CustomFilters
from ..helper.telegram_helper.message_utils import delete_message, edit_message, send_message

CONTROL_TIMEOUT = 300
INPUT_TIMEOUT = 60
BATCH_SIZE = 50
BATCH_DELAY = 1
CRITICAL_FILE_LIMIT = 1000
CRITICAL_SIZE_LIMIT = 100 * 1024**3

PURGE_SESSIONS = {}
PURGE_DRIVE_LOCKS = {}


def _make_token():
    return uuid4().hex[:10]


def _configured_root_id():
    if not Config.GDRIVE_ID:
        return ""
    try:
        return GoogleDrivePurge().resolve_target_id(Config.GDRIVE_ID)
    except (KeyError, IndexError):
        return Config.GDRIVE_ID


def _mode_label(mode, value=None):
    labels = {
        "all": "Delete All",
        "files": "Delete Files Only",
        "empty_folders": "Delete Empty Folders",
        "folders": "Delete Only Folders",
    }
    if mode == "age":
        try:
            return f"Delete Older Than {float(value):g} Day(s)"
        except (TypeError, ValueError):
            return "Delete By Age"
    if mode == "range":
        try:
            return f"Delete First {int(value)} File(s)"
        except (TypeError, ValueError):
            return "Delete By Range"
    return labels.get(mode, mode)


def _session_expired(session):
    return (
        not session.get("running")
        and not session.get("transitioning")
        and time() > session["expires_at"]
    )


def _touch_session(session):
    session["expires_at"] = time() + CONTROL_TIMEOUT


def _release_session(token):
    session = PURGE_SESSIONS.pop(token, None)
    if session:
        locked_token = PURGE_DRIVE_LOCKS.get(session["target_id"])
        if locked_token == token:
            PURGE_DRIVE_LOCKS.pop(session["target_id"], None)


async def _expire_session(token):
    while session := PURGE_SESSIONS.get(token):
        if session.get("running"):
            return
        remaining = session["expires_at"] - time()
        if remaining > 0:
            await sleep(remaining)
            continue
        message = session["message"]
        session["expired"] = True
        _release_session(token)
        await edit_message(
            message,
            "Drive purge panel expired. Start a new purge command.",
        )
        return


def _main_buttons(token):
    buttons = ButtonMaker()
    buttons.data_button("🗑 Delete All", f"gdp {token} mode all", style=ButtonStyle.DANGER)
    buttons.data_button("📅 Delete By Age", f"gdp {token} age_menu")
    buttons.data_button("🔢 Delete By Range", f"gdp {token} range_menu")
    buttons.data_button("📄 Delete Files Only", f"gdp {token} mode files")
    buttons.data_button("📁 Delete Empty Folders", f"gdp {token} mode empty_folders")
    buttons.data_button("📂 Delete Only Folders", f"gdp {token} mode folders")
    buttons.data_button("🔍 Dry Run Preview", f"gdp {token} dry")
    buttons.data_button("❌ Cancel", f"gdp {token} cancel", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


def _age_buttons(token):
    buttons = ButtonMaker()
    for days in (1, 7, 30, 90, 180, 365):
        buttons.data_button(f"Older Than {days} Day(s)", f"gdp {token} age {days}")
    buttons.data_button("Custom Duration", f"gdp {token} custom_age")
    buttons.data_button("↩ Back", f"gdp {token} menu", position="footer")
    buttons.data_button(
        "❌ Cancel",
        f"gdp {token} cancel",
        position="footer",
        style=ButtonStyle.DANGER,
    )
    return buttons.build_menu(2, f_cols=2)


def _range_buttons(token):
    buttons = ButtonMaker()
    for amount in (100, 500, 1000, 5000):
        buttons.data_button(f"First {amount} Files", f"gdp {token} range {amount}")
    buttons.data_button("Custom Amount", f"gdp {token} custom_range")
    buttons.data_button("↩ Back", f"gdp {token} menu", position="footer")
    buttons.data_button(
        "❌ Cancel",
        f"gdp {token} cancel",
        position="footer",
        style=ButtonStyle.DANGER,
    )
    return buttons.build_menu(2, f_cols=2)


def _confirm_buttons(token):
    buttons = ButtonMaker()
    buttons.data_button("✅ Confirm", f"gdp {token} confirm", style=ButtonStyle.DANGER)
    buttons.data_button("❌ Cancel", f"gdp {token} cancel", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


def _final_confirm_buttons(token):
    buttons = ButtonMaker()
    buttons.data_button(
        "🚨 Confirm Permanent Delete",
        f"gdp {token} final_confirm",
        style=ButtonStyle.DANGER,
    )
    buttons.data_button(
        "❌ Cancel",
        f"gdp {token} cancel",
        style=ButtonStyle.DANGER,
    )
    return buttons.build_menu(1)


def _stop_buttons(token):
    buttons = ButtonMaker()
    buttons.data_button("⏹ Stop Purge", f"gdp {token} stop", style=ButtonStyle.DANGER)
    return buttons.build_menu(1)


def _target_text(session, default_used=False):
    summary = session["summary"]
    text = "<b>🗂 Target Drive Information</b>\n\n"
    if default_used:
        text += (
            "⚠ <b>No Drive ID was provided.</b>\n\n"
            "The configured Root Drive will be used.\n\n"
        )
    text += f"<b>Name:</b> <code>{escape(summary['target_name'])}</code>\n"
    text += f"<b>Drive ID:</b> <code>{escape(summary['target_id'])}</code>\n\n"
    text += f"<b>Files:</b> <code>{summary['files']:,}</code>\n"
    text += f"<b>Folders:</b> <code>{summary['folders']:,}</code>\n"
    text += f"<b>Total Size:</b> <code>{get_readable_file_size(summary['size'])}</code>\n\n"
    if summary["undeletable"]:
        text += (
            f"⚠ <b>Items without delete permission:</b> "
            f"<code>{summary['undeletable']:,}</code>\n\n"
        )
    else:
        text += "✅ <b>Delete access verified.</b>\n\n"
    text += "<b>Ready for cleanup.</b>\n\n"
    text += "<b>🧹 Drive Purge Manager</b>\n\nSelect an action:"
    return text


def _preview_text(session, plan, dry=False):
    title = "🔍 <b>Preview Results</b>" if dry else "⚠ <b>Warning</b>"
    text = f"{title}\n\n"
    if not dry:
        text += "This operation cannot be undone.\n\n"
    text += f"<b>Target:</b>\n<code>{escape(session['summary']['target_name'])}</code>\n\n"
    text += f"<b>Mode:</b> <code>{escape(_mode_label(plan['mode'], plan['value']))}</code>\n\n"
    text += f"<b>Files To Delete:</b> <code>{len(plan['files']):,}</code>\n"
    text += f"<b>Folders To Delete:</b> <code>{len(plan['folders']):,}</code>\n"
    if plan["move_files"]:
        text += f"<b>Files To Move To Target Root:</b> <code>{len(plan['move_files']):,}</code>\n"
    text += f"\n<b>Total Size:</b>\n<code>{get_readable_file_size(plan['size'])}</code>"
    if not dry:
        text += "\n\n<b>Are you sure?</b>"
    return text


def _critical_plan(session, plan):
    return (
        plan["mode"] == "all"
        or session["is_root"]
        or len(plan["files"]) > CRITICAL_FILE_LIMIT
        or plan["size"] > CRITICAL_SIZE_LIMIT
    )


def _parse_duration_days(value):
    value = value.strip().lower()
    if not value:
        return None
    unit = value[-1]
    number = value[:-1] if unit in "dhms" else value
    try:
        amount = float(number)
    except ValueError:
        return None
    if amount <= 0:
        return None
    if unit == "h":
        return amount / 24
    if unit == "m":
        return amount / 1440
    if unit == "s":
        return amount / 86400
    return amount


async def _wait_for_text(client, query, validator, timeout_message, session=None):
    done = Event()
    value_box = {}

    async def event_filter(_, __, event):
        user = event.from_user or event.sender_chat
        return bool(
            user.id == query.from_user.id
            and event.chat.id == query.message.chat.id
            and event.text
        )

    async def listener(_, event):
        if session:
            _touch_session(session)
        value = validator(event.text.strip())
        if value is None:
            await send_message(event, timeout_message)
            return
        value_box["value"] = value
        value_box["message"] = event
        done.set()

    handler = client.add_handler(
        MessageHandler(listener, filters=create(event_filter)), group=-1
    )
    try:
        await wait_for(done.wait(), timeout=INPUT_TIMEOUT)
        await delete_message(value_box.get("message"))
        return value_box["value"]
    except TimeoutError:
        return None
    finally:
        client.remove_handler(*handler)


async def _show_main(message, session):
    await edit_message(
        message,
        _target_text(session, session["default_used"]),
        _main_buttons(session["token"]),
    )


async def _show_plan(message, session, mode, value=None, dry=False):
    plan = session["helper"].build_plan(mode, value)
    session["plan"] = plan
    if dry:
        session["confirm_stage"] = "preview"
        GoogleDrivePurge.log_operation(
            session["user"],
            session["summary"],
            f"dry-run:{_mode_label(plan['mode'], plan['value'])}",
            0,
            0,
            0,
            0,
        )
        buttons = ButtonMaker()
        buttons.data_button("↩ Back", f"gdp {session['token']} menu")
        buttons.data_button("❌ Cancel", f"gdp {session['token']} cancel", style=ButtonStyle.DANGER)
        await edit_message(message, _preview_text(session, plan, True), buttons.build_menu(2))
        return
    if plan["blocked_delete"] or plan["blocked_move"]:
        session["confirm_stage"] = "blocked"
        buttons = ButtonMaker()
        buttons.data_button("↩ Back", f"gdp {session['token']} menu")
        buttons.data_button("❌ Cancel", f"gdp {session['token']} cancel", style=ButtonStyle.DANGER)
        text = (
            "⛔ <b>Purge Plan Blocked</b>\n\n"
            "Google Drive reported insufficient permissions for items selected by this mode.\n\n"
            f"<b>Cannot Delete:</b> <code>{len(plan['blocked_delete']):,}</code>\n"
            f"<b>Cannot Move:</b> <code>{len(plan['blocked_move']):,}</code>\n\n"
            "No deletion has been performed."
        )
        await edit_message(message, text, buttons.build_menu(2))
        return
    if plan["total"] == 0 and not plan["move_files"]:
        session["confirm_stage"] = "empty"
        buttons = ButtonMaker()
        buttons.data_button("↩ Back", f"gdp {session['token']} menu")
        buttons.data_button("❌ Cancel", f"gdp {session['token']} cancel", style=ButtonStyle.DANGER)
        await edit_message(
            message,
            f"{_preview_text(session, plan, True)}\n\nNo matching items were found.",
            buttons.build_menu(2),
        )
        return
    session["confirm_stage"] = "primary"
    await edit_message(message, _preview_text(session, plan), _confirm_buttons(session["token"]))


async def _show_final_confirmation(message, session):
    plan = session["plan"]
    session["confirm_stage"] = "final"
    text = (
        "🚨 <b>Final Confirmation</b>\n\n"
        "You are about to permanently delete:\n\n"
        f"<b>Files:</b> <code>{len(plan['files']):,}</code>\n"
        f"<b>Folders:</b> <code>{len(plan['folders']):,}</code>\n"
        f"<b>Size:</b> <code>{get_readable_file_size(plan['size'])}</code>\n\n"
        "This action cannot be undone.\n\n"
        "Press the confirmation button below to continue."
    )
    await edit_message(
        message,
        text,
        _final_confirm_buttons(session["token"]),
    )


async def _run_purge(message, session):
    token = session["token"]
    helper = session["helper"]
    plan = session["plan"]
    session["running"] = True
    session["stop"] = False
    started = time()
    deleted_files = 0
    deleted_folders = 0
    moved_files = 0
    recovered = 0
    total_work = len(plan["move_files"]) + len(plan["files"]) + len(plan["folders"])
    processed = 0

    async def update_progress(force=False):
        if not force and time() - session.get("last_update", 0) < 5:
            return
        session["last_update"] = time()
        text = (
            "🗑 <b>Purge Running</b>\n\n"
            f"<b>Progress:</b>\n<code>{processed:,} / {total_work:,}</code>\n\n"
            f"<b>Deleted:</b>\n<code>{deleted_files:,} files</code>\n"
            f"<code>{deleted_folders:,} folders</code>\n"
        )
        if moved_files:
            text += f"<code>{moved_files:,} files moved to target root</code>\n"
        text += f"\n<b>Recovered:</b>\n<code>{get_readable_file_size(recovered)}</code>"
        await edit_message(message, text, _stop_buttons(token))

    await update_progress(True)
    try:
        for items, action in (
            (plan["move_files"], "move"),
            (plan["files"], "file"),
            (plan["folders"], "folder"),
        ):
            for start in range(0, len(items), BATCH_SIZE):
                if session.get("stop"):
                    break
                batch = items[start : start + BATCH_SIZE]
                if action == "move":
                    for item in batch:
                        await sync_to_async(helper.move_file_to_target_root, item)
                        moved_files += 1
                        processed += 1
                        await update_progress()
                else:
                    completed_ids, errors = await sync_to_async(
                        helper.delete_batch, batch
                    )
                    for item in batch:
                        if item["id"] not in completed_ids:
                            continue
                        if action == "file":
                            deleted_files += 1
                            recovered += item.get("size_int", 0)
                        else:
                            deleted_folders += 1
                    processed += len(completed_ids)
                    await update_progress()
                    if errors:
                        first_error = next(iter(errors.values()))
                        raise RuntimeError(
                            f"{len(errors)} item(s) failed in the current batch: "
                            f"{first_error}"
                        )
                await sleep(BATCH_DELAY)
            if session.get("stop"):
                break
    except Exception as err:
        elapsed = time() - started
        LOGGER.error("Drive purge failed", exc_info=True)
        GoogleDrivePurge.log_operation(
            session["user"],
            session["summary"],
            f"failed:{_mode_label(plan['mode'], plan['value'])}",
            deleted_files,
            deleted_folders,
            recovered,
            elapsed,
        )
        text = (
            "❌ <b>Purge Failed</b>\n\n"
            f"<b>Reason:</b>\n<code>{escape(str(err))}</code>\n\n"
            f"<b>Deleted Files:</b>\n<code>{deleted_files:,}</code>\n\n"
            f"<b>Deleted Folders:</b>\n<code>{deleted_folders:,}</code>\n\n"
            "Operation Stopped Safely."
        )
        await edit_message(message, text)
        _release_session(token)
        return

    elapsed = time() - started
    stopped = session.get("stop")
    GoogleDrivePurge.log_operation(
        session["user"],
        session["summary"],
        ("stopped:" if stopped else "") + _mode_label(plan["mode"], plan["value"]),
        deleted_files,
        deleted_folders,
        recovered,
        elapsed,
    )
    title = "⏹ <b>Purge Stopped</b>" if stopped else "✅ <b>Purge Completed</b>"
    text = (
        f"{title}\n\n"
        f"<b>Target Drive:</b>\n<code>{escape(session['summary']['target_name'])}</code>\n\n"
        f"<b>Deleted Files:</b>\n<code>{deleted_files:,}</code>\n\n"
        f"<b>Deleted Folders:</b>\n<code>{deleted_folders:,}</code>\n\n"
    )
    if moved_files:
        text += f"<b>Files Moved To Target Root:</b>\n<code>{moved_files:,}</code>\n\n"
    text += (
        f"<b>Recovered Storage:</b>\n<code>{get_readable_file_size(recovered)}</code>\n\n"
        f"<b>Execution Time:</b>\n<code>{get_readable_time(elapsed) or '0s'}</code>"
    )
    await edit_message(message, text)
    _release_session(token)


@new_task
async def purge_drive(_, message):
    user = message.from_user or message.sender_chat
    if not await CustomFilters.sudo("", message):
        await send_message(
            message,
            "Unauthorized access. Drive purge is restricted to SUDO users only.",
        )
        return

    args = message.text.split(maxsplit=1)
    default_used = len(args) == 1
    target = Config.GDRIVE_ID if default_used else args[1].strip()
    if not target:
        await send_message(
            message,
            "No Drive ID was provided and <code>GDRIVE_ID</code> is not configured.",
        )
        return

    scan_message = await send_message(message, "Scanning target Drive. Please wait...")
    helper = GoogleDrivePurge()
    try:
        await sync_to_async(helper.prepare, target, user.id)
        summary = await sync_to_async(helper.scan)
    except Exception as err:
        LOGGER.error("Drive purge scan failed", exc_info=True)
        await edit_message(
            scan_message,
            f"Drive purge scan failed:\n<code>{escape(str(err))}</code>",
        )
        return

    existing_token = PURGE_DRIVE_LOCKS.get(helper.target_id)
    if existing_token:
        existing_session = PURGE_SESSIONS.get(existing_token)
        if not existing_session or _session_expired(existing_session):
            _release_session(existing_token)
            existing_token = None
    if existing_token:
        await edit_message(
            scan_message,
            "Another purge control panel or purge operation is already active for this Drive.",
        )
        return

    token = _make_token()
    session = {
        "token": token,
        "user": user,
        "user_id": user.id,
        "helper": helper,
        "summary": summary,
        "target_id": helper.target_id,
        "default_used": default_used,
        "is_root": (
            default_used
            or helper.target_id == "root"
            or helper.target_id == _configured_root_id()
        ),
        "created_at": time(),
        "expires_at": time() + CONTROL_TIMEOUT,
        "running": False,
        "stop": False,
        "message": scan_message,
    }
    PURGE_SESSIONS[token] = session
    PURGE_DRIVE_LOCKS[helper.target_id] = token
    LOGGER.info(
        "Drive purge scan | user_id=%s | username=%s | target_drive_id=%s | "
        "target_drive_name=%s | files=%s | folders=%s | size=%s",
        user.id,
        getattr(user, "username", ""),
        helper.target_id,
        helper.target_name,
        summary["files"],
        summary["folders"],
        summary["size"],
    )
    await edit_message(scan_message, _target_text(session, default_used), _main_buttons(token))
    bot_loop.create_task(_expire_session(token))


@new_task
async def purge_callback(client, query):
    data = query.data.split()
    if len(data) < 3:
        await query.answer()
        return
    token = data[1]
    action = data[2]
    session = PURGE_SESSIONS.get(token)
    if not session:
        await query.answer("This purge panel has expired.", show_alert=True)
        return
    if query.from_user.id != session["user_id"]:
        await query.answer("This purge panel belongs to another user.", show_alert=True)
        return
    if not await CustomFilters.sudo("", query):
        await query.answer("Unauthorized.", show_alert=True)
        return
    if _session_expired(session):
        await edit_message(query.message, "Drive purge panel expired. Start a new purge command.")
        _release_session(token)
        await query.answer()
        return
    _touch_session(session)

    if action == "stop":
        session["stop"] = True
        await query.answer("Stop requested. Current batch will finish safely.", show_alert=True)
        return
    if session.get("running"):
        await query.answer("Purge is already running. Use Stop Purge.", show_alert=True)
        return
    if session.get("transitioning"):
        await query.answer("The purge panel is updating. Please try again.", show_alert=True)
        return
    if action == "cancel":
        session["cancelled"] = True
        _release_session(token)
        await query.answer()
        await edit_message(query.message, "Drive purge cancelled.")
        GoogleDrivePurge.log_operation(
            session["user"],
            session["summary"],
            "cancelled",
            0,
            0,
            0,
            time() - session["created_at"],
        )
        return

    if action == "confirm":
        plan = session.get("plan")
        if (
            session.get("cancelled")
            or not plan
            or session.get("confirm_stage") != "primary"
        ):
            await query.answer("This confirmation is no longer active.", show_alert=True)
            return
        if _critical_plan(session, plan):
            session["confirm_stage"] = "final"
            session["transitioning"] = True
            try:
                await query.answer()
                await _show_final_confirmation(query.message, session)
            finally:
                session["transitioning"] = False
            return
        session["running"] = True
        session["confirm_stage"] = "running"
        await query.answer()
        await _run_purge(query.message, session)
        return

    if action == "final_confirm":
        plan = session.get("plan")
        if (
            session.get("cancelled")
            or not plan
            or session.get("confirm_stage") != "final"
            or not _critical_plan(session, plan)
        ):
            await query.answer("This confirmation is no longer active.", show_alert=True)
            return
        session["running"] = True
        session["confirm_stage"] = "running"
        await query.answer()
        await _run_purge(query.message, session)
        return

    await query.answer()
    if action == "menu":
        await _show_main(query.message, session)
    elif action == "age_menu":
        await edit_message(
            query.message,
            "📅 <b>Delete By Age</b>\n\nSelect an age:",
            _age_buttons(token),
        )
    elif action == "range_menu":
        await edit_message(
            query.message,
            "🔢 <b>Delete By Range</b>\n\nSelect an amount:",
            _range_buttons(token),
        )
    elif action == "age" and len(data) > 3:
        await _show_plan(query.message, session, "age", float(data[3]))
    elif action == "range" and len(data) > 3:
        await _show_plan(query.message, session, "range", int(data[3]))
    elif action == "custom_age":
        await edit_message(
            query.message,
            "Send custom age within 60 seconds.\n\n"
            "Examples: <code>30</code>, <code>90d</code>, <code>12h</code>",
        )
        days = await _wait_for_text(
            client,
            query,
            _parse_duration_days,
            "Invalid duration. Send a number of days, or use d/h/m/s suffix.",
            session,
        )
        if days is None:
            await edit_message(query.message, "Custom age input timed out. Operation cancelled.")
            _release_session(token)
            return
        await _show_plan(query.message, session, "age", days)
    elif action == "custom_range":
        await edit_message(
            query.message,
            "Send custom file amount within 60 seconds.\n\n"
            "Examples: <code>100</code>, <code>5000</code>, <code>10000</code>",
        )

        def parse_amount(text):
            try:
                amount = int(text)
            except ValueError:
                return None
            return amount if amount > 0 else None

        amount = await _wait_for_text(
            client,
            query,
            parse_amount,
            "Invalid amount. Send a positive whole number.",
            session,
        )
        if amount is None:
            await edit_message(
                query.message,
                "Custom amount input timed out. Operation cancelled.",
            )
            _release_session(token)
            return
        await _show_plan(query.message, session, "range", amount)
    elif action == "dry":
        await _show_plan(query.message, session, "all", dry=True)
    elif action == "mode" and len(data) > 3:
        await _show_plan(query.message, session, data[3])

