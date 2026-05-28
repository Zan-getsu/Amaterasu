from pyrogram.filters import command, reply, private, create
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from urllib.parse import quote

from bot import LOGGER
from bot.core.tg_client import TgClient
from bot.core.config_manager import Config
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import send_message, edit_message, delete_message

def get_media(message):
    if not message:
        return None
    for media_type in ["document", "video", "audio", "photo", "voice", "animation", "video_note", "sticker"]:
        if media := getattr(message, media_type, None):
            return media
    return None

def is_streamable(filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    streamable_exts = [
        'mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'm4v', # Video
        'mp3', 'ogg', 'wav', 'flac', 'm4a', 'aac', # Audio
        'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', # Image
        'pdf', 'doc', 'docx', 'txt' # Docs
    ]
    return ext in streamable_exts

async def generate_link_markup(chat_id, message_id, filename, secure_hash=""):
    encoded_filename = quote(filename)
    hash_query = f"?hash={secure_hash}" if secure_hash else ""
    hash_query_amp = f"&hash={secure_hash}" if secure_hash else ""
    
    stream_link = f"{Config.BASE_URL}/watch/{chat_id}/{message_id}/{encoded_filename}{hash_query}"
    download_link = f"{Config.BASE_URL}/stream/{chat_id}/{message_id}/{encoded_filename}?disposition=attachment{hash_query_amp}"
    
    buttons = []
    if is_streamable(filename):
        buttons.append([
            InlineKeyboardButton("❖ STREAM ONLINE", url=stream_link),
            InlineKeyboardButton("❖ DIRECT DOWNLOAD", url=download_link)
        ])
    else:
        stream_link = None
        buttons.append([
            InlineKeyboardButton("❖ DIRECT DOWNLOAD", url=download_link)
        ])
        
    return InlineKeyboardMarkup(buttons), stream_link, download_link

async def process_media_message(client, message, reply_to_msg):
    media = get_media(reply_to_msg)
    if not media:
        await send_message(message, "Replied message is not a valid media file.")
        return
        
    filename = getattr(media, "file_name", None)
    if not filename:
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
        filename = f"Stream_{reply_to_msg.id}.{ext}"
        
    file_size = getattr(media, "file_size", 0) or 0
    readable_size = get_readable_file_size(file_size)
    
    status_msg = await send_message(message, "<i>◷ Processing file... Please wait.</i>")
    
    try:
        if Config.BIN_CHANNEL:
            media_copy = await reply_to_msg.copy(chat_id=Config.BIN_CHANNEL)
            chat_id = Config.BIN_CHANNEL
            message_id = media_copy.id
            copied_media = get_media(media_copy)
            unique_id = getattr(copied_media, "file_unique_id", "") if copied_media else ""
        else:
            chat_id = reply_to_msg.chat.id
            message_id = reply_to_msg.id
            unique_id = getattr(media, "file_unique_id", "")
            
        secure_hash = unique_id[:6] if len(unique_id) >= 6 else unique_id
            
        markup, stream_link, download_link = await generate_link_markup(chat_id, message_id, filename, secure_hash)
        
        caption = (
            f"<b>❖ 𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !</b>\n"
            f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            f"├ 📂 <b>Name :</b> <code>{filename}</code>\n"
            f"│\n"
            f"├ 📦 <b>Size :</b> <code>{readable_size}</code>\n"
            f"│\n"
        )
        if stream_link:
            caption += f"├ 📥 <b>DL   :</b> <code>{download_link}</code>\n"
            caption += f"│\n"
            caption += f"└ 🖥 <b>Play :</b> <code>{stream_link}</code>"
        else:
            caption += f"└ 📥 <b>DL   :</b> <code>{download_link}</code>"
        
        await edit_message(status_msg, caption, markup)
    except Exception as e:
        LOGGER.error(f"Error in FileToLink processing: {e}")
        await edit_message(status_msg, f"<b>⚑ ERROR:</b> <i>Failed to generate links. {str(e)}</i>")

async def link_command_handler(client, message):
    if not Config.BASE_URL:
        await send_message(message, "BASE_URL is not configured in the bot settings.")
        return
        
    if not message.reply_to_message:
        await send_message(message, "Please reply to a media file to generate links.")
        return
        
    args = message.text.split()
    batch_count = 1
    if len(args) > 1 and args[1].isdigit():
        batch_count = min(int(args[1]), int(Config.MAX_BATCH_FILES))
        
    if batch_count > 1:
        start_msg_id = message.reply_to_message.id
        chat_id = message.chat.id
        status_msg = await send_message(message, f"<i>◷ Starting batch processing of {batch_count} files...</i>")
        
        processed = 0
        failed = 0
        
        for msg_id in range(start_msg_id, start_msg_id + batch_count):
            try:
                msg = await client.get_messages(chat_id, msg_id)
                if not msg or msg.empty or not get_media(msg):
                    continue
                    
                media = get_media(msg)
                filename = getattr(media, "file_name", f"Stream_{msg.id}.bin")
                
                if Config.BIN_CHANNEL:
                    media_copy = await msg.copy(chat_id=Config.BIN_CHANNEL)
                    t_chat_id = Config.BIN_CHANNEL
                    t_message_id = media_copy.id
                    copied_media = get_media(media_copy)
                    unique_id = getattr(copied_media, "file_unique_id", "") if copied_media else ""
                else:
                    t_chat_id = chat_id
                    t_message_id = msg.id
                    unique_id = getattr(media, "file_unique_id", "")
                    
                secure_hash = unique_id[:6] if len(unique_id) >= 6 else unique_id
                    
                markup, stream_link, download_link = await generate_link_markup(t_chat_id, t_message_id, filename, secure_hash)
                
                readable_size = get_readable_file_size(getattr(media, "file_size", 0) or 0)
                caption = (
                    f"<b>❖ 𝗕𝗮𝘁𝗰𝗵 𝗙𝗶𝗹𝗲 {processed + 1}</b>\n"
                    f"┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
                    f"├ 📂 <b>Name :</b> <code>{filename}</code>\n"
                    f"│\n"
                    f"├ 📦 <b>Size :</b> <code>{readable_size}</code>\n"
                    f"│\n"
                )
                if stream_link:
                    caption += f"├ 📥 <b>DL   :</b> <code>{download_link}</code>\n"
                    caption += f"│\n"
                    caption += f"└ 🖥 <b>Play :</b> <code>{stream_link}</code>"
                else:
                    caption += f"└ 📥 <b>DL   :</b> <code>{download_link}</code>"
                await send_message(message, caption, markup)
                processed += 1
            except Exception as e:
                LOGGER.error(f"Failed to process batch message {msg_id}: {e}")
                failed += 1
                
        await edit_message(status_msg, f"<b>❖ BATCH COMPLETED</b>\n┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n├ Processed: <code>{processed}</code>\n└ Failed   : <code>{failed}</code>")
    else:
        await process_media_message(client, message, message.reply_to_message)

async def private_media_handler(client, message):
    from pyrogram import ContinuePropagation
    if not Config.BASE_URL:
        raise ContinuePropagation
    if not get_media(message):
        raise ContinuePropagation

    await process_media_message(client, message, message)
