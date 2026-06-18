from asyncio import sleep
from datetime import datetime
from urllib.parse import quote

from pyrogram import ContinuePropagation
from pyrogram.enums import ButtonStyle
from pyrogram.errors import FloodWait

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import get_web_secret
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.ext_utils.shortener_utils import short_url
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import edit_message, send_message
from web.security import make_route_token


MEDIA_TYPES = (
    "audio",
    "document",
    "photo",
    "sticker",
    "animation",
    "video",
    "voice",
    "video_note",
)


def get_media(message):
    if not message:
        return None
    for media_type in MEDIA_TYPES:
        if media := getattr(message, media_type, None):
            return media
    return None


def get_media_type(message):
    if not message:
        return "file"
    for media_type in MEDIA_TYPES:
        if getattr(message, media_type, None):
            return media_type
    return "file"


def get_filename(message, media=None):
    media = media or get_media(message)
    filename = getattr(media, "file_name", None) if media else None
    if filename:
        return filename.decode("utf-8", errors="replace") if isinstance(filename, bytes) else str(filename)

    media_type = get_media_type(message)
    ext_map = {
        "photo": "jpg",
        "audio": "mp3",
        "voice": "ogg",
        "video": "mp4",
        "animation": "mp4",
        "video_note": "mp4",
        "sticker": "webp",
    }
    ext = ext_map.get(media_type, "bin")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"Amaterasu FileToLink_{timestamp}.{ext}"


def quote_media_name(filename: str) -> str:
    return quote(str(filename).replace("/", "_"), safe="")


def is_streamable(filename):
    ext = filename.split('.')[-1].lower() if '.' in filename else ''
    streamable_exts = [
        'mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'wmv', 'm4v', # Video
        'mp3', 'ogg', 'wav', 'flac', 'm4a', 'aac', # Audio
        'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', # Image
        'pdf', 'doc', 'docx', 'txt' # Docs
    ]
    return ext in streamable_exts


async def maybe_shorten(link: str) -> str:
    if not (Config.SHORTEN_ENABLED and Config.SHORTEN_MEDIA_LINKS):
        return link
    try:
        return await short_url(link)
    except Exception as e:
        LOGGER.warning(f"Failed to shorten FileToLink URL: {e}")
        return link


async def generate_link_markup(chat_id, message_id, filename, secure_hash=""):
    token_path = f"/{secure_hash}" if secure_hash else f"/{chat_id}/{message_id}/{quote_media_name(filename)}"
    base_url = Config.BASE_URL.rstrip("/")
    
    stream_link = await maybe_shorten(f"{base_url}/watch{token_path}")
    download_link = await maybe_shorten(f"{base_url}/dl{token_path}")
    
    buttons = ButtonMaker()
    buttons.url_button("▶️ STREAM", stream_link, style=ButtonStyle.PRIMARY)
    buttons.url_button("⬇️ DOWNLOAD", download_link, style=ButtonStyle.SUCCESS)
        
    return buttons.build_menu(2), stream_link, download_link


def _stream_token(chat_id, message_id, unique_id):
    return make_route_token(
        get_web_secret(),
        "stream",
        int(chat_id),
        int(message_id),
    )


async def copy_to_bin(message):
    try:
        try:
            return await message.copy(chat_id=Config.BIN_CHANNEL)
        except FloodWait as e:
            await sleep(e.value)
            return await message.copy(chat_id=Config.BIN_CHANNEL)
    except Exception as e:
        if "MEDIA_CAPTION_TOO_LONG" in str(e):
            try:
                try:
                    return await message.copy(chat_id=Config.BIN_CHANNEL, caption=None)
                except FloodWait as flood:
                    await sleep(flood.value)
                    return await message.copy(chat_id=Config.BIN_CHANNEL, caption=None)
            except Exception as copy_error:
                LOGGER.error(f"Failed to copy FileToLink media without caption: {copy_error}")
                return None
        LOGGER.error(f"Failed to copy FileToLink media to BIN_CHANNEL: {e}")
        return None


async def prepare_stored_media(message):
    media = get_media(message)
    if Config.BIN_CHANNEL:
        copied = await copy_to_bin(message)
        if not copied:
            raise RuntimeError("Failed to store media in BIN_CHANNEL.")
        media = get_media(copied) or media
        
        user = message.from_user or message.sender_chat
        user_mention = user.mention(style="html") if hasattr(user, "mention") else getattr(user, "title", "Unknown")
            
        user_id = user.id
        file_id = getattr(media, "file_unique_id", "Unknown")
        
        reply_text = (
            f"<b>❖ FILETOLINK LOGGER</b>\n<code>"
            f"┌─ {'Requested':<10}: </code>{user_mention}<code>\n"
            f"├─ {'User ID':<10}: {user_id}\n"
            f"└─ {'File ID':<10}: {file_id}</code>"
        )
        
        try:
            await copied.reply(reply_text, quote=True)
        except Exception as e:
            LOGGER.error(f"Failed to reply to copied message in BIN_CHANNEL: {e}")
            
        return Config.BIN_CHANNEL, copied.id, media
    return message.chat.id, message.id, media


def build_caption(title, filename, readable_size, stream_link, download_link):
    title = title.replace("❖ ", "").strip()
    caption = (
        f"<b>❖ {title}</b>\n"
        f"<code>┌─ {'Name':<6} : {filename}\n"
        f"└─ {'Size':<6} : {readable_size}</code>\n\n"
        f"<b>⋗ Download Link:</b>\n<code>{download_link}</code>\n\n"
        f"<b>⋗ Stream Link:</b>\n<code>{stream_link}</code>"
    )
    return caption


async def process_media_message(client, message, reply_to_msg):
    media = get_media(reply_to_msg)
    if not media:
        await send_message(message, "Replied message is not a valid media file.")
        return
        
    filename = get_filename(reply_to_msg, media)
        
    file_size = getattr(media, "file_size", 0) or 0
    readable_size = get_readable_file_size(file_size)
    
    status_msg = await send_message(message, "<i>◷ Processing file... Please wait.</i>")
    
    try:
        chat_id, message_id, stored_media = await prepare_stored_media(reply_to_msg)
        unique_id = getattr(stored_media, "file_unique_id", "")
            
        secure_hash = _stream_token(chat_id, message_id, unique_id)
            
        markup, stream_link, download_link = await generate_link_markup(chat_id, message_id, filename, secure_hash)
        
        caption = build_caption("𝗬𝗼𝘂𝗿 𝗟𝗶𝗻𝗸 𝗚𝗲𝗻𝗲𝗿𝗮𝘁𝗲𝗱 !", filename, readable_size, stream_link, download_link)
        
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
    max_batch = max(1, int(Config.MAX_BATCH_FILES or 50))
    if len(args) > 1:
        if not args[1].isdigit():
            await send_message(message, "Batch count must be a number.")
            return
        batch_count = int(args[1])
        if batch_count < 1 or batch_count > max_batch:
            await send_message(message, f"Batch count must be between 1 and {max_batch}.")
            return
        
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
                    failed += 1
                    continue
                    
                media = get_media(msg)
                filename = get_filename(msg, media)
                t_chat_id, t_message_id, stored_media = await prepare_stored_media(msg)
                unique_id = getattr(stored_media, "file_unique_id", "")
                    
                secure_hash = _stream_token(t_chat_id, t_message_id, unique_id)
                    
                markup, stream_link, download_link = await generate_link_markup(t_chat_id, t_message_id, filename, secure_hash)
                
                readable_size = get_readable_file_size(getattr(media, "file_size", 0) or 0)
                caption = build_caption(f"𝗕𝗮𝘁𝗰𝗵 𝗙𝗶𝗹𝗲 {processed + 1}", filename, readable_size, stream_link, download_link)
                await send_message(message, caption, markup)
                processed += 1
            except Exception as e:
                LOGGER.error(f"Failed to process batch message {msg_id}: {e}")
                failed += 1
                
        await edit_message(status_msg, f"<b>❖ BATCH COMPLETED</b>\n\n<code>┌─ {'Processed':<9} : {processed}\n└─ {'Failed':<9} : {failed}</code>")
    else:
        await process_media_message(client, message, message.reply_to_message)

async def private_media_handler(client, message):
    from bot import user_data
    if not Config.BASE_URL:
        raise ContinuePropagation
    if not get_media(message):
        raise ContinuePropagation
    if not message.from_user:
        raise ContinuePropagation

    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})
    if not user_dict.get("AUTO_FILETOLINK", True):
        raise ContinuePropagation

    await process_media_message(client, message, message)


def _blocked_channel_ids():
    blocked = set()
    for cid in str(Config.BANNED_CHANNELS or "").replace(",", " ").split():
        try:
            blocked.add(int(cid))
        except ValueError:
            continue
    return blocked


async def channel_media_handler(client, message):
    if not (Config.BASE_URL and Config.CHANNEL and get_media(message)):
        raise ContinuePropagation
    if Config.BIN_CHANNEL and message.chat and message.chat.id == int(Config.BIN_CHANNEL):
        raise ContinuePropagation
    if message.chat and message.chat.id in _blocked_channel_ids():
        raise ContinuePropagation

    media = get_media(message)
    filename = get_filename(message, media)
    readable_size = get_readable_file_size(getattr(media, "file_size", 0) or 0)

    try:
        chat_id, message_id, stored_media = await prepare_stored_media(message)
        secure_hash = _stream_token(chat_id, message_id, getattr(stored_media, "file_unique_id", ""))
        markup, stream_link, download_link = await generate_link_markup(chat_id, message_id, filename, secure_hash)
        caption = build_caption("𝗖𝗵𝗮𝗻𝗻𝗲𝗹 𝗙𝗶𝗹𝗲 𝗥𝗲𝗮𝗱𝘆", filename, readable_size, stream_link, download_link)
        try:
            await message.edit_reply_markup(reply_markup=markup)
        except Exception:
            await send_message(message, caption, markup)
    except Exception as e:
        LOGGER.error(f"Error in channel FileToLink processing: {e}")

