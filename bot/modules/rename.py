import os
import asyncio
from pyrogram.filters import command, reply, private
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, ForceReply

from bot import LOGGER, bot_loop
from bot.core.tg_client import TgClient
from bot.core.config_manager import Config
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import send_message, edit_message, delete_message
from bot.helper.ext_utils.status_utils import get_readable_file_size

# Set to keep track of users who enabled Rename Mode
RENAME_MODE_USERS = set()

# Dictionary to hold pending text replies for conversations (message_id -> Future)
pending_replies = {}

# Dictionary to track the original media message when renaming (user_id -> Message)
user_media_to_rename = {}
user_rename_preferences = {}

def is_rename_mode(user_id: int) -> bool:
    return user_id in RENAME_MODE_USERS

def toggle_rename_mode(user_id: int) -> bool:
    if user_id in RENAME_MODE_USERS:
        RENAME_MODE_USERS.remove(user_id)
        return False
    else:
        RENAME_MODE_USERS.add(user_id)
        return True

async def wait_for_reply(message_id: int, timeout: int = 60) -> Message:
    future = asyncio.Future()
    pending_replies[message_id] = future
    try:
        return await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        pending_replies.pop(message_id, None)

def get_media(message):
    if not message:
        return None
    for media_type in ["document", "video", "audio", "photo", "voice", "animation", "video_note", "sticker"]:
        if media := getattr(message, media_type, None):
            return media
    return None

async def prompt_rename_choice(client, message, media_msg):
    media = get_media(media_msg)
    if not media:
        return
        
    user_id = message.from_user.id
    user_media_to_rename[user_id] = media_msg
    
    file_name = getattr(media, "file_name", None)
    if not file_name:
        ext_map = {
            "photo": "jpg",
            "audio": "mp3",
            "voice": "ogg",
            "video": "mp4",
            "animation": "mp4",
            "video_note": "mp4",
            "sticker": "webp",
        }
        media_type = type(media).__name__.lower()
        ext = ext_map.get(media_type, "bin")
        file_name = f"Stream_{media_msg.id}.{ext}"
        
    file_size = get_readable_file_size(getattr(media, "file_size", 0) or 0)
    
    caption = (
        f"✏️ <b>Rename Mode Active!</b>\n\n"
        f"<b>Original File:</b> <code>{file_name}</code>\n"
        f"<b>Size:</b> {file_size}\n\n"
        f"Choose an option to rename this file:"
    )
    
    buttons = [
        [
            InlineKeyboardButton("✏️ Rename", callback_data=f"ren_choice_ren_{user_id}"),
            InlineKeyboardButton("🤖 Auto-Rename", callback_data=f"ren_choice_auto_{user_id}")
        ],
        [
            InlineKeyboardButton("ℹ️ File Info", callback_data=f"ren_choice_info_{user_id}"),
            InlineKeyboardButton("✖️ Cancel", callback_data=f"ren_choice_cancel_{user_id}")
        ]
    ]
    
    await send_message(message, caption, InlineKeyboardMarkup(buttons))

async def rename_command_handler(client, message):
    user_id = message.from_user.id
    
    if message.reply_to_message and get_media(message.reply_to_message):
        await prompt_rename_choice(client, message, message.reply_to_message)
        return
        
    is_active = toggle_rename_mode(user_id)
    if is_active:
        msg = (
            "✏️ <b>Rename Mode has been toggled ON!</b>\n\n"
            "• Send any media file in PM to rename it.\n"
            "• Initiate any leech task (e.g. `/leech`) to be prompted to rename the output before proceeding."
        )
    else:
        msg = "✖️ <b>Rename Mode has been toggled OFF!</b>"
        
    await send_message(message, msg)

async def rename_private_media_handler(client, message):
    if not message.from_user:
        return
    if not get_media(message):
        return
    user_id = message.from_user.id
    if is_rename_mode(user_id):
        await prompt_rename_choice(client, message, message)

async def prompt_leech_rename(client, message) -> str:
    prompt = await send_message(
        message,
        "✏️ <b>Rename Mode is active!</b>\n\n"
        "Reply to this message with the **new filename** (with extension) for this leech task, "
        "or click the button below to use the original filename.",
        reply_to_message_id=message.id
    )
    
    await edit_message(
        prompt,
        "✏️ <b>Rename Mode is active!</b>\n\n"
        "Reply to this message with the **new filename** (with extension) for this leech task, "
        "or click the button below to use the original filename.",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("Use Original Name", callback_data=f"leech_orig_{prompt.id}")]
        ])
    )
    
    reply_msg = await wait_for_reply(prompt.id, timeout=60)
    
    if not reply_msg or not getattr(reply_msg, "text", None):
        await delete_message(prompt)
        return "skip"
        
    if isinstance(reply_msg, str) and reply_msg == "skip":
        await delete_message(prompt)
        return "skip"
        
    new_name = reply_msg.text.strip()
    await delete_message(reply_msg)
    await delete_message(prompt)
    return new_name

async def rename_callback_handler(client, query):
    data = query.data
    user_id = query.from_user.id
    
    if data.startswith("leech_orig_"):
        prompt_id = int(data.split("_")[2])
        if prompt_id in pending_replies:
            future = pending_replies[prompt_id]
            if not future.done():
                future.set_result("skip")
        await query.answer("Using original filename.")
        return

    if data.startswith("ren_up_"):
        # ren_up_document_12345 -> upload_type="document"
        parts = data.split("_")
        upload_type = parts[2]  # document, video, audio
        target_user_id = int(parts[3])
        if user_id != target_user_id:
            await query.answer("This menu is not for you!", show_alert=True)
            return
        await _handle_upload(client, query, user_id, upload_type)
        return

    if not data.startswith("ren_choice_"):
        return
        
    target_user_id = int(data.split("_")[-1])
    if user_id != target_user_id:
        await query.answer("This menu is not for you!", show_alert=True)
        return
        
    action = data.split("_")[2]
    
    if action == "cancel":
        user_media_to_rename.pop(user_id, None)
        await delete_message(query.message)
        await query.answer("Operation cancelled.")
        return
        
    elif action == "info":
        media_msg = user_media_to_rename.get(user_id)
        if not media_msg:
            await query.answer("Expired. Send the file again.", show_alert=True)
            return
            
        media = get_media(media_msg)
        media_type = type(media).__name__.lower()
        file_size = get_readable_file_size(getattr(media, "file_size", 0) or 0)
        file_name = getattr(media, "file_name", "None")
        mime_type = getattr(media, "mime_type", "None")
        unique_id = getattr(media, "file_unique_id", "None")
        
        info_text = (
            f"ℹ️ <b>File Metadata Details</b>\n\n"
            f"• <b>Type</b>: {media_type.capitalize()}\n"
            f"• <b>Name</b>: <code>{file_name}</code>\n"
            f"• <b>Mime</b>: <code>{mime_type}</code>\n"
            f"• <b>Size</b>: {file_size}\n"
            f"• <b>Unique ID</b>: <code>{unique_id}</code>"
        )
        
        buttons = [
            [InlineKeyboardButton("✏️ Rename", callback_data=f"ren_choice_ren_{user_id}")],
            [InlineKeyboardButton("✖️ Cancel", callback_data=f"ren_choice_cancel_{user_id}")]
        ]
        
        await edit_message(query.message, info_text, InlineKeyboardMarkup(buttons))
        await query.answer()
        
    elif action == "ren":
        media_msg = user_media_to_rename.get(user_id)
        if not media_msg:
            await query.answer("Expired. Send the file again.", show_alert=True)
            return
            
        await query.answer()
        await delete_message(query.message)
        
        await client.send_message(
            chat_id=query.message.chat.id,
            text="✏️ **Please enter the new filename:**\n\n_Reply to this message with the new name._",
            reply_to_message_id=media_msg.id,
            reply_markup=ForceReply(True)
        )
        
    elif action == "auto":
        media_msg = user_media_to_rename.get(user_id)
        if not media_msg:
            await query.answer("Expired. Send the file again.", show_alert=True)
            return
            
        from bot import user_data
        current_template = user_data.get(user_id, {}).get("AUTORENAME_TEMPLATE", "")
        if not current_template or current_template == "None":
            await query.answer("You have not set an Auto-Rename Template!", show_alert=True)
            return
            
        await query.answer()
        await delete_message(query.message)
        
        media = get_media(media_msg)
        file_name = getattr(media, "file_name", None)
        if not file_name:
            ext_map = {"photo": "jpg", "audio": "mp3", "voice": "ogg", "video": "mp4", "animation": "mp4", "video_note": "mp4", "sticker": "webp"}
            media_type = type(media).__name__.lower()
            ext = ext_map.get(media_type, "bin")
            file_name = f"Stream_{media_msg.id}.{ext}"

        from bot.helper.ext_utils.autorename_utils import apply_autorename_template
        new_name = apply_autorename_template(file_name, current_template)
        user_rename_preferences[user_id] = new_name
        
        buttons = [[InlineKeyboardButton("📁 Document", callback_data=f"ren_up_document_{user_id}")]]
        media_type = type(media).__name__.lower()
        if media_type in ["video", "document"]:
            buttons.append([InlineKeyboardButton("🎥 Video", callback_data=f"ren_up_video_{user_id}")])
        elif media_type == "audio":
            buttons.append([InlineKeyboardButton("🎵 Audio", callback_data=f"ren_up_audio_{user_id}")])
            
        await client.send_message(
            chat_id=query.message.chat.id,
            text=f"**Auto-Rename Applied!**\n\n**New File Name:** `{new_name}`\n\n**Select the output file type:**",
            reply_markup=InlineKeyboardMarkup(buttons),
            reply_to_message_id=media_msg.id
        )
        

async def _handle_upload(client, query, user_id, upload_type):
    new_name = user_rename_preferences.pop(user_id, None)
    media_msg = user_media_to_rename.pop(user_id, None)
    
    if not new_name or not media_msg:
        await query.answer("Session expired. Please try again.", show_alert=True)
        return
        
    await query.answer()
    progress_msg = await edit_message(query.message, "⏳ <b>Downloading file from Telegram...</b>")
    
    try:
        import time
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
                    f"⏳ <b>Downloading file from Telegram...</b>\n"
                    f"Progress: <code>{pct:.1f}%</code> of {get_readable_file_size(total)}"
                )
            except Exception:
                pass
        
        download_dir = "downloads"
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        local_path = await media_msg.download(
            file_name=os.path.join(download_dir, new_name),
            progress=progress_callback
        )
        
        if not local_path or not os.path.exists(local_path):
            raise Exception("Failed to download file.")
            
        await edit_message(progress_msg, "⚡ <b>Uploading renamed file to Telegram...</b>")
        
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
                    f"⚡ <b>Uploading renamed file to Telegram...</b>\n"
                    f"Progress: <code>{pct:.1f}%</code> of {get_readable_file_size(total)}"
                )
            except Exception:
                pass

        # Extract duration if video or audio
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
                chat_id=media_msg.chat.id,
                video=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                supports_streaming=True,
                duration=duration,
                reply_to_message_id=media_msg.id,
                progress=upload_progress
            )
        elif upload_type == "audio":
            await client.send_audio(
                chat_id=media_msg.chat.id,
                audio=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                duration=duration,
                reply_to_message_id=media_msg.id,
                progress=upload_progress
            )
        else:
            await client.send_document(
                chat_id=media_msg.chat.id,
                document=local_path,
                caption=custom_caption,
                thumb=thumb_path if has_thumb else None,
                reply_to_message_id=media_msg.id,
                progress=upload_progress
            )
            
        await delete_message(progress_msg)
        
        if os.path.exists(local_path):
            os.remove(local_path)
            
    except Exception as e:
        LOGGER.error(f"Error renaming file: {e}")
        await edit_message(progress_msg, f"✖️ <b>Failed to rename file. Error:</b> <code>{str(e)}</code>")
        if 'local_path' in locals() and os.path.exists(local_path):
            os.remove(local_path)

async def reply_listener(client, message):
    if message.reply_to_message and message.reply_to_message.id in pending_replies:
        future = pending_replies[message.reply_to_message.id]
        if not future.done():
            future.set_result(message)


async def rename_force_reply_handler(client, message):
    reply_message = message.reply_to_message
    if not reply_message or not reply_message.reply_markup or not isinstance(reply_message.reply_markup, ForceReply):
        return
        
    if not reply_message.text or "Please enter the new filename" not in reply_message.text:
        return

    if not message.text:
        await send_message(message, "Please send a text filename, not media.")
        return
        
    new_name = message.text.strip()
    user_id = message.from_user.id
    
    media_msg = reply_message.reply_to_message
    if not media_msg:
        media_msg = user_media_to_rename.get(user_id)
    if not media_msg:
        await send_message(message, "Expired. Send the file again.")
        return

    media = get_media(media_msg)
    if not media:
        await send_message(message, "Could not find media in the original message.")
        return
        
    # Infer extension if user didn't provide one
    if "." not in new_name:
        extn = "bin"
        if hasattr(media, "file_name") and media.file_name and "." in media.file_name:
            extn = media.file_name.rsplit('.', 1)[-1]
        elif getattr(media, "mime_type", None):
            mime = media.mime_type
            if "video" in mime: extn = "mp4"
            elif "audio" in mime: extn = "mp3"
            elif "image" in mime: extn = "jpg"
            else: extn = "mkv"
        new_name = f"{new_name}.{extn}"
        
    user_rename_preferences[user_id] = new_name
    
    await delete_message(reply_message)
    await delete_message(message)
    
    buttons = [[InlineKeyboardButton("📁 Document", callback_data=f"ren_up_document_{user_id}")]]
    
    media_type = type(media).__name__.lower()
    if media_type in ["video", "document"]:
        buttons.append([InlineKeyboardButton("🎥 Video", callback_data=f"ren_up_video_{user_id}")])
    elif media_type == "audio":
        buttons.append([InlineKeyboardButton("🎵 Audio", callback_data=f"ren_up_audio_{user_id}")])
        
    await client.send_message(
        chat_id=message.chat.id,
        text=f"**Select the output file type:**\n\n**File Name:** `{new_name}`",
        reply_markup=InlineKeyboardMarkup(buttons),
        reply_to_message_id=media_msg.id
    )
