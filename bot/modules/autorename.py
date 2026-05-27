from pyrogram.handlers import MessageHandler
from pyrogram.filters import command, regex

from bot import user_data
from bot.core.tg_client import TgClient
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import send_message, edit_message
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.button_build import ButtonMaker

from bot.helper.ext_utils.autorename_utils import apply_autorename_template
from bot.modules.rename import get_media, user_media_to_rename, user_rename_preferences
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import os

async def autorename_command(client, message):
    user_id = message.from_user.id
    current_template = user_data.get(user_id, {}).get("AUTORENAME_TEMPLATE", "")

    # If the user replies to a message containing media
    if message.reply_to_message and get_media(message.reply_to_message):
        media_msg = message.reply_to_message
        media = get_media(media_msg)
        if not current_template or current_template == "None":
            await send_message(message, "<b>⚑ ERROR:</b> <i>No Auto-Rename Template set.\nSet it using <code>/autorename [Template]</code></i>")
            return

        file_name = getattr(media, "file_name", None)
        if not file_name:
            # Fallback if no filename
            ext_map = {"photo": "jpg", "audio": "mp3", "voice": "ogg", "video": "mp4", "animation": "mp4", "video_note": "mp4", "sticker": "webp"}
            media_type = type(media).__name__.lower()
            ext = ext_map.get(media_type, "bin")
            file_name = f"Stream_{media_msg.id}.{ext}"

        new_name = apply_autorename_template(file_name, current_template)
        
        user_media_to_rename[user_id] = media_msg
        user_rename_preferences[user_id] = new_name
        
        buttons = [[InlineKeyboardButton("❖ DOCUMENT", callback_data=f"ren_up_document_{user_id}"]]
        media_type = type(media).__name__.lower()
        if media_type in ["video", "document"]:
            buttons.append([InlineKeyboardButton("❖ VIDEO", callback_data=f"ren_up_video_{user_id}"])
        elif media_type == "audio":
            buttons.append([InlineKeyboardButton("❖ AUDIO", callback_data=f"ren_up_audio_{user_id}"])
            
        await client.send_message(
            chat_id=message.chat.id,
            text=f"<b>❖ AUTO-RENAME APPLIED</b>\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n├ Name : <code>{new_name}</code>\n└ Info : Select the output file type.",
            reply_markup=InlineKeyboardMarkup(buttons),
            reply_to_message_id=media_msg.id
        )
        return

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        # User just typed /autorename without arguments
        msg = (
            "<b>❖ AUTO-RENAME CONFIG</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"├ Template : <code>{current_template or 'None'}</code>\n"
            "├ Set CMD  : <code>/autorename [Template]</code>\n"
            "├ <b>Variables</b>:\n"
            "│  ├ <code>{{title}}</code> : Base name\n"
            "│  ├ <code>{{season}}</code> : Season (e.g. 01)\n"
            "│  ├ <code>{{episode}}</code> : Episode (e.g. 02)\n"
            "│  └ <code>{{quality}}</code> : Quality (e.g. 1080p)\n"
            "└ Tip      : <i>Reply to any file with /autorename to rename immediately.</i>"
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
        f"<b>❖ AUTO-RENAME SETTINGS</b>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"├ Status   : <code>Template Saved Successfully!</code>\n"
        f"├ Template : <code>{format_template}</code>\n"
        f"└ Info     : <i>Files will be auto-renamed on upload. Reply with /autorename to rename files instantly.</i>"
    )

TgClient.bot.add_handler(MessageHandler(autorename_command, filters=command(BotCommands.AutoRenameCommand)))
