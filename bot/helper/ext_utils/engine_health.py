"""Phase 2.9 — Engine health checks.

Periodically (every 5 minutes) checks the health of aria2, qBittorrent,
SABnzbd, JDownloader. Tracks state: HEALTHY, DEGRADED, UNAVAILABLE.

On state change:
  - Logs at WARNING level.
  - Sends a Telegram message to the owner ONLY on HEALTHY → UNAVAILABLE
    and UNAVAILABLE → HEALTHY transitions (not for every flap).

engine_selector.py reads this state before dispatching. If an engine
is UNAVAILABLE, it's skipped in the fallback chain.

Integrates with /healthz endpoint — the UNAVAILABLE count is included
in the healthz response.
"""

from asyncio import sleep, create_task
from logging import getLogger
from time import time

LOGGER = getLogger(__name__)

# Engine health states
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
UNAVAILABLE = "UNAVAILABLE"

# Current state: {engine_name: {"state": str, "last_check": float, "last_change": float}}
_engine_states = {}

# Owner DM sent for this transition? Avoid spamming on every flap.
# Reset to False when state changes back to HEALTHY.
_owner_notified_unavailable = set()

_CHECK_INTERVAL = 300  # 5 minutes


async def _check_aria2():
    """Check aria2 RPC health. Returns (state, detail)."""
    try:
        from ...core.config_manager import Config
        from ...core.torrent_manager import TorrentManager

        if Config.DISABLE_TORRENTS:
            return HEALTHY, "torrents disabled"
        if TorrentManager.aria2 is None:
            return UNAVAILABLE, "aria2 client is not connected"
        # Reuse the configured WebSocket client. Aria2HttpClient does not
        # accept the ``secret`` argument in the bundled aioaria2 version.
        version = await TorrentManager.aria2.getVersion()
        return HEALTHY, f"aria2 {version.get('version', '?')}"
    except Exception as e:
        return UNAVAILABLE, str(e)


async def _check_qbit():
    """Check qBittorrent health. Returns (state, detail)."""
    try:
        from ...core.config_manager import Config
        from ...core.torrent_manager import TorrentManager

        if Config.DISABLE_TORRENTS:
            return HEALTHY, "torrents disabled"
        if TorrentManager.qbittorrent is None:
            return UNAVAILABLE, "qBittorrent client is not connected"
        # The active client is already authenticated against /api/v2/.
        version = await TorrentManager.qbittorrent.app.version()
        return HEALTHY, f"qBittorrent {version}"
    except Exception as e:
        return UNAVAILABLE, str(e)


async def _check_sabnzbd():
    """Check SABnzbd health. Returns (state, detail)."""
    try:
        from ... import sabnzbd_client
        from ...core.config_manager import Config
        if Config.DISABLE_NZB:
            return HEALTHY, "NZB disabled"
        await sabnzbd_client.get_config()
        return HEALTHY, "SABnzbd OK"
    except Exception as e:
        return UNAVAILABLE, str(e)


async def _check_jd():
    """Check JDownloader health. Returns (state, detail)."""
    try:
        from ...core.config_manager import Config
        if Config.DISABLE_JD:
            return HEALTHY, "JD disabled"
        # JD doesn't have a simple health endpoint — check if myjd
        # client is connected. If the booter hasn't run, it's unavailable.
        from ...core.jdownloader_booter import jdownloader
        if jdownloader and getattr(jdownloader, "_device", None):
            return HEALTHY, "JDownloader connected"
        return DEGRADED, "JDownloader not connected"
    except Exception as e:
        return UNAVAILABLE, str(e)


_CHECKS = {
    "aria2": _check_aria2,
    "qbit": _check_qbit,
    "sabnzbd": _check_sabnzbd,
    "jd": _check_jd,
}


async def _check_all_engines():
    """Run all health checks and update _engine_states."""
    for name, check_fn in _CHECKS.items():
        try:
            state, detail = await check_fn()
        except Exception as e:
            state, detail = UNAVAILABLE, f"check error: {e}"
        old_state = _engine_states.get(name, {}).get("state", HEALTHY)
        now = time()
        if state != old_state:
            _engine_states[name] = {
                "state": state,
                "detail": detail,
                "last_check": now,
                "last_change": now,
            }
            LOGGER.warning(
                f"Engine {name} state changed: {old_state} → {state} ({detail})"
            )
            # Notify owner on HEALTHY → UNAVAILABLE and UNAVAILABLE → HEALTHY
            if state == UNAVAILABLE and name not in _owner_notified_unavailable:
                await _notify_owner(
                    f"⚠️ Engine {name} is now UNAVAILABLE: {detail}"
                )
                _owner_notified_unavailable.add(name)
            elif state == HEALTHY and name in _owner_notified_unavailable:
                await _notify_owner(f"✅ Engine {name} is back to HEALTHY: {detail}")
                _owner_notified_unavailable.discard(name)
        else:
            _engine_states[name] = {
                "state": state,
                "detail": detail,
                "last_check": now,
                "last_change": _engine_states.get(name, {}).get("last_change", now),
            }


async def _notify_owner(message):
    """Send a DM to the owner about engine state change."""
    try:
        from ...core.tg_client import TgClient
        from ...core.config_manager import Config
        if TgClient.bot and Config.OWNER_ID:
            await TgClient.bot.send_message(Config.OWNER_ID, message)
    except Exception as e:
        LOGGER.warning(f"Failed to notify owner of engine state change: {e}")


def get_health_states():
    """Return a snapshot of engine health states.

    Returns dict: {engine_name: "HEALTHY"|"DEGRADED"|"UNAVAILABLE"}
    """
    return {name: info.get("state", HEALTHY) for name, info in _engine_states.items()}


def get_health_detail():
    """Return full health state with details (for /healthz endpoint)."""
    return {
        name: {
            "state": info.get("state", HEALTHY),
            "detail": info.get("detail", ""),
            "last_check": info.get("last_check", 0),
            "last_change": info.get("last_change", 0),
        }
        for name, info in _engine_states.items()
    }


def get_unavailable_count():
    """Return the number of engines currently UNAVAILABLE."""
    return sum(1 for info in _engine_states.values() if info.get("state") == UNAVAILABLE)


async def engine_health_loop():
    """Background loop that checks engine health every 5 minutes."""
    LOGGER.info("Engine health checker started (5-minute interval)")
    # Initial check after 60s startup grace period
    await sleep(60)
    while True:
        try:
            await _check_all_engines()
        except Exception as e:
            LOGGER.warning(f"Engine health check error: {e}")
        await sleep(_CHECK_INTERVAL)


async def start_engine_health_checker():
    """Entry point — called from bot/__main__.py as a background task."""
    create_task(engine_health_loop())
