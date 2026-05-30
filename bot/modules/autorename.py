import os
import time
import logging

from pyrogram import ContinuePropagation
from pyrogram.handlers import MessageHandler
from pyrogram.filters import command, private, document, video, audio
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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

        download_dir = "downloads"
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

        thumb_path = f"thumbnails/{user_id}.jpg"
        has_thumb = os.path.exists(thumb_path)

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

        common_kwargs = dict(
            chat_id=message.chat.id,
            caption=custom_caption,
            thumb=thumb_path if has_thumb else None,
            reply_to_message_id=message.id,
            progress=_up_progress,
        )

        if upload_type == "video":
            await client.send_video(
                video=local_path,
                supports_streaming=True,
                duration=duration,
                **common_kwargs,
            )
        elif upload_type == "audio":
            await client.send_audio(
                audio=local_path,
                duration=duration,
                **common_kwargs,
            )
        else:
            await client.send_document(
                document=local_path,
                **common_kwargs,
            )

        await delete_message(progress_msg)

    except Exception as e:
        LOGGER.error(f"Error auto-renaming file: {e}")
        await edit_message(
            progress_msg,
            f"<b>⚑ ERROR:</b> <i>Failed to auto-rename file. {e}</i>",
        )
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)


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
