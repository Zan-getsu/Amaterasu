"""Phase 1.7 — Cloudflare tunnel URL persistence monitor.

Watches /data/tunnel_url.txt for changes. When the tunnel service
(docker-compose `tunnel` container) writes a new quick-tunnel URL,
this module:
  1. Updates Config.BASE_URL to the new tunnel URL.
  2. Persists the new URL to MongoDB (settings.config).
  3. Sends the new URL to the owner via Telegram DM.

The tunnel service writes the URL once at startup; this monitor catches
the write and propagates it. If the tunnel rotates (restart), the
monitor catches the new URL and re-propagates.

This runs as a background task started from bot/__main__.py after the
bot is online. It polls /data/tunnel_url.txt every 10 seconds — light
enough to not waste CPU, fast enough to catch a new URL within seconds
of tunnel startup.
"""

from asyncio import sleep
from os import environ
from pathlib import Path

from ... import LOGGER
from ...core.config_manager import Config

_TUNNEL_URL_FILE = Path(environ.get("TUNNEL_URL_FILE", "/data/tunnel_url.txt"))
_POLL_INTERVAL = 10  # seconds
_last_url = None


async def _read_tunnel_url():
    """Read the tunnel URL from the shared volume file. Returns None if
    the file doesn't exist or is empty."""
    try:
        if not _TUNNEL_URL_FILE.exists():
            return None
        text = _TUNNEL_URL_FILE.read_text(encoding="utf-8").strip()
        if not text or not text.startswith("http"):
            return None
        return text.rstrip("/")
    except Exception as e:
        LOGGER.warning(f"tunnel_monitor: error reading {_TUNNEL_URL_FILE}: {e}")
        return None


async def _propagate_url(url):
    """Propagate the new tunnel URL to Config, MongoDB, and owner DM."""
    global _last_url
    if url == _last_url:
        return  # no change
    _last_url = url
    LOGGER.info(f"Tunnel URL detected: {url}")
    # Update Config.BASE_URL so FileToLink and other routes use the tunnel
    Config.BASE_URL = url
    Config.FQDN = url.split("://", 1)[-1].split(":")[0] if "://" in url else ""
    Config.HAS_SSL = url.startswith("https://")
    Config.NO_PORT = True
    # Persist to MongoDB so it survives restart
    try:
        from .db_handler import database
        if database.db is not None:
            await database.update_config({
                "BASE_URL": url,
                "FQDN": Config.FQDN,
                "HAS_SSL": Config.HAS_SSL,
                "NO_PORT": Config.NO_PORT,
            })
            LOGGER.info(f"Tunnel URL persisted to MongoDB: {url}")
    except Exception as e:
        LOGGER.warning(f"Tunnel URL persist to MongoDB: {e}")
    # DM the owner with the new URL
    try:
        from ...core.tg_client import TgClient
        from ...helper.telegram_helper.message_utils import send_message
        if TgClient.bot and Config.OWNER_ID:
            await TgClient.bot.send_message(
                Config.OWNER_ID,
                f"<b>Cloudflare Tunnel URL</b>\n"
                f"<code>{url}</code>\n\n"
                f"This URL is now active for FileToLink streaming and the web UI. "
                f"It will rotate on every tunnel restart — this message will be "
                f"sent again with the new URL after each rotation.",
            )
    except Exception as e:
        LOGGER.warning(f"Tunnel URL owner DM: {e}")


async def tunnel_monitor_loop():
    """Background loop that polls /data/tunnel_url.txt for changes.
    Started from bot/__main__.py after the bot is online."""
    LOGGER.info(
        f"tunnel_monitor: watching {_TUNNEL_URL_FILE} for Cloudflare URL changes"
    )
    # Wait a bit for the tunnel service to start and write the URL
    await sleep(15)
    while True:
        try:
            url = await _read_tunnel_url()
            if url and url != _last_url:
                await _propagate_url(url)
        except Exception as e:
            LOGGER.warning(f"tunnel_monitor loop error: {e}")
        await sleep(_POLL_INTERVAL)


async def start_tunnel_monitor():
    """Entry point — called from bot/__main__.py as a background task."""
    from .bot_utils import create_tracked_task
    create_tracked_task(tunnel_monitor_loop())
