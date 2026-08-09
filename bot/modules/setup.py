"""Owner-only setup review wizard."""

from html import escape

from .. import DOWNLOAD_DIR
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)
from ..version import get_version

_SETUP_STEPS = [
    "download_dir",
    "gdrive",
    "rclone",
    "owner_id",
    "summary",
]

_STEP_LABELS = {
    "download_dir": "Download Directory",
    "gdrive": "Google Drive",
    "rclone": "Rclone",
    "owner_id": "Owner Confirmation",
    "summary": "Summary & Apply",
}


def _primary_command(command):
    return command[0] if isinstance(command, list) else command


def _status_label(configured):
    return "Ready" if configured else "Needs setup"


def _setup_header(step):
    step_idx = _SETUP_STEPS.index(step) + 1
    title = _STEP_LABELS[step].upper()
    return (
        f"<b>✦ SETUP CONTROL</b>\n"
        f"<i>Step {step_idx}/{len(_SETUP_STEPS)} - {_STEP_LABELS[step]}</i>\n\n"
        f"╭─ <b>Step</b> : <code>{step_idx}/{len(_SETUP_STEPS)}</code>\n"
        f"├─ <b>Panel</b> : <code>{escape(title)}</code>"
    )


def _setup_message(step, state=None):
    """Build the setup message for the current step."""
    del state
    if step == "download_dir":
        current = escape(str(getattr(Config, "DOWNLOAD_DIR", DOWNLOAD_DIR)))
        default_dir = escape(str(DOWNLOAD_DIR))
        return (
            f"{_setup_header(step)}\n"
            f"├─ <b>Current</b> : <code>{current}</code>\n"
            f"╰─ <b>Default</b> : <code>{default_dir}</code>\n\n"
            "<i>Downloads are staged here before upload or streaming. Keep the "
            "path writable inside the container. Change DOWNLOAD_DIR in config "
            "or environment, then restart.</i>"
        )
    elif step == "gdrive":
        configured = bool(
            getattr(Config, "GDRIVE_ID", "")
            or getattr(Config, "USE_SERVICE_ACCOUNTS", False)
        )
        target = escape(str(getattr(Config, "GDRIVE_ID", "") or "Not set"))
        mode = (
            "Service Accounts"
            if getattr(Config, "USE_SERVICE_ACCOUNTS", False)
            else "Token"
        )
        token_cmd = _primary_command(BotCommands.TokenGenCommand)
        return (
            f"{_setup_header(step)}\n"
            f"├─ <b>Status</b> : <code>{_status_label(configured)}</code>\n"
            f"├─ <b>Mode</b> : <code>{mode}</code>\n"
            f"╰─ <b>Target</b> : <code>{target}</code>\n\n"
            f"<i>Use /{token_cmd} to generate a private Drive token, then set "
            "GDRIVE_ID to the destination folder. Skip this if you only leech "
            "to Telegram or use Rclone.</i>"
        )
    elif step == "rclone":
        configured = bool(getattr(Config, "RCLONE_PATH", ""))
        target = escape(str(getattr(Config, "RCLONE_PATH", "") or "Not set"))
        return (
            f"{_setup_header(step)}\n"
            f"├─ <b>Status</b> : <code>{_status_label(configured)}</code>\n"
            f"╰─ <b>Target</b> : <code>{target}</code>\n\n"
            "<i>Configure a remote with rclone config, then set RCLONE_PATH "
            "to remote:path. Skip this if Rclone is not part of your upload "
            "flow.</i>"
        )
    elif step == "owner_id":
        oid = escape(str(getattr(Config, "OWNER_ID", 0)))
        return (
            f"{_setup_header(step)}\n"
            f"├─ <b>Status</b> : <code>Owner verified</code>\n"
            f"╰─ <b>OWNER_ID</b> : <code>{oid}</code>\n\n"
            "<i>This wizard is owner-only. If the ID is wrong, update "
            "OWNER_ID in config or environment, then restart.</i>"
        )
    elif step == "summary":
        gdrive_configured = bool(
            getattr(Config, "GDRIVE_ID", "")
            or getattr(Config, "USE_SERVICE_ACCOUNTS", False)
        )
        rclone_configured = bool(getattr(Config, "RCLONE_PATH", ""))
        user_settings_cmd = _primary_command(BotCommands.UserSetCommand)
        return (
            f"{_setup_header(step)}\n"
            f"├─ <b>Download Dir</b> : <code>{escape(str(getattr(Config, 'DOWNLOAD_DIR', DOWNLOAD_DIR)))}</code>\n"
            f"├─ <b>Google Drive</b> : <code>{_status_label(gdrive_configured)}</code>\n"
            f"├─ <b>Rclone</b> : <code>{_status_label(rclone_configured)}</code>\n"
            f"├─ <b>Owner ID</b> : <code>{escape(str(getattr(Config, 'OWNER_ID', 0)))}</code>\n"
            f"╰─ <b>Version</b> : <code>{escape(str(get_version()))}</code>\n\n"
            "<i>Review complete. Use /help for commands or "
            f"/{user_settings_cmd} for per-user storage settings.</i>"
        )
    return "<b>✦ SETUP CONTROL</b>\n<i>Unknown setup step.</i>"


def _setup_buttons(step, user_id):
    """Build the inline keyboard for the current step."""
    buttons = ButtonMaker()
    step_idx = _SETUP_STEPS.index(step)
    if step_idx < len(_SETUP_STEPS) - 1:
        buttons.data_button("Next →", f"setup next {user_id} {step_idx + 1}")
    if step_idx > 0:
        buttons.data_button("← Back", f"setup next {user_id} {step_idx - 1}")
    if step_idx < len(_SETUP_STEPS) - 1:
        buttons.data_button("Skip", f"setup skip {user_id} {step_idx + 1}")
    else:
        buttons.data_button("Done", f"setup close {user_id}")
    buttons.data_button("Close", f"setup close {user_id}", "footer")
    return buttons.build_menu(2)


@new_task
async def setup_wizard(_, message):
    """Phase 5.8 — /setup command. Owner only."""
    user = message.from_user or message.sender_chat
    if user is None or user.id != Config.OWNER_ID:
        await send_message(
            message,
            "<b>✦ SETUP LOCKED</b>\n"
            "<i>This command is only available to the bot owner.</i>",
        )
        return
    step = _SETUP_STEPS[0]
    msg = _setup_message(step, {})
    buttons = _setup_buttons(step, user.id)
    await send_message(message, msg, buttons)


@new_task
async def setup_callback(_, query):
    """Handle setup wizard inline button callbacks."""
    data = query.data.split()
    if len(data) < 3:
        await query.answer("Invalid callback.", show_alert=True)
        return
    try:
        user_id = int(data[2])
    except ValueError:
        await query.answer("Invalid callback.", show_alert=True)
        return
    if query.from_user.id != user_id:
        await query.answer("Not authorized.", show_alert=True)
        return
    action = data[1]
    if action == "close":
        await query.answer()
        await delete_message(query.message)
        return
    if action not in {"next", "skip"} or len(data) < 4:
        await query.answer("Invalid callback.", show_alert=True)
        return
    try:
        step_idx = int(data[3])
    except ValueError:
        await query.answer("Invalid step.", show_alert=True)
        return
    if step_idx < 0 or step_idx >= len(_SETUP_STEPS):
        await query.answer("Invalid step.", show_alert=True)
        return
    step = _SETUP_STEPS[step_idx]
    await query.answer()
    msg = _setup_message(step, {})
    buttons = _setup_buttons(step, user_id)
    await edit_message(query.message, msg, buttons)
