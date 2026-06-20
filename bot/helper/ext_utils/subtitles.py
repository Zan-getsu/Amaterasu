"""Phase 4.4 — Automatic subtitle download.

After a video file is downloaded, if AUTO_SUBTITLES=True, search
OpenSubtitles API for subtitles in SUBTITLE_LANGS (comma-separated,
default 'en'). Download the top match per language. Save as
filename.lang.srt in the same directory. Bundle with the upload.

If OpenSubtitles API is unreachable or returns no results, log WARNING
and continue the upload without subtitles. Do not fail the task.

Cache successful lookups in MongoDB for 7 days (key: content hash +
language code) to avoid repeated API calls for the same file.

OpenSubtitles API: https://opensubtitles.stoplight.io/docs/opensubtitles-api/
"""

from asyncio import gather
from hashlib import md5
from logging import getLogger
from os import path as ospath

from aiofiles.os import path as aiopath

from bot.core.config_manager import Config

LOGGER = getLogger(__name__)

# OpenSubtitles REST API base URL
_OS_API_BASE = "https://api.opensubtitles.com/api/v1"
# Cache TTL in seconds (7 days)
_CACHE_TTL = 7 * 24 * 3600

_VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg"}
)


def _is_video_file(filename):
    """Check if a file is a video based on extension."""
    ext = ospath.splitext(filename)[1].lower()
    return ext in _VIDEO_EXTENSIONS


async def _compute_file_hash(filepath):
    """Compute OpenSubtitles hash for a file. The hash is based on the
    first and last 64 KB of the file plus the file size. This is the
    algorithm OpenSubtitles uses for file-based lookups."""
    try:
        from aiofiles import open as aiopen
        size = (await aiopath.getsize(filepath)) if await aiopath.exists(filepath) else 0
        if size < 65536 * 2:
            return None, size
        hash_val = size
        async with aiopen(filepath, "rb") as f:
            # First 64 KB
            chunk = await f.read(65536)
            for byte in chunk:
                hash_val = (hash_val + byte) & 0xFFFFFFFFFFFFFFFF
            # Last 64 KB
            await f.seek(max(0, size - 65536))
            chunk = await f.read(65536)
            for byte in chunk:
                hash_val = (hash_val + byte) & 0xFFFFFFFFFFFFFFFF
        return f"{hash_val:016x}", size
    except Exception as e:
        LOGGER.warning(f"Subtitle hash computation failed for {filepath}: {e}")
        return None, 0


async def _search_opensubtitles(file_hash, size, filename, language, api_key):
    """Search OpenSubtitles for subtitles matching the file hash.
    Returns the download URL for the best match, or None."""
    try:
        from bot.helper.ext_utils.http_client import http_client
        headers = {
            "Api-Key": api_key,
            "User-Agent": "Amaterasu v1.6.2",
            "Content-Type": "application/json",
        }
        params = {
            "ai_translated": "exclude",
            "languages": language,
            "order_by": "download_count",
            "order_direction": "desc",
            "limit": 5,
        }
        if file_hash and size:
            params["moviehash"] = file_hash
            params["moviebytesize"] = str(size)
        else:
            # Fall back to filename search
            params["query"] = ospath.splitext(filename)[0]
        resp = await http_client.get(
            f"{_OS_API_BASE}/subtitles",
            params=params,
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            LOGGER.warning(f"OpenSubtitles API returned {resp.status_code}")
            return None
        data = resp.json()
        subtitles = data.get("data", [])
        if not subtitles:
            return None
        # Return the file_id of the top match for download
        files = subtitles[0].get("attributes", {}).get("files", [])
        if files:
            return files[0].get("file_id")
        return None
    except Exception as e:
        LOGGER.warning(f"OpenSubtitles search error: {e}")
        return None


async def _download_subtitle(file_id, api_key, output_path):
    """Download a subtitle file from OpenSubtitles by file_id.
    Returns True on success, False on failure."""
    try:
        from bot.helper.ext_utils.http_client import http_client
        from aiofiles import open as aiopen
        headers = {
            "Api-Key": api_key,
            "User-Agent": "Amaterasu v1.6.2",
            "Content-Type": "application/json",
        }
        # Step 1: request download link
        resp = await http_client.post(
            f"{_OS_API_BASE}/download",
            json={"file_id": int(file_id)},
            headers=headers,
            timeout=30,
        )
        if resp.status_code != 200:
            LOGGER.warning(f"OpenSubtitles download API returned {resp.status_code}")
            return False
        download_data = resp.json()
        download_url = download_data.get("link")
        if not download_url:
            return False
        # Step 2: download the actual subtitle file
        resp = await http_client.get(download_url, timeout=60)
        if resp.status_code != 200:
            return False
        async with aiopen(output_path, "wb") as f:
            await f.write(resp.content)
        return True
    except Exception as e:
        LOGGER.warning(f"Subtitle download error: {e}")
        return False


async def _get_cached_subtitle(file_hash, language):
    """Check MongoDB cache for a previously-found subtitle.
    Returns the cached file_id or None."""
    try:
        from bot.helper.ext_utils.db_handler import database
        if database.db is None:
            return None
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=_CACHE_TTL)
        doc = await database.db.subtitle_cache.find_one(
            {"file_hash": file_hash, "language": language, "cached_at": {"$gte": cutoff}},
        )
        return doc.get("file_id") if doc else None
    except Exception:
        return None


async def _cache_subtitle(file_hash, language, file_id):
    """Cache a subtitle file_id in MongoDB for 7 days."""
    try:
        from bot.helper.ext_utils.db_handler import database
        if database.db is None:
            return
        from datetime import datetime, timezone
        await database.db.subtitle_cache.update_one(
            {"file_hash": file_hash, "language": language},
            {"$set": {"file_id": file_id, "cached_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception:
        pass


async def download_subtitles(filepath):
    """Main entry point. Called after a video download completes.

    If AUTO_SUBTITLES is True, searches OpenSubtitles for subtitles in
    SUBTITLE_LANGS. Downloads the top match per language and saves as
    .srt files alongside the video. Returns a list of downloaded .srt
    paths (empty list if none found or disabled).

    Never raises — subtitle failure does not block the upload.
    """
    if not getattr(Config, "AUTO_SUBTITLES", False):
        return []

    api_key = getattr(Config, "OPENSUBTITLES_API", "") or getattr(Config, "AUTO_SUBTITLES_API", "")
    if not api_key:
        LOGGER.info("AUTO_SUBTITLES enabled but no OpenSubtitles API key set — skipping")
        return []

    filename = ospath.basename(filepath)
    if not _is_video_file(filename):
        return []

    langs_str = getattr(Config, "SUBTITLE_LANGS", "en") or "en"
    languages = [l.strip() for l in langs_str.split(",") if l.strip()]
    if not languages:
        languages = ["en"]

    LOGGER.info(f"Auto-subtitles: searching for '{filename}' in {languages}")
    file_hash, size = await _compute_file_hash(filepath)

    downloaded = []
    tasks = []
    for lang in languages:
        tasks.append(_fetch_one_subtitle(filepath, filename, file_hash, size, lang, api_key))
    results = await gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, str) and result:
            downloaded.append(result)

    if downloaded:
        LOGGER.info(f"Auto-subtitles: downloaded {len(downloaded)} subtitle file(s) for {filename}")
    else:
        LOGGER.info(f"Auto-subtitles: no subtitles found for {filename}")

    return downloaded


async def _fetch_one_subtitle(filepath, filename, file_hash, size, language, api_key):
    """Fetch a single subtitle for one language. Returns the .srt path
    or empty string on failure."""
    # Check cache first
    if file_hash:
        cached_file_id = await _get_cached_subtitle(file_hash, language)
        if cached_file_id:
            output_path = f"{ospath.splitext(filepath)[0]}.{language}.srt"
            if await _download_subtitle(cached_file_id, api_key, output_path):
                LOGGER.info(f"Auto-subtitles: cached hit for {language}")
                return output_path

    # Search OpenSubtitles
    file_id = await _search_opensubtitles(file_hash, size, filename, language, api_key)
    if not file_id:
        return ""

    # Download
    output_path = f"{ospath.splitext(filepath)[0]}.{language}.srt"
    if await _download_subtitle(file_id, api_key, output_path):
        # Cache the result
        if file_hash:
            await _cache_subtitle(file_hash, language, file_id)
        return output_path
    return ""
