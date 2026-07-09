from asyncio import sleep
from contextlib import suppress
from datetime import datetime
from html import escape
from os import environ
from pathlib import Path
from urllib.parse import quote

from pyrogram import ContinuePropagation
from pyrogram.enums import ButtonStyle
from pyrogram.errors import FloodWait

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import arg_parser, get_web_secret
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.helper.ext_utils.shortener_utils import short_url
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.message_utils import edit_message, send_message
from web.security import make_route_token
# Phase 2.12 — import canonical media helpers from tg_utils (deduplication)
from bot.helper.telegram_helper.tg_utils import (
    MEDIA_TYPES,
    get_media,
    get_media_type,
)


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


def _cache_usage():
    cache_dir = Path(environ.get("FILETOLINK_CACHE_DIR", "/tmp/amaterasu-filetolink"))
    total_size = 0
    file_count = 0
    with suppress(OSError):
        for path in cache_dir.iterdir():
            with suppress(OSError):
                if path.is_file() and not path.name.endswith(".part"):
                    total_size += path.stat().st_size
                    file_count += 1
    return cache_dir, file_count, total_size


async def send_filetolink_status(message):
    from bot.core.tg_client import TgClient

    stream_clients = getattr(TgClient, "stream_clients", {}) or {}
    stream_loads = getattr(TgClient, "stream_loads", {}) or {}
    client_lines = []
    for client_id in sorted(stream_clients):
        client = stream_clients[client_id]
        username = getattr(getattr(client, "me", None), "username", None)
        name = f"@{username}" if username else ("main bot" if client_id == 0 else "stream bot")
        load = stream_loads.get(client_id, 0)
        client_lines.append(f"├─ #{client_id}: {escape(str(name))} | load {load}")

    cache_dir, cache_files, cache_size = _cache_usage()
    cache_max_mb = environ.get("FILETOLINK_CACHE_MAX_MB", "256")
    cache_total_mb = environ.get("FILETOLINK_CACHE_TOTAL_MAX_MB", "2048")
    base_url = Config.BASE_URL or "Not configured"
    bin_channel = Config.BIN_CHANNEL or "Disabled"
    leech_dump = Config.LEECH_DUMP_CHAT or "Disabled"
    stream_count = len(stream_clients) or 1
    client_block = "\n".join(client_lines) if client_lines else "└─ #0: main bot | load 0"

    text = (
        "<b>❖ FILETOLINK STATUS</b>\n"
        "<code>"
        f"┌─ {'Base URL':<12}: {escape(str(base_url))}\n"
        f"├─ {'BIN_CHANNEL':<12}: {escape(str(bin_channel))}\n"
        f"├─ {'Dump Chat':<12}: {escape(str(leech_dump))}\n"
        f"├─ {'Stream Bots':<12}: {stream_count}\n"
        f"├─ {'Cache Files':<12}: {cache_files}\n"
        f"├─ {'Cache Size':<12}: {get_readable_file_size(cache_size)}\n"
        f"├─ {'File Cap':<12}: {cache_max_mb} MB\n"
        f"├─ {'Total Cap':<12}: {cache_total_mb} MB\n"
        f"└─ {'Cache Dir':<12}: {escape(str(cache_dir))}\n\n"
        f"{client_block}"
        "</code>"
    )
    await send_message(message, text)


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
    async def copy_message(**kwargs):
        copied = await message.copy(
            chat_id=Config.BIN_CHANNEL,
            reply_markup=None,
            **kwargs,
        )
        with suppress(Exception):
            await copied.edit_reply_markup(reply_markup=None)
        return copied

    try:
        try:
            return await copy_message()
        except FloodWait as e:
            await sleep(e.value)
            return await copy_message()
    except Exception as e:
        if "MEDIA_CAPTION_TOO_LONG" in str(e):
            try:
                try:
                    return await copy_message(caption=None)
                except FloodWait as flood:
                    await sleep(flood.value)
                    return await copy_message(caption=None)
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


def parse_link_batch_count(command_text):
    input_list = (command_text or "").split()
    args = {"-i": 0, "link": ""}
    arg_parser(input_list[1:], args)

    has_i_flag = "-i" in input_list[1:]
    raw_count = args["-i"] if has_i_flag else args["link"]
    if raw_count in ("", None) or (has_i_flag and raw_count == 0):
        return None if has_i_flag else 1

    raw_count = str(raw_count).strip()
    if not raw_count.isdigit():
        return None
    return int(raw_count)


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
    input_list = (message.text or "").split()
    if len(input_list) > 1 and input_list[1].lower() in {"status", "stats", "health"}:
        await send_filetolink_status(message)
        return

    if not Config.BASE_URL:
        await send_message(message, "BASE_URL is not configured in the bot settings.")
        return
        
    if not message.reply_to_message:
        await send_message(message, "Please reply to a media file to generate links.")
        return
        
    max_batch = max(1, int(Config.MAX_BATCH_FILES or 50))
    batch_count = parse_link_batch_count(message.text)
    if batch_count is None:
        await send_message(message, "Batch count must be a number. Example: /link -i 10")
        return
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
