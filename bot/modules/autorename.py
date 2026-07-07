import os
import time
from pyrogram import ContinuePropagation
from pyrogram.handlers import MessageHandler
from pyrogram.filters import command, private, document, video, audio

from bot import user_data, LOGGER
from bot.core.tg_client import TgClient
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.message_utils import (
    send_message,
    edit_message,
    delete_message,
)
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.ext_utils.bot_utils import update_user_ldata
from bot.helper.ext_utils.status_utils import get_readable_file_size
from bot.core.config_manager import Config

from bot.helper.ext_utils.autorename_utils import apply_autorename_template


def _get_media(message):
    """Extract media object from a Pyrogram message."""
    if not message:
        return None
    for attr in (
        "document",
        "video",
        "audio",
        "photo",
        "voice",
        "animation",
        "video_note",
        "sticker",
    ):
        if media := getattr(message, attr, None):
            return media
    return None


async def autorename_command(client, message):
    """
    /autorename  – Toggle auto-rename mode on/off.

    The rename template itself is managed through the user-settings
    panel (AUTORENAME_TEMPLATE).  This command only flips the
    AUTORENAME_ENABLED flag.
    """
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})
    current_template = user_dict.get("AUTORENAME_TEMPLATE", "")
    is_enabled = user_dict.get("AUTORENAME_ENABLED", False)

    # ── Toggle ──────────────────────────────────────────────────
    new_state = not is_enabled
    update_user_ldata(user_id, "AUTORENAME_ENABLED", new_state)
    await database.update_user_data(user_id)

    status_icon = "✅" if new_state else "❌"
    status_text = "ENABLED" if new_state else "DISABLED"

    msg = (
        "<b>❖ AUTO-RENAME MODE</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"├ Status   : {status_icon} <code>{status_text}</code>\n"
        f"├ Template : <code>{current_template or 'Not Set'}</code>\n"
        "└ Tip      : <i>Set your template from User Settings → Misc Settings → Auto-Rename.</i>"
    )
    await send_message(message, msg)


async def auto_rename_handler(client, message):
    """
    Catch-all handler for private document / video / audio messages.

    When a user has auto-rename mode enabled (AUTORENAME_ENABLED) and a
    valid template (AUTORENAME_TEMPLATE), this handler downloads the
    incoming file, renames it using the template, and re-uploads it —
    exactly mirroring the reference Auto-Rename-Bot behaviour.

    If auto-rename is NOT active, ``ContinuePropagation`` is raised so
    that downstream handlers (e.g. FileToLink) can still process the
    message.
    """
    user_id = message.from_user.id
    user_dict = user_data.get(user_id, {})

    # ── Gate checks ─────────────────────────────────────────────
    if not user_dict.get("AUTORENAME_ENABLED", False):
        raise ContinuePropagation

    template = user_dict.get("AUTORENAME_TEMPLATE", "")
    if not template or template == "None":
        raise ContinuePropagation

    media = _get_media(message)
    if not media:
        raise ContinuePropagation

    # ── Resolve original filename ───────────────────────────────
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
        media_type_name = type(media).__name__.lower()
        ext = ext_map.get(media_type_name, "bin")
        file_name = f"Stream_{message.id}.{ext}"

    # ── Apply template ──────────────────────────────────────────
    new_name = apply_autorename_template(file_name, template)
    if new_name == file_name:
        # Template didn't produce a change — let other handlers run
        raise ContinuePropagation

    # ── Determine upload type ───────────────────────────────────
    if getattr(message, "video", None):
        upload_type = "video"
    elif getattr(message, "audio", None):
        upload_type = "audio"
    else:
        upload_type = "document"

    # ── Download ────────────────────────────────────────────────
    progress_msg = await send_message(
        message, "<i>◷ Downloading file for auto-rename...</i>"
    )

    local_path = None
    downloaded_thumb = False
    thumb_path = f"thumbnails/{user_id}.jpg"
    has_thumb = os.path.exists(thumb_path)
    
    try:
        last_dl_edit = 0

        async def _dl_progress(current, total):
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
                    f"└ Prog : <code>{pct:.1f}%</code> of "
                    f"<code>{get_readable_file_size(total)}</code>",
                )
            except Exception:
                pass

        from bot import DOWNLOAD_DIR
        download_dir = os.path.join(DOWNLOAD_DIR, str(message.id))
        os.makedirs(download_dir, exist_ok=True)

        local_path = await message.download(
            file_name=os.path.join(download_dir, new_name),
            progress=_dl_progress,
        )

        if not local_path or not os.path.exists(local_path):
            raise Exception("Failed to download file.")

        # ── Upload ──────────────────────────────────────────────
        await edit_message(
            progress_msg, "<i>◷ Uploading auto-renamed file...</i>"
        )

        if not has_thumb:
            media = _get_media(message)
            if getattr(media, "thumbs", None):
                thumb_path = await client.download_media(media.thumbs[0].file_id)
                if thumb_path:
                    has_thumb = True
                    downloaded_thumb = True

        # Build caption
        custom_caption = f"<b>File Name:</b> <code>{new_name}</code>"
        user_caption = user_dict.get("LEECH_CAPTION") or (
            Config.LEECH_CAPTION if hasattr(Config, "LEECH_CAPTION") else ""
        )
        if user_caption:
            try:
                custom_caption = user_caption.format(filename=new_name)
            except Exception:
                pass

        last_up_edit = 0

        async def _up_progress(current, total):
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
                    f"└ Prog : <code>{pct:.1f}%</code> of "
                    f"<code>{get_readable_file_size(total)}</code>",
                )
            except Exception:
                pass

        # Extract duration for video/audio
        duration = 0
        if upload_type in ("video", "audio"):
            try:
                from hachoir.metadata import extractMetadata
                from hachoir.parser import createParser

                metadata = extractMetadata(createParser(local_path))
                if metadata and metadata.has("duration"):
                    duration = metadata.get("duration").seconds
            except Exception:
                pass

        if not has_thumb and upload_type == "video":
            from bot.helper.ext_utils.media_utils import get_video_thumbnail
            thumb_path = await get_video_thumbnail(local_path, duration)
            if thumb_path:
                has_thumb = True
                downloaded_thumb = True

        common_kwargs = dict(
            caption=custom_caption,
            thumb=thumb_path if has_thumb else None,
            progress=_up_progress,
        )
        if upload_type in ["video", "audio"]:
            common_kwargs["duration"] = duration
        if upload_type == "video":
            common_kwargs["supports_streaming"] = True

        total_size = os.path.getsize(local_path)
        is_large = total_size > 52428800  # 50 MB
        
        upload_client = client
        use_dump = False
        dump_chat = getattr(Config, "LEECH_DUMP_CHAT", "") or getattr(Config, "BIN_CHANNEL", "")
        
        if is_large and TgClient.user:
            upload_client = TgClient.user
            if dump_chat:
                use_dump = True

        common_kwargs["chat_id"] = dump_chat if use_dump else message.chat.id
        if not use_dump:
            common_kwargs["reply_to_message_id"] = message.id

        if upload_type == "video":
            up_msg = await upload_client.send_video(video=local_path, **common_kwargs)
        elif upload_type == "audio":
            up_msg = await upload_client.send_audio(audio=local_path, **common_kwargs)
        else:
            up_msg = await upload_client.send_document(document=local_path, **common_kwargs)

        if use_dump and up_msg:
            await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=up_msg.chat.id,
                message_id=up_msg.id,
                reply_to_message_id=message.id
            )

        await delete_message(progress_msg)

    except Exception as e:
        LOGGER.error(f"Error auto-renaming file: {e}")
        await edit_message(
            progress_msg,
            f"<b>⚑ ERROR:</b> <i>Failed to auto-rename file. {e}</i>",
        )
    finally:
        if downloaded_thumb and thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)
        if 'download_dir' in locals() and os.path.exists(download_dir):
            import shutil
            shutil.rmtree(download_dir, ignore_errors=True)


# ── Register handlers ───────────────────────────────────────────
TgClient.bot.add_handler(
    MessageHandler(
        autorename_command,
        filters=command(BotCommands.AutoRenameCommand),
    )
)

# Auto-rename file handler sits in group 1 (same tier as filetolink)
# so that it can intercept before group-2 handlers, but after
# command handlers in group 0. Uses ContinuePropagation when inactive.
TgClient.bot.add_handler(
    MessageHandler(
        auto_rename_handler,
        filters=private & (document | video | audio),
    ),
    group=1,
)

