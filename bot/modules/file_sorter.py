from asyncio import Lock, sleep

from pyrogram import ContinuePropagation
from pyrogram.errors import FloodWait
from pyrogram.filters import (
    animation,
    audio,
    command,
    document,
    photo,
    sticker,
    video,
    video_note,
    voice,
)
from pyrogram.handlers import MessageHandler

from bot.core.tg_client import TgClient
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.message_utils import edit_message, send_message


sort_sessions = {}
sort_lock = Lock()


def _sort_command_text():
    cmd = BotCommands.SortCommand
    if isinstance(cmd, list):
        cmd = cmd[0]
    return f"/{cmd}"


def _session_key(message):
    user = message.from_user or message.sender_chat
    thread_id = message.message_thread_id if message.is_topic_message else None
    return message.chat.id, user.id, thread_id


def _get_media_entry(message):
    for media_type, fallback_ext in (
        ("document", "bin"),
        ("video", "mp4"),
        ("audio", "mp3"),
        ("photo", "jpg"),
        ("voice", "ogg"),
        ("animation", "mp4"),
        ("video_note", "mp4"),
        ("sticker", "webp"),
    ):
        media = getattr(message, media_type, None)
        if not media:
            continue

        file_name = getattr(media, "file_name", None)
        if not file_name and media_type == "audio":
            file_name = getattr(media, "title", None)
        if not file_name:
            file_name = f"{media_type.title()}_{message.id}.{fallback_ext}"

        return {
            "caption": message.caption,
            "caption_entities": message.caption_entities,
            "file_id": media.file_id,
            "file_name": file_name,
            "file_size": getattr(media, "file_size", 0) or 0,
            "media_type": media_type,
            "message_id": message.id,
        }

    return None


async def _send_cached_file(client, message, entry):
    kwargs = {
        "chat_id": message.chat.id,
        "disable_notification": True,
    }
    if message.is_topic_message:
        kwargs["message_thread_id"] = message.message_thread_id
    if entry["caption"]:
        kwargs["caption"] = entry["caption"]
        if entry["caption_entities"]:
            kwargs["caption_entities"] = entry["caption_entities"]

    file_id = entry["file_id"]
    media_type = entry["media_type"]

    try:
        if media_type == "photo":
            return await client.send_photo(photo=file_id, **kwargs)
        if media_type == "video":
            return await client.send_video(
                video=file_id,
                supports_streaming=True,
                **kwargs,
            )
        if media_type == "audio":
            return await client.send_audio(audio=file_id, **kwargs)
        if media_type == "voice":
            return await client.send_voice(voice=file_id, **kwargs)
        if media_type == "animation":
            return await client.send_animation(
                animation=file_id,
                **kwargs,
            )
        if media_type == "video_note":
            return await client.send_video_note(video_note=file_id, **kwargs)
        if media_type == "sticker":
            return await client.send_sticker(sticker=file_id, **kwargs)

        return await client.send_document(
            document=file_id,
            **kwargs,
        )
    except FloodWait as flood:
        await sleep(flood.value * 1.2)
        return await _send_cached_file(client, message, entry)


async def sort_command(client, message):
    key = _session_key(message)

    async with sort_lock:
        session = sort_sessions.pop(key, None)
        if session is None:
            sort_sessions[key] = {"files": []}
            session = None

    if session is None:
        sort_cmd = _sort_command_text()
        await send_message(
            message,
            "<b>❖ SORT MODE ENABLED</b>\n"
            f"Send files now. Send <code>{sort_cmd}</code> again when you want them returned alphabetically.",
        )
        return

    files = session["files"]
    if not files:
        await send_message(
            message,
            "<b>❖ SORT MODE DISABLED</b>\n"
            "No files were cached for sorting.",
        )
        return

    status_msg = await send_message(
        message,
        f"<i>◷ Sorting and resending {len(files)} cached file(s)...</i>",
    )

    sent = 0
    failed = 0
    sorted_files = sorted(
        files,
        key=lambda item: (item["file_name"].casefold(), item["message_id"]),
    )

    for entry in sorted_files:
        try:
            await _send_cached_file(client, message, entry)
            sent += 1
        except Exception:
            failed += 1

    await edit_message(
        status_msg,
        "<b>❖ SORT MODE DISABLED</b>\n"
        "Cached files were sorted by file name and resent using Telegram file IDs.\n"
        f"├ Sent   : <code>{sent}</code>\n"
        f"└ Failed : <code>{failed}</code>",
    )


async def sort_media_handler(client, message):
    key = _session_key(message)
    entry = _get_media_entry(message)
    if entry is None:
        raise ContinuePropagation

    async with sort_lock:
        session = sort_sessions.get(key)
        if session is None:
            raise ContinuePropagation

        session["files"].append(entry)
        count = len(session["files"])

    if count == 1 or count % 10 == 0:
        sort_cmd = _sort_command_text()
        await send_message(
            message,
            f"<b>❖ SORT CACHE</b>\n"
            f"Cached <code>{count}</code> file(s). Send <code>{sort_cmd}</code> again to deliver.",
        )


TgClient.bot.add_handler(
    MessageHandler(
        sort_command,
        filters=command(BotCommands.SortCommand, case_sensitive=True),
    )
)

TgClient.bot.add_handler(
    MessageHandler(
        sort_media_handler,
        filters=document
        | video
        | audio
        | photo
        | voice
        | animation
        | video_note
        | sticker,
    ),
    group=0,
)
