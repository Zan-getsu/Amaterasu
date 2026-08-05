from asyncio import sleep
from contextlib import suppress
from datetime import datetime
from html import escape
from json import loads as json_loads
from math import isfinite
from os import environ
from pathlib import Path
from time import time
from urllib.parse import quote

from pyrogram import ContinuePropagation
from pyrogram.enums import ButtonStyle
from pyrogram.errors import FloodWait
from pyrogram.types import ReplyParameters

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import arg_parser, get_web_secret
from bot.helper.ext_utils.status_utils import (
    get_progress_bar_string,
    get_readable_file_size,
    get_readable_time,
)
from bot.helper.ext_utils.shortener_utils import short_url
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.compat import get_user_mention
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


def _safe_number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return float(default)
    return number if isfinite(number) else float(default)


def _safe_count(value, default=0):
    return max(int(_safe_number(value, default)), 0)


def _read_filetolink_status() -> dict:
    """Read the web worker's atomic runtime snapshot."""
    status_path = Path(
        environ.get(
            "FILETOLINK_STATUS_FILE", "/tmp/amaterasu-filetolink-status.json"
        )
    )
    snapshot = {}
    with suppress(OSError, ValueError, TypeError):
        snapshot = json_loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            snapshot = {}

    cache = snapshot.get("cache") if isinstance(snapshot.get("cache"), dict) else {}
    if "files" not in cache or "bytes" not in cache:
        _, fallback_files, fallback_bytes = _cache_usage()
        cache.setdefault("files", fallback_files)
        cache.setdefault("bytes", fallback_bytes)
    try:
        cache_total_mb = max(int(environ.get("FILETOLINK_CACHE_TOTAL_MAX_MB", "2048")), 0)
    except (TypeError, ValueError):
        cache_total_mb = 2048
    cache.setdefault("max_bytes", cache_total_mb * 1024 * 1024)
    snapshot["cache"] = cache

    updated_at = _safe_number(snapshot.get("updated_at"))
    snapshot["stale"] = not updated_at or time() - updated_at > 10
    snapshot.setdefault("workers", {"ready": 0, "total": 0})
    snapshot.setdefault("transfers", [])
    snapshot.setdefault("active_count", len(snapshot["transfers"]))
    snapshot.setdefault("aggregate_speed", 0)
    return snapshot


def _filetolink_state(snapshot: dict) -> tuple[str, str]:
    if not Config.BASE_URL:
        return "⚪", "Disabled"
    if snapshot.get("stale") or snapshot.get("state") == "stopped":
        return "🔴", "Offline"
    state = str(snapshot.get("state") or "ready").lower()
    if state == "streaming":
        return "🟢", "Streaming"
    if state == "degraded":
        return "🟠", "Degraded"
    return "🟢", "Ready"


def build_filetolink_status(
    sid: int,
    *,
    standalone: bool = False,
    page_no: int = 1,
):
    """Render FileToLink with the same task-card language as /status."""
    snapshot = _read_filetolink_status()
    transfers = snapshot.get("transfers")
    if not isinstance(transfers, list):
        transfers = []
    transfers = sorted(
        (item for item in transfers if isinstance(item, dict)),
        key=lambda item: _safe_number(item.get("started_at")),
    )

    transfer_cards = []
    for index, transfer in enumerate(transfers, start=1):
        name = str(transfer.get("name") or "Unknown file")
        if len(name) > 70:
            name = f"{name[:67]}..."
        total = _safe_count(transfer.get("total"))
        processed = _safe_count(transfer.get("bytes_sent"))
        progress = min(max(_safe_number(transfer.get("progress")), 0), 100)
        mode = "Downloading" if str(transfer.get("mode")).lower() == "download" else "Streaming"
        elapsed = get_readable_time(
            max(time() - _safe_number(transfer.get("started_at"), time()), 0)
        ) or "0s"
        transfer_cards.append(
            f"╭─ ▶ <b>TRANSFER {index:02d}</b> : <b>{escape(name)}</b>\n"
            f"├─ <b>Status</b> : <code>{mode}</code>\n"
            f"├─ <b>Progress</b> : <code>{get_progress_bar_string(progress)} {progress:.1f}%</code>\n"
            f"├─ <b>Processed</b> : <code>{get_readable_file_size(processed)} / {get_readable_file_size(total)}</code>\n"
            f"├─ <b>Speed</b> : <code>↓ {get_readable_file_size(_safe_number(transfer.get('speed')))}/s</code>\n"
            f"├─ <b>Elapsed</b> : <code>◷ {elapsed}</code>\n"
            f"╰─ <b>Source</b> : <code>{escape(str(transfer.get('source') or 'Telegram'))}</code>\n\n"
        )

    state_icon, state_label = _filetolink_state(snapshot)
    workers = snapshot.get("workers") if isinstance(snapshot.get("workers"), dict) else {}
    ready_workers = _safe_count(workers.get("ready"))
    total_workers = _safe_count(workers.get("total"))
    active_count = _safe_count(snapshot.get("active_count"), len(transfers))
    cache = snapshot["cache"]
    cache_files = _safe_count(cache.get("files"))
    cache_bytes = _safe_count(cache.get("bytes"))
    cache_max = _safe_count(cache.get("max_bytes"))
    cache_value = get_readable_file_size(cache_bytes)
    if cache_max:
        cache_value += f" / {get_readable_file_size(cache_max)}"
    cache_value += f" • {cache_files} files"

    metrics = (
        "<b>✦ SERVICE METRICS</b>\n<pre>\n"
        f"┌─ {'State':<9}: {state_icon} {state_label}\n"
        f"├─ {'Transfers':<9}: {active_count} active\n"
        f"├─ {'Workers':<9}: {ready_workers} / {total_workers} ready\n"
        f"├─ {'Speed':<9}: ↓ {get_readable_file_size(_safe_number(snapshot.get('aggregate_speed')))}/s\n"
        f"└─ {'Cache':<9}: {cache_value}\n</pre>"
    )

    # /status is normally a media message, so Telegram applies its caption
    # limit. STATUS_LIMIT remains the maximum number of transfers per page;
    # the secondary budget keeps every page safely below that caption limit.
    status_limit = Config.STATUS_LIMIT if Config.STATUS_LIMIT > 0 else 10
    caption_budget = 820
    base_length = len("<b>✦ FILETOLINK STATUS</b>\n\n") + len(metrics)
    pages = []
    current_page = []
    current_length = base_length
    for card in transfer_cards:
        if current_page and (
            len(current_page) >= status_limit
            or current_length + len(card) > caption_budget
        ):
            pages.append(current_page)
            current_page = []
            current_length = base_length
        current_page.append(card)
        current_length += len(card)
    if current_page or not pages:
        pages.append(current_page)

    page_count = len(pages)
    page_no = min(max(int(page_no or 1), 1), page_count)
    text = "<b>✦ FILETOLINK STATUS</b>\n\n"
    if pages[page_no - 1]:
        text += "".join(pages[page_no - 1])
    else:
        text += "<i>No active transfers.</i>\n\n"
    text += metrics

    buttons = ButtonMaker()
    buttons.data_button(
        "↻ REFRESH",
        f"status {sid} flp {page_no}",
        position="header",
        style=ButtonStyle.PRIMARY,
    )
    if standalone:
        buttons.data_button("✕ CLOSE", f"status {sid} dismiss", position="header")
    else:
        buttons.data_button("↩ TASKS", f"status {sid} home", position="header")
    if page_count > 1:
        buttons.data_button(
            "❮ PREV",
            f"status {sid} flp {max(page_no - 1, 1)}",
            position="f_body",
        )
        buttons.data_button(
            f"{page_no:02d} / {page_count:02d}",
            f"status {sid} flp {page_no}",
            position="f_body",
        )
        buttons.data_button(
            "NEXT ❯",
            f"status {sid} flp {min(page_no + 1, page_count)}",
            position="f_body",
        )
    return text, buttons.build_menu(h_cols=2, fb_cols=3)


async def send_filetolink_status(message):
    sid = message.chat.id
    text, buttons = build_filetolink_status(sid, standalone=True)
    await send_message(message, text, buttons)


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
    bin_channel = Config.effective_bin_channel()

    async def copy_message(**kwargs):
        copied = await message.copy(
            chat_id=bin_channel,
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
    bin_channel = Config.effective_bin_channel()
    if bin_channel:
        copied = await copy_to_bin(message)
        if not copied:
            raise RuntimeError("Failed to store media in BIN_CHANNEL.")
        media = get_media(copied) or media
        
        user = message.from_user or message.sender_chat
        user_mention = get_user_mention(user)
            
        user_id = user.id
        file_id = getattr(media, "file_unique_id", "Unknown")
        
        reply_text = (
            f"<b>✦ FILETOLINK LOGGER</b>\n<code>"
            f"┌─ {'Requested':<10}: </code>{user_mention}<code>\n"
            f"├─ {'User ID':<10}: {user_id}\n"
            f"└─ {'File ID':<10}: {file_id}</code>"
        )
        
        try:
            await copied.reply(
                reply_text,
                reply_parameters=ReplyParameters(message_id=copied.id),
            )
        except Exception as e:
            LOGGER.error(f"Failed to reply to copied message in BIN_CHANNEL: {e}")
            
        return bin_channel, copied.id, media
    return message.chat.id, message.id, media


def build_caption(title, filename, readable_size, stream_link, download_link):
    title = title.replace("✦ ", "").strip()
    safe_filename = escape(str(filename))
    safe_size = escape(str(readable_size))
    safe_download_text = escape(str(download_link))
    safe_download_href = escape(str(download_link), quote=True)
    safe_stream_text = escape(str(stream_link))
    safe_stream_href = escape(str(stream_link), quote=True)
    caption = (
        f"<b>✦ {title}</b>\n"
        "<i>Your secure media links are ready.</i>\n\n"
        "╭─ <b>FILE DETAILS</b>\n"
        f"├─ <b>Name</b> : <code>{safe_filename}</code>\n"
        f"╰─ <b>Size</b> : <code>{safe_size}</code>\n\n"
        f"<b>⬇️ DOWNLOAD</b>\n<a href=\"{safe_download_href}\">"
        f"{safe_download_text}</a>\n\n"
        f"<b>▶️ STREAM</b>\n<a href=\"{safe_stream_href}\">"
        f"{safe_stream_text}</a>"
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
        
        caption = build_caption(
            "YOUR LINKS ARE READY",
            filename,
            readable_size,
            stream_link,
            download_link,
        )
        
        await edit_message(status_msg, caption, markup)
    except Exception as e:
        LOGGER.error(f"Error in FileToLink processing: {e}")
        await edit_message(
            status_msg,
            f"<b>✦ LINK GENERATION FAILED</b>\n"
            f"<i>{escape(str(e))}</i>",
        )

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
                caption = build_caption(
                    f"BATCH FILE {processed + 1}",
                    filename,
                    readable_size,
                    stream_link,
                    download_link,
                )
                await send_message(message, caption, markup)
                processed += 1
            except Exception as e:
                LOGGER.error(f"Failed to process batch message {msg_id}: {e}")
                failed += 1
                
        await edit_message(status_msg, f"<b>✦ BATCH COMPLETED</b>\n\n<code>┌─ {'Processed':<9} : {processed}\n└─ {'Failed':<9} : {failed}</code>")
    else:
        await process_media_message(client, message, message.reply_to_message)


def _is_automatic_media_candidate(message, *, require_user=False):
    """Reject media generated by Amaterasu or another bot.

    Handler filters provide the first boundary, while this check protects
    direct/internal handler calls and Telegram updates with unusual authorship.
    """
    if not message or getattr(message, "outgoing", False):
        return False

    user = getattr(message, "from_user", None)
    if require_user and user is None:
        return False
    if user and (
        getattr(user, "is_bot", False) or getattr(user, "is_self", False)
    ):
        return False
    return bool(get_media(message))


async def private_media_handler(client, message):
    from bot import user_data
    if not Config.BASE_URL:
        raise ContinuePropagation
    if not _is_automatic_media_candidate(message, require_user=True):
        raise ContinuePropagation

    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})
    if not user_dict.get("AUTO_FILETOLINK", False):
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
    if not (
        Config.BASE_URL
        and Config.CHANNEL
        and _is_automatic_media_candidate(message)
    ):
        raise ContinuePropagation
    bin_channel = Config.effective_bin_channel()
    if bin_channel and message.chat and message.chat.id == int(bin_channel):
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
