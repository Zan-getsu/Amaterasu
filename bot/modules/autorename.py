from pyrogram.handlers import MessageHandler
from pyrogram.filters import command, regex

from bot import bot, user_data
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import send_message, edit_message
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

async def autorename_command(client, message):
    user_id = message.from_user.id

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        # User just typed /autorename without arguments
        current_template = user_data.get(user_id, {}).get("AUTORENAME_TEMPLATE", "None")
        msg = (
            "<b>Auto-Rename Configuration</b>\n\n"
            f"<b>Current Template:</b> <code>{current_template}</code>\n\n"
            "<b>To set a new template, use:</b>\n"
            "<code>/autorename [Your Prefix] {title} S{season}E{episode} - {quality}</code>\n\n"
            "<b>Available Variables:</b>\n"
            "• <code>{title}</code> - Base name of the file without extra metadata\n"
            "• <code>{season}</code> - Extracted Season number (e.g. 01)\n"
            "• <code>{episode}</code> - Extracted Episode number (e.g. 02)\n"
            "• <code>{quality}</code> - Extracted Quality (e.g. 1080p)"
        )
        await send_message(message, msg)
        return

    format_template = command_parts[1].strip()

    # Save to user_data and database
    from bot.helper.ext_utils.bot_utils import update_user_ldata
    update_user_ldata(user_id, "AUTORENAME_TEMPLATE", format_template)
    await database.update_user_data(user_id)

    await send_message(
        message,
        f"<b>🌟 Auto-Rename Template Saved!</b>\n\n"
        f"<b>Your new template:</b> <code>{format_template}</code>\n\n"
        "Files will be automatically renamed before upload according to this format."
    )

bot.add_handler(MessageHandler(autorename_command, filters=command("autorename")))
