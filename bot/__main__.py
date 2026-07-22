# ruff: noqa: E402

import sys
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
from .helper.ext_utils.crash_reporter import (
    send_unhandled_exception,
    send_async_exception,
)

sys.excepthook = send_unhandled_exception

_clean_task = None

STARTUP_BANNER = r"""
╔════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                            ║
║      █████╗ ███╗   ███╗███████╗████████╗███████╗██████╗  █████╗ ███████╗██╗   ██╗          ║
║     ██╔══██╗████╗ ████║██╔════╝╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║   ██║          ║
║     ███████║██╔████╔██║█████╗     ██║   █████╗  ██████╔╝███████║███████╗██║   ██║          ║
║     ██╔══██║██║╚██╔╝██║██╔══╝     ██║   ██╔══╝  ██╔══██╗██╔══██║╚════██║██║   ██║          ║
║     ██║  ██║██║ ╚═╝ ██║███████╗   ██║   ███████╗██║  ██║██║  ██║███████║╚██████╔╝          ║
║     ╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚══════╝ ╚═════╝              ║
║                                                                                            ║
║                              ────  Amaterasu  ────                                         ║
║                                 The Black Sun                                              ║
║                                                                                            ║
╚════════════════════════════════════════════════════════════════════════════════════════════╝
""".strip()


async def main():
    LOGGER.info("\n%s", STARTUP_BANNER)

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

    if not Config.DISABLE_NZB:
        from bot import _sabnzbd_key, _update_sabnzbd_ini, sabnzbd_client

        derived_key = _sabnzbd_key()
        patched_ok = _update_sabnzbd_ini(derived_key)
        if not patched_ok:
            # Refuse to start SABnzbd with default credentials. Disable
            # the NZB engine for this boot and warn loudly.
            LOGGER.error(
                "SABnzbd.ini patching failed — disabling NZB engine for "
                "this boot. Set DISABLE_NZB=True to silence, or fix the "
                "ini file (see logs above)."
            )
            Config.DISABLE_NZB = True
        else:
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

    # Start the MAIN bot in the foreground — it's required for handlers
    # to register and for the bot to function. Block until it's up
    # (with FloodWait retries inside start_bot).
    await TgClient.start_bot()

    # Start the user session, helper bots, and helper users in the
    # BACKGROUND (non-blocking) by default. Provisioning stream bots first
    # tries to establish the user session, but never prevents the main bot
    # from starting if that optional setup cannot run.
    # We use create_tracked_task (which wraps bot_loop.create_task)
    # so failures are logged instead of silently dropped.
    from .helper.ext_utils.bot_utils import create_tracked_task as _ctt
    provision_stream_bots = False
    if Config.AUTO_PROVISION_STREAM_BOTS:
        if not Config.USER_SESSION_STRING:
            LOGGER.warning(
                "AUTO_PROVISION_STREAM_BOTS requires USER_SESSION_STRING. "
                "Skipping stream-bot provisioning for this boot."
            )
        else:
            await TgClient.start_user()
            if TgClient.user is None:
                LOGGER.warning(
                    "AUTO_PROVISION_STREAM_BOTS could not start "
                    "USER_SESSION_STRING. Skipping stream-bot provisioning "
                    "for this boot."
                )
            else:
                provision_stream_bots = True
    else:
        _ctt(TgClient.start_user())
    _ctt(TgClient.start_helper_bots())
    _ctt(TgClient.start_helper_users())

    # Stream clients (MULTI_TOKEN bots) are used for load-balanced file
    # streaming and are managed by the web server (gunicorn) subprocess.
    # The main bot process only needs them temporarily if
    # AUTO_PROVISION_STREAM_BOTS is enabled (to add bots to storage chats).
    if provision_stream_bots:
        await TgClient.start_stream_clients()
        try:
            await TgClient.provision_stream_bots()
        except Exception as e:
            LOGGER.error(
                "AUTO_PROVISION_STREAM_BOTS failed; continuing normal startup: %s",
                e,
            )
        # Provisioning done — stop the stream clients in this process.
        # The web server subprocess starts its own set for actual streaming.
        for cid, client in list(TgClient.stream_clients.items()):
            if cid != 0:
                try:
                    await client.stop()
                except Exception:
                    pass
        TgClient.stream_clients = {}
        TgClient.stream_loads = {}
    await gather(load_configurations(), update_variables())

    await gather(
        update_qb_options(),
        update_aria2_options(),
        update_nzb_options(),
    )
    from .core.jdownloader_booter import jdownloader
    from .helper.ext_utils.bot_utils import create_tracked_task, git_info, search_images
    from .helper.ext_utils.files_utils import clean_all
    from .helper.ext_utils.telegraph_helper import telegraph
    from .helper.mirror_leech_utils.rclone_utils.serve import rclone_serve_booter
    from .modules import (
        get_packages_version,
        initiate_search_tools,
    )

    await save_settings()
    await git_info.init()
    if not Config.DISABLE_JD:
        create_tracked_task(jdownloader.boot())
    global _clean_task
    _clean_task = bot_loop.create_task(clean_all())
    create_tracked_task(initiate_search_tools())
    create_tracked_task(get_packages_version())
    create_tracked_task(telegraph.create_account())
    create_tracked_task(rclone_serve_booter())
    create_tracked_task(search_images())
    # Phase 1.7 — start tunnel monitor for Cloudflare quick tunnel URL
    # persistence. Watches /data/tunnel_url.txt and propagates new URLs
    # to Config.BASE_URL, MongoDB, and owner DM.
    from .helper.ext_utils.tunnel_monitor import start_tunnel_monitor
    create_tracked_task(start_tunnel_monitor())
    # Phase 2.9 — start engine health checker. Checks aria2, qbit,
    # SABnzbd, JDownloader every 5 minutes. Notifies owner on
    # HEALTHY → UNAVAILABLE and UNAVAILABLE → HEALTHY transitions.
    from .helper.ext_utils.engine_health import start_engine_health_checker
    create_tracked_task(start_engine_health_checker())
    # Phase 3.1 — detect FFmpeg hardware acceleration at startup so the
    # first encode doesn't pay the probe cost. Logs the detected encoder.
    from .helper.ext_utils.hwaccel import init_hwaccel_detection
    create_tracked_task(init_hwaccel_detection())


try:
    bot_loop.run_until_complete(main())
except Exception:
    try:
        bot_loop.run_until_complete(TgClient.stop())
    except Exception as stop_error:
        LOGGER.error(f"Failed to stop Telegram clients after startup error: {stop_error}")
    raise


def _handle_asyncio_exception(loop, context):
    exc = context.get("exception")
    if exc and isinstance(exc, (KeyError, ValueError)):
        msg = str(exc)
        msg_lower = msg.lower()
        if "unknown constructor" in msg_lower or "server sent an unknown" in msg_lower:
            LOGGER.warning(f"Pyrogram schema mismatch (tg side): {msg}")
            return
    send_async_exception(context)
    loop.default_exception_handler(context)


bot_loop.set_exception_handler(_handle_asyncio_exception)

from .core.handlers import add_handlers
from .helper.ext_utils.bot_utils import create_help_buttons
from .helper.listeners.aria2_listener import add_aria2_callbacks

add_aria2_callbacks()
create_help_buttons()
bot_loop.run_until_complete(add_handlers())

from .modules import restart_notification

if _clean_task is not None:
    try:
        bot_loop.run_until_complete(_clean_task)
    except Exception as e:
        LOGGER.error(f"clean_all error: {e}")
try:
    bot_loop.run_until_complete(restart_notification())
except Exception as e:
    LOGGER.error(f"restart_notification error: {e}")

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
        await add_handlers()
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

LOGGER.info("Web UI: qBittorrent available at /qbit/")
LOGGER.info("Web UI: SABnzbd available at /nzb/")

# --- Graceful shutdown -------------------------------------------------
# Install signal handlers so SIGTERM/SIGINT trigger a clean shutdown
# instead of being dropped (Pyrogram's run_forever ignores them by default).
# The shutdown sequence:
#   1. Stop accepting new Telegram updates (TgClient.stop)
#   2. Cancel pending status-update intervals
#   3. Persist Config to MongoDB (so next boot picks up where we left off)
#   4. Close MongoDB connection
#   5. Close httpx AsyncClient singletons (if any)
# Download daemons (aria2, qBittorrent, SABnzbd, JD) are NOT paused —
# they continue in their own processes and resume on next boot via
# INCOMPLETE_TASK_NOTIFIER.
import signal
import asyncio as _asyncio

_shutdown_event = _asyncio.Event()


def _signal_handler(signum, _frame):
    LOGGER.info(f"Received signal {signum} ({signal.Signals(signum).name}), "
                "initiating graceful shutdown...")
    _shutdown_event.set()


def _install_signal_handlers():
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            bot_loop.add_signal_handler(sig, _signal_handler, sig)
        except (NotImplementedError, RuntimeError):
            # add_signal_handler is not available on Windows — fall back
            # to the default KeyboardInterrupt behavior.
            signal.signal(sig, _signal_handler)


async def _graceful_shutdown():
    LOGGER.info("Shutdown: stopping Telegram clients...")
    try:
        await TgClient.stop()
    except Exception as e:
        LOGGER.error(f"Shutdown: TgClient.stop error: {e}")

    LOGGER.info("Shutdown: cancelling status intervals...")
    try:
        from . import intervals
        for interval in intervals.get("status", {}).values():
            if hasattr(interval, "cancel"):
                try:
                    interval.cancel()
                except Exception:
                    pass
    except Exception as e:
        LOGGER.error(f"Shutdown: interval cancel error: {e}")

    LOGGER.info("Shutdown: persisting Config to MongoDB...")
    try:
        from .helper.ext_utils.db_handler import database
        if database.db is not None:
            await database.update_config(Config.get_all())
            await database.disconnect()
    except Exception as e:
        LOGGER.error(f"Shutdown: config persist error: {e}")

    LOGGER.info("Shutdown complete.")


_install_signal_handlers()
LOGGER.info("Amaterasu Client(s) & Services Started !")

# Run forever, but wake up when a shutdown signal arrives so we can
# drain cleanly before the process exits.
async def _main_loop():
    await _shutdown_event.wait()
    await _graceful_shutdown()


try:
    bot_loop.run_until_complete(_main_loop())
except (KeyboardInterrupt, SystemExit):
    LOGGER.info("Hard interrupt received, exiting.")
    bot_loop.run_until_complete(_graceful_shutdown())
