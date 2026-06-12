# ruff: noqa: E402

import faulthandler
from sys import stderr
from logging import FileHandler, getLogger

faulthandler.enable(file=stderr, all_threads=True)

from .core.config_manager import Config

Config.load()

from datetime import datetime
from logging import Formatter
from time import localtime

from pytz import timezone

from . import LOGGER, bot_loop

for _h in getLogger().handlers:
    if isinstance(_h, FileHandler):
        try:
            faulthandler.enable(file=_h.stream.fileno(), all_threads=True)
        except Exception:
            pass
        break
from .core.tg_client import TgClient


async def main():
    from asyncio import gather

    from .core.startup import (
        load_configurations,
        load_settings,
        save_settings,
        update_aria2_options,
        update_nzb_options,
        update_qb_options,
        update_variables,
    )

    await load_settings()

    from bot import _sabnzbd_key, _update_sabnzbd_ini, sabnzbd_client
    derived_key = _sabnzbd_key()
    _update_sabnzbd_ini(derived_key)
    sabnzbd_client._default_params["apikey"] = derived_key
    from .helper.ext_utils.db_handler import database
    await database.update_nzb_config()

    from .helper.telegram_helper.bot_commands import BotCommands

    BotCommands.refresh_commands()

    try:
        tz = timezone(Config.TIMEZONE)
    except Exception:
        from pytz import utc

        tz = utc

    def changetz(*args):
        try:
            return datetime.now(tz).timetuple()
        except Exception:
            return localtime()

    Formatter.converter = changetz

    await gather(
        TgClient.start_bot(),
        TgClient.start_user(),
        TgClient.start_helper_bots(),
        TgClient.start_helper_users(),
    )
    await TgClient.start_stream_clients()
    await gather(load_configurations(), update_variables())

    from .core.torrent_manager import TorrentManager

    await TorrentManager.initiate()
    await gather(
        update_qb_options(),
        update_aria2_options(),
        update_nzb_options(),
    )
    from .core.jdownloader_booter import jdownloader
    from .helper.ext_utils.bot_utils import search_images
    from .helper.ext_utils.files_utils import clean_all
    from .helper.ext_utils.telegraph_helper import telegraph
    from .helper.mirror_leech_utils.rclone_utils.serve import rclone_serve_booter
    from .modules import (
        get_packages_version,
        initiate_search_tools,
    )

    await gather(
        save_settings(),
        jdownloader.boot(),
        clean_all(),
        initiate_search_tools(),
        get_packages_version(),
        telegraph.create_account(),
        rclone_serve_booter(),
    )
    bot_loop.create_task(search_images())


bot_loop.run_until_complete(main())


def _handle_asyncio_exception(loop, context):
    exc = context.get("exception")
    if exc and isinstance(exc, (KeyError, ValueError)):
        msg = str(exc)
        msg_lower = msg.lower()
        if "unknown constructor" in msg_lower or "server sent an unknown" in msg_lower:
            LOGGER.warning(f"Pyrogram schema mismatch (tg side): {msg}")
            return
    loop.default_exception_handler(context)


bot_loop.set_exception_handler(_handle_asyncio_exception)

from .core.handlers import add_handlers
from .helper.ext_utils.bot_utils import create_help_buttons
from .helper.listeners.aria2_listener import add_aria2_callbacks

add_aria2_callbacks()
create_help_buttons()
add_handlers()

from .modules import restart_notification

bot_loop.run_until_complete(restart_notification())

from .core.plugin_manager import get_plugin_manager
from .modules.plugin_manager import register_plugin_commands

plugin_manager = get_plugin_manager()
plugin_manager.bot = TgClient.bot
register_plugin_commands()

from pyrogram.filters import regex
from pyrogram.handlers import CallbackQueryHandler

from .core.handlers import add_handlers
from .helper.ext_utils.bot_utils import new_task
from .helper.telegram_helper.filters import CustomFilters
from .helper.telegram_helper.message_utils import (
    delete_message,
    edit_message,
    send_message,
)


@new_task
async def restart_sessions_confirm(_, query):
    data = query.data.split()
    message = query.message
    if data[1] == "confirm":
        reply_to = message.reply_to_message
        restart_message = await send_message(reply_to, "Restarting Session(s)...")
        await delete_message(message)
        await TgClient.reload()
        add_handlers()
        TgClient.bot.add_handler(
            CallbackQueryHandler(
                restart_sessions_confirm,
                filters=regex("^sessionrestart") & CustomFilters.sudo,
            )
        )
        await edit_message(restart_message, "Session(s) Restarted Successfully!")
    else:
        await delete_message(message)


TgClient.bot.add_handler(
    CallbackQueryHandler(
        restart_sessions_confirm,
        filters=regex("^sessionrestart") & CustomFilters.sudo,
    )
)

from .helper.ext_utils.bot_utils import derive_service_password

_bot_id = (Config.BOT_TOKEN or "").split(":", 1)[0] or "0"
qbit_pwd = derive_service_password(_bot_id, "qbit")
nzb_pwd = derive_service_password(_bot_id, "sabnzbd")
LOGGER.info(f"Web UI: qBittorrent: /qbit/?pass={qbit_pwd}")
LOGGER.info(f"Web UI: SABnzbd: /nzb/?pass={nzb_pwd}")

LOGGER.info("Amaterasu Client(s) & Services Started !")
bot_loop.run_forever()
