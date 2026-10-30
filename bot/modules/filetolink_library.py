"""Owner/sudo channel indexing and private, expiring catalog links."""

from asyncio import Event, Lock, create_task
from html import escape
from time import monotonic
from urllib.parse import urlencode

from pyrogram.enums import ChatType

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import get_web_secret
from bot.helper.ext_utils.db_handler import database
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import edit_message, send_message
from web.media_library import MediaLibrary, channel_target
from web.security import make_signed_token

_lock = Lock()
_stop = Event()
_scan = None


async def library_command(client, message, parts):
    global _scan
    if message.chat.type != ChatType.PRIVATE or not await CustomFilters.sudo(client, message):
        await send_message(
            message,
            "Media library commands are available to the owner and sudo users in private chat.",
        )
        return
    if not Config.BASE_URL or database.db is None:
        await send_message(
            message,
            "Configure BASE_URL and a reachable DATABASE_URL before using the media library.",
        )
        return
    command = parts[1].lower()
    if command == "library":
        user_id = message.from_user.id
        token = make_signed_token(get_web_secret(), "media-library", user_id, ttl=3600)
        url = (
            f"{Config.BASE_URL.rstrip('/')}/library?{urlencode(dict(user_id=user_id, token=token))}"
        )
        buttons = ButtonMaker()
        buttons.url_button("OPEN MEDIA LIBRARY", url)
        await send_message(
            message,
            "Your private library link expires in one hour. Anyone holding it can browse the indexed files.",
            buttons.build_menu(1),
        )
        return
    if command == "cancelindex":
        _stop.set()
        await send_message(message, "Stop requested. Indexed files and scan progress are retained.")
        return
    async with _lock:
        if _scan and not _scan.done():
            await send_message(message, "A scan is running. Use /link cancelindex to stop it.")
            return
        try:
            target, end = channel_target(parts[2] if len(parts) > 2 else "")
            chat = await client.get_chat(target)
            from bot.helper.telegram_helper.tg_utils import get_media
            from bot.modules.filetolink import _blocked_channel_ids, get_filename

            if (
                chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP)
                or chat.id in _blocked_channel_ids()
            ):
                raise ValueError("Choose an accessible channel that is not banned.")
            library = MediaLibrary(
                database.filetolink_collection("library"), database.filetolink_collection("scans")
            )
            await library.ensure_indexes()
        except Exception as exc:
            await send_message(message, f"Cannot start indexing: {escape(str(exc))}")
            return
        status = await send_message(
            message,
            "Indexing channel media. Use /link cancelindex to stop; repeat the same command to resume.",
        )
        _stop.clear()
        last_report = 0

        def describe(msg):
            media = get_media(msg)
            if media is None or not getattr(media, "file_size", 0):
                return None
            return dict(
                name=get_filename(msg, media),
                size=media.file_size,
                unique_id=getattr(media, "file_unique_id", ""),
                mime=getattr(media, "mime_type", "") or "application/octet-stream",
            )

        async def report(last, total, count):
            nonlocal last_report
            if monotonic() - last_report < 10 and last < total:
                return
            last_report = monotonic()
            try:
                await edit_message(
                    status,
                    f"Channel indexing: {last}/{total} message IDs checked · {count} media files processed.",
                )
            except Exception as exc:
                LOGGER.debug("Channel scan progress update failed (%s).", type(exc).__name__)

        async def run():
            try:
                last, count = await library.scan(
                    client, chat.id, end, _stop, describe, report, rescan="rescan" in parts[3:]
                )
                await edit_message(
                    status,
                    f"{'Stopped' if _stop.is_set() else 'Index complete'} at {last}/{end}. {count} media files processed.\nOpen /link library to browse.",
                )
            except Exception as exc:
                LOGGER.warning("Media library scan stopped: %s", type(exc).__name__)
                await edit_message(
                    status,
                    "Indexing stopped because Telegram or the database was unavailable. Repeat the command to resume saved progress.",
                )

        _scan = create_task(run())
