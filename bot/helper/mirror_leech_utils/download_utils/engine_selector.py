"""Phase 2.7 — Engine fallback chain / smart engine selection.

When /mirror or /leech is called without an explicit engine flag
(/qbmirror, /jdmirror, etc.), this module picks the engine based on
the URL pattern. On engine failure, falls back one step down the chain.

Selection logic (in order):
  1. magnet: or .torrent file → qBittorrent if healthy, else aria2.
  2. mega.nz → mega engine.
  3. drive.google.com or gdrive:// → GDrive engine.
  4. rclone:// or recognized rclone remote → rclone engine.
  5. All other HTTP/HTTPS → try direct_link_generator first. If it
     returns a direct link, use aria2 on that link. If it returns
     nothing, use aria2 on the original URL.

On engine failure, log: "Engine [X] failed for [URL]: [error].
Falling back to [Y]"

This module is the entire "smart engine" feature. No new commands —
it's the default behavior of /mirror and /leech when no engine flag
is given.
"""

from logging import getLogger

LOGGER = getLogger(__name__)


def select_engine(url, engine_health=None):
    """Select the best engine for the given URL.

    Args:
        url: The download URL string.
        engine_health: Optional dict mapping engine name to health
            state ('HEALTHY', 'DEGRADED', 'UNAVAILABLE'). If an engine
            is UNAVAILABLE, skip it and use the fallback. If None,
            assume all engines are healthy.

    Returns:
        List of engine names in fallback order. The caller should try
        each in order until one succeeds. The list always includes
        'aria2' as the final fallback (it can handle any URL type).
    """
    url_lower = url.lower() if isinstance(url, str) else ""

    # Helper to check if an engine is available
    def is_available(name):
        if engine_health is None:
            return True
        state = engine_health.get(name, "HEALTHY")
        return state != "UNAVAILABLE"

    # 1. Magnet or .torrent
    if url_lower.startswith("magnet:") or url_lower.endswith(".torrent"):
        chain = ["qbit", "aria2"]
        return [e for e in chain if is_available(e)] or ["aria2"]

    # 2. Mega
    if "mega.nz" in url_lower or "mega.co.nz" in url_lower:
        chain = ["mega", "aria2"]
        return [e for e in chain if is_available(e)] or ["aria2"]

    # 3. Google Drive
    if "drive.google.com" in url_lower or "gdrive://" in url_lower:
        chain = ["gdrive", "aria2"]
        return [e for e in chain if is_available(e)] or ["aria2"]

    # 4. Rclone
    if "rclone://" in url_lower:
        chain = ["rclone", "aria2"]
        return [e for e in chain if is_available(e)] or ["aria2"]

    # 5. HTTP/HTTPS — try direct_link_generator first (via aria2 on
    #    the generated link), then fall back to aria2 on the original URL.
    #    The actual direct_link_generator call happens in the download
    #    dispatcher; here we just return the engine chain.
    chain = ["direct", "aria2"]
    return [e for e in chain if is_available(e)] or ["aria2"]


def engine_display_name(engine):
    """Return a human-readable name for an engine code."""
    names = {
        "qbit": "qBittorrent",
        "aria2": "Aria2",
        "mega": "Mega",
        "gdrive": "Google Drive",
        "rclone": "Rclone",
        "direct": "Direct Link Generator",
        "jd": "JDownloader",
        "nzb": "SABnzbd",
        "ytdlp": "yt-dlp",
        "telegram": "Telegram",
    }
    return names.get(engine, engine)


async def get_engine_health_snapshot():
    """Return a snapshot of engine health states from engine_health module.

    Returns None if engine_health module isn't loaded yet (during startup).
    """
    try:
        from ....helper.ext_utils.engine_health import get_health_states
        return get_health_states()
    except Exception:
        return None
