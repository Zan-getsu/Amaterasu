import os
import time
import logging
from pyrogram.handlers import MessageHandler
from pyrogram.filters import command, private, document, video, audio
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import user_data
from bot.core.tg_client import TgClient
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import send_message, edit_message, delete_message
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.ext_utils.bot_utils import update_user_ldata, new_task
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.core.config_manager import Config

from bot.helper.ext_utils.autorename_utils import apply_autorename_template
from bot.modules.rename import get_media, user_media_to_rename, user_rename_preferences

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
        
        buttons = [[InlineKeyboardButton("❖ DOCUMENT", callback_data=f"ren_up_document_{user_id}")]]
        media_type = type(media).__name__.lower()
        if media_type in ["video", "document"]:
            buttons.append([InlineKeyboardButton("❖ VIDEO", callback_data=f"ren_up_video_{user_id}")])
        elif media_type == "audio":
            buttons.append([InlineKeyboardButton("❖ AUDIO", callback_data=f"ren_up_audio_{user_id}")])
            
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
        is_enabled = user_data.get(user_id, {}).get("AUTORENAME_ENABLED", False)
        new_state = not is_enabled
        update_user_ldata(user_id, "AUTORENAME_ENABLED", new_state)
        
        @new_task
        async def update_db():
            await database.update_user_data(user_id)
        update_db()
        
        status = "ENABLED" if new_state else "DISABLED"
        msg = (
            "<b>❖ AUTO-RENAME CONFIG</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"├ Status   : <code>{status}</code>\n"
            f"├ Template : <code>{current_template or 'None'}</code>\n"
            "├ Set CMD  : <code>/autorename [Template]</code>\n"
            "├ <b>Variables</b>:\n"
            "│  ├ <code>{title}</code> : Base name\n"
            "│  ├ <code>{season}</code> : Season (e.g. 01)\n"
            "│  ├ <code>{episode}</code> : Episode (e.g. 02)\n"
            "│  └ <code>{quality}</code> : Quality (e.g. 1080p)\n"
            "└ Tip      : <i>Reply to any file with /autorename to rename immediately.</i>"
        )
        await send_message(message, msg)
        return

    format_template = command_parts[1].strip()

    # Save to user_data and database
    update_user_ldata(user_id, "AUTORENAME_TEMPLATE", format_template)
    
    @new_task
    async def update_db_template():
        await database.update_user_data(user_id)
    update_db_template()

    await send_message(
        message,
        f"<b>❖ AUTO-RENAME SETTINGS</b>\n"
        f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"├ Status   : <code>Template Saved Successfully!</code>\n"
        f"├ Template : <code>{format_template}</code>\n"
        f"└ Info     : <i>Files will be auto-renamed on upload. Reply with /autorename to rename files instantly.</i>"
    )

async def auto_rename_files(client, message):
    user_id = message.from_user.id
    
    is_enabled = user_data.get(user_id, {}).get("AUTORENAME_ENABLED", False)
    if not is_enabled:
        return
        
    current_template = user_data.get(user_id, {}).get("AUTORENAME_TEMPLATE", "")
    if not current_template or current_template == "None":
        return
        
    media = get_media(message)
    if not media:
        return

    file_name = getattr(media, "file_name", None)
    if not file_name:
        ext_map = {"photo": "jpg", "audio": "mp3", "voice": "ogg", "video": "mp4", "animation": "mp4", "video_note": "mp4", "sticker": "webp"}
        media_type_orig = type(media).__name__.lower()
        ext = ext_map.get(media_type_orig, "bin")
        file_name = f"Stream_{message.id}.{ext}"

    new_name = apply_autorename_template(file_name, current_template)
    if new_name == file_name:
        return
    
    upload_type = "document"
    if getattr(message, "video", None):
        upload_type = "video"
    elif getattr(message, "audio", None):
        upload_type = "audio"

    progress_msg = await send_message(message, "<i>◷ Downloading file for auto-rename...</i>")
    
    try:
        last_dl_edit = 0
        async def progress_callback(current, total):
            nonlocal last_dl_edit
            now = time.time()
            if now - last_dl_edit < 4 and current < total:
                return
            last_dl_edit = now
            try:
                pct = (current * 100) / total if total else 0
                await edit_message(
                    progress_msg, 
                    f"<b>❖ AUTO-RENAME DOWNLOAD</b>\n"
                    f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                    f"└ Prog : <code>{pct:.1f}%</code> of <code>{get_readable_file_size(total)}</code>"
                )
            except Exception:
                pass
        
        download_dir = "downloads"
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        local_path = await message.download(
            file_name=os.path.join(download_dir, new_name),
            progress=progress_callback
        )
        
        if not local_path or not os.path.exists(local_path):
            raise Exception("Failed to download file.")
            
        await edit_message(progress_msg, "<i>◷ Uploading auto-renamed file...</i>")
        
        thumb_path = f"thumbnails/{user_id}.jpg"
        has_thumb = os.path.exists(thumb_path)
        
        custom_caption = f"<b>File Name:</b> <code>{new_name}</code>"
        if user_caption := Config.get_all().get("LEECH_CAPTION"):
            try:
                custom_caption = user_caption.format(filename=new_name)
            except Exception:
                pass
            
        last_up_edit = 0
        async def upload_progress(current, total):
            nonlocal last_up_edit
            now = time.time()
            if now - last_up_edit < 4 and current < total:
                return
            last_up_edit = now
            try:
                pct = (current * 100) / total if total else 0
                await edit_message(
                    progress_msg, 
                    f"<b>❖ AUTO-RENAME UPLOAD</b>\n"
                    f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                    f"└ Prog : <code>{pct:.1f}%</code> of <code>{get_readable_file_size(total)}</code>"
                )
            except Exception:
                pass

        duration = 0
        if upload_type in ["video", "audio"]:
            try:
                from hachoir.metadata import extractMetadata
                from hachoir.parser import createParser
                metadata = extractMetadata(createParser(local_path))
                if metadata and metadata.has("duration"):
                    duration = metadata.get('duration').seconds
            except Exception:
                pass

        if upload_type == "video":
            await client.send_video(
                chat_id=message.chat.id,
                video=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                supports_streaming=True,
                duration=duration,
                reply_to_message_id=message.id,
                progress=upload_progress
            )
        elif upload_type == "audio":
            await client.send_audio(
                chat_id=message.chat.id,
                audio=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                duration=duration,
                reply_to_message_id=message.id,
                progress=upload_progress
            )
        else:
            await client.send_document(
                chat_id=message.chat.id,
                document=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                reply_to_message_id=message.id,
                progress=upload_progress
            )
            
        await delete_message(progress_msg)
        
        if os.path.exists(local_path):
            os.remove(local_path)
            
    except Exception as e:
        logging.error(f"Error auto-renaming file: {e}")
        await edit_message(progress_msg, f"<b>⚑ ERROR:</b> <i>Failed to auto-rename file. {str(e)}</i>")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

TgClient.bot.add_handler(MessageHandler(autorename_command, filters=command(BotCommands.AutoRenameCommand)))
TgClient.bot.add_handler(MessageHandler(auto_rename_files, filters=private & (document | video | audio)))
