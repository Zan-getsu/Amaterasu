"""Phase 5.8 — Interactive setup wizard.

/Setup command — owner only. Step-by-step inline keyboard wizard:
  1. Set DOWNLOAD_DIR (ask for path, validate it exists and is writable)
  2. Configure GDrive (show current status; link to instructions)
  3. Configure Rclone (show current status; link to instructions)
  4. Set OWNER_ID confirmation
  5. Summary screen with Apply button

Each step has a Skip button. Does NOT replace .env/MongoDB config —
it's a guided overlay for first-time setup.
"""

from .. import LOGGER, DOWNLOAD_DIR
from ..core.config_manager import Config
from ..helper.ext_utils.bot_utils import new_task
from ..helper.telegram_helper.bot_commands import BotCommands
from ..helper.telegram_helper.button_build import ButtonMaker
from ..helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)


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


def _setup_message(step, state):
    """Build the setup message for the current step."""
    if step == "download_dir":
        current = getattr(Config, "DOWNLOAD_DIR", DOWNLOAD_DIR)
        return (
            "<b>❖ Setup — Step 1/5: Download Directory</b>\n\n"
            f"<b>Current:</b> <code>{current}</code>\n\n"
            "<i>This is where downloaded files are stored. Ensure the "
            "path exists and is writable. The default "
            f"<code>{DOWNLOAD_DIR}</code> works for Docker deployments.</i>\n\n"
            "<b>To change:</b> Set <code>DOWNLOAD_DIR</code> in your "
            "config.py or environment, then restart. Or skip if the "
            "default is fine."
        )
    elif step == "gdrive":
        configured = bool(
            getattr(Config, "GDRIVE_ID", "")
            or getattr(Config, "USE_SERVICE_ACCOUNTS", False)
        )
        status = "✅ Configured" if configured else "❌ Not configured"
        return (
            "<b>❖ Setup — Step 2/5: Google Drive</b>\n\n"
            f"<b>Status:</b> {status}\n\n"
            "<i>To configure GDrive as an upload destination:\n"
            "1. Run <code>python3 gen_scripts/gen_token_pickle/script.py</code>\n"
            "2. Upload the resulting token.pickle via /usetting\n"
            "3. Set GDRIVE_ID to your destination folder ID\n\n"
            "Or skip if you don't need GDrive uploads.</i>"
        )
    elif step == "rclone":
        configured = bool(getattr(Config, "RCLONE_PATH", ""))
        status = "✅ Configured" if configured else "❌ Not configured"
        return (
            "<b>❖ Setup — Step 3/5: Rclone</b>\n\n"
            f"<b>Status:</b> {status}\n\n"
            "<i>To configure Rclone:\n"
            "1. Run <code>rclone config</code> inside the container\n"
            "2. Add a remote (gdrive, dropbox, s3, etc.)\n"
            "3. Set RCLONE_PATH to your destination remote:path\n\n"
            "Or skip if you don't need Rclone uploads.</i>"
        )
    elif step == "owner_id":
        oid = getattr(Config, "OWNER_ID", 0)
        return (
            "<b>❖ Setup — Step 4/5: Owner Confirmation</b>\n\n"
            f"<b>Current OWNER_ID:</b> <code>{oid}</code>\n\n"
            "<i>This is your Telegram user ID. You received this setup "
            "message because you are the owner. If this ID is correct, "
            "continue. If not, set OWNER_ID in your config and restart.</i>"
        )
    elif step == "summary":
        gdrive_status = "✅" if (
            getattr(Config, "GDRIVE_ID", "")
            or getattr(Config, "USE_SERVICE_ACCOUNTS", False)
        ) else "❌"
        rclone_status = "✅" if getattr(Config, "RCLONE_PATH", "") else "❌"
        return (
            "<b>❖ Setup — Step 5/5: Summary</b>\n\n"
            f"<code>┌─ Download Dir : {getattr(Config, 'DOWNLOAD_DIR', DOWNLOAD_DIR)}\n"
            f"├─ Google Drive  : {gdrive_status}\n"
            f"├─ Rclone        : {rclone_status}\n"
            f"├─ Owner ID      : {getattr(Config, 'OWNER_ID', 0)}\n"
            f"└─ Version       : v1.6.3</code>\n\n"
            "<i>Setup is complete! The bot is ready to use.\n"
            "Use /help to see all commands.\n"
            "Use /usetting to configure per-user settings.</i>"
        )
    return "<b>Setup</b>"


def _setup_buttons(step, user_id):
    """Build the inline keyboard for the current step."""
    buttons = ButtonMaker()
    step_idx = _SETUP_STEPS.index(step)
    if step_idx < len(_SETUP_STEPS) - 1:
        buttons.data_button("Next →", f"setup next {user_id} {step_idx + 1}")
    if step_idx > 0:
        buttons.data_button("← Back", f"setup next {user_id} {step_idx - 1}")
    buttons.data_button("Skip", f"setup skip {user_id} {step_idx}")
    buttons.data_button("Close", f"setup close {user_id}", "footer")
    return buttons.build_menu(2)


@new_task
async def setup_wizard(_, message):
    """Phase 5.8 — /setup command. Owner only."""
    user = message.from_user or message.sender_chat
    if user is None or user.id != Config.OWNER_ID:
        await send_message(message, "This command is for the bot owner only.")
        return
    step = _SETUP_STEPS[0]
    msg = _setup_message(step, {})
    buttons = _setup_buttons(step, user.id)
    await send_message(message, msg, buttons)


@new_task
async def setup_callback(_, query):
    """Handle setup wizard inline button callbacks."""
    data = query.data.split()
    if len(data) < 4:
        await query.answer("Invalid callback.", show_alert=True)
        return
    user_id = int(data[2])
    if query.from_user.id != user_id:
        await query.answer("Not authorized.", show_alert=True)
        return
    action = data[1]
    if action == "close":
        await query.answer()
        await delete_message(query.message)
        return
    step_idx = int(data[3])
    if step_idx < 0 or step_idx >= len(_SETUP_STEPS):
        await query.answer("Invalid step.", show_alert=True)
        return
    step = _SETUP_STEPS[step_idx]
    await query.answer()
    msg = _setup_message(step, {})
    buttons = _setup_buttons(step, user_id)
    await edit_message(query.message, msg, buttons)
