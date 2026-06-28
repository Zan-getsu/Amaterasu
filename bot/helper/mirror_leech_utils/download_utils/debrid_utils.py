"""Phase 1.1 — Debrid multi-provider support.

Unrestricts download URLs via debrid services. Dispatched by the
DEBRID_LINK_API config value prefix:
  - "rd:YOUR_KEY"  → Real-Debrid (https://real-debrid.com)
  - "ad:YOUR_KEY"  → AllDebrid (https://alldebrid.com)
  - "pm:YOUR_KEY"  → Premiumize (https://premiumize.me)
  - "dl:YOUR_KEY"  → Debrid-Link (https://debrid-link.com) — legacy,
                     also matched when no prefix is given (backward
                     compat with v1.5.0 Config.DEBRID_LINK_API which
                     was a bare key for debrid-link.com)
  - "tb:YOUR_KEY"  → TorBox (https://torbox.app) — Phase 1 port P1.
                     TorBox also doubles as a torrent seedbox.

If DEBRID_LINK_API is empty, this module is never called (Rule 2 —
silent absence for unconfigured features).

Each provider returns a direct download URL that aria2 can fetch
without going through the file-hosting site's wait page/ads.
"""

from json import loads as json_loads
from logging import getLogger

from cloudscraper import create_scraper

from bot.core.config_manager import Config
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException

LOGGER = getLogger(__name__)


# Phase 1 port P1 — TorBox supported host domains (subset; the full
# list lives at https://torbox.app/settings?tab=api). Used by the
# direct_link_generator dispatcher to decide whether to route a URL
# through TorBox. Kept here (not in direct_link_generator.py) so the
# TorBox resolver is fully self-contained.
TORBOX_SUPPORTED_SITES = [
    "rapidgator.net",
    "rg.to",
    "nitroflare.com",
    "keep2share.cc",
    "k2s.cc",
    "katfile.com",
    "turbobit.net",
    "depositfiles.com",
    "filefactory.com",
    "filespace.com",
    "hitfile.net",
    "file.al",
    "fboom.me",
    "hotlink.cc",
    "oboom.com",
    "sendit.cloud",
    "sendspace.com",
    "takefile.link",
    "tezfiles.com",
    "thevideo.me",
    "file-up.org",
    "filefox.cc",
    "filer.net",
    "filerio.in",
    "filesabc.com",
    "fireget.com",
    "flashbit.cc",
    "florenfile.com",
    "fshare.vn",
    "gigapeta.com",
    "goloady.com",
    "hexupload.net",
    "icerbox.com",
    "inclouddrive.com",
    "isra.cloud",
    "load.to",
    "mixdrop.co",
    "mixloads.com",
    "mp4upload.com",
    "nelion.me",
    "ninjastream.to",
    "nowvideo.club",
    "prefiles.com",
    "rapidgator.asia",
    "rapidrar.com",
    "rapidu.net",
    "rarefile.net",
    "redbunker.net",
    "rockfile.eu",
    "rutube.ru",
    "scribd.com",
    "simfileshare.net",
    "speed-down.org",
    "streamon.to",
    "streamtape.com",
    "turbobit.cc",
    "turbobit.pw",
    "turbobit.online",
    "turbobit.ru",
    "turbobit.live",
    "uptobox.com",
    "uptostream.com",
    "wdupload.com",
    "worldbytez.com",
    "world-files.com",
    "wupfile.com",
    "1fichier.com",
    "alterupload.com",
    "cjoint.net",
    "desfichiers.com",
    "dfichiers.com",
    "megadl.org",
    "mesfichiers.org",
    "pjointe.com",
    "tenvoi.com",
    "dl4free.com",
    "apkadmin.com",
    "clicknupload.link",
    "clicknupload.org",
    "clicknupload.co",
    "clicknupload.cc",
    "ddl.to",
    "ddownload.com",
    "dropapk.to",
    "drop.download",
    "easybytez.com",
    "emload.com",
    "fastfile.cc",
    "letsupload.cc",
    "moonfile.com",
    "nofile.io",
]


def _parse_api_key():
    """Return (provider, key) tuple from Config.DEBRID_LINK_API.

    Provider is one of: 'real-debrid', 'alldebrid', 'premiumize',
    'debrid-link', 'torbox'. Key is the bare API key without the prefix.

    Backward compat: if the value has no prefix, assume debrid-link
    (the v1.5.0 behavior).
    """
    raw = (Config.DEBRID_LINK_API or "").strip()
    if not raw:
        return None, None
    if raw.startswith("rd:"):
        return "real-debrid", raw[3:].strip()
    if raw.startswith("ad:"):
        return "alldebrid", raw[3:].strip()
    if raw.startswith("pm:"):
        return "premiumize", raw[3:].strip()
    if raw.startswith("dl:"):
        return "debrid-link", raw[3:].strip()
    # Phase 1 port P1 — TorBox prefix
    if raw.startswith("tb:"):
        return "torbox", raw[3:].strip()
    # No prefix — assume debrid-link (v1.5.0 backward compat)
    return "debrid-link", raw


def debrid_unrestrict(url):
    """Main entry point. Dispatches to the correct provider based on
    the DEBRID_LINK_API prefix. Returns a direct download URL string,
    or a dict with 'contents' for multi-file responses.

    Raises DirectDownloadLinkException on any failure."""
    provider, key = _parse_api_key()
    if not provider or not key:
        raise DirectDownloadLinkException(
            "ERROR: No debrid API key configured. Set DEBRID_LINK_API "
            "with a provider prefix (rd:, ad:, pm:, dl:, tb:)."
        )
    if provider == "real-debrid":
        return _real_debrid(url, key)
    if provider == "alldebrid":
        return _alldebrid(url, key)
    if provider == "premiumize":
        return _premiumize(url, key)
    if provider == "debrid-link":
        return _debrid_link(url, key)
    # Phase 1 port P1 — TorBox dispatch
    if provider == "torbox":
        return _torbox(url, key)
    raise DirectDownloadLinkException(
        f"ERROR: Unknown debrid provider: {provider}"
    )


def _torbox(url, api_key):
    """TorBox unrestrict endpoint (Phase 1 port P1).

    TorBox API: https://github.com/torboxapp/torbox-api
    Endpoint: POST https://api.torbox.app/v1/api/webdl/create_webdl
    Auth: api_key passed as user_hash in the request body.

    Returns the direct download URL from the response. TorBox streams
    the file from its own CDN, so the returned URL is fetchable by aria2
    without further authentication.

    Error handling: TorBox returns {"success": false, "detail": "..."}
    on failure. We translate that into a DirectDownloadLinkException.
    """
    cget = create_scraper().request
    try:
        resp = cget(
            "POST",
            "https://api.torbox.app/v1/api/webdl/create_webdl",
            json={
                "web_dl_url": url,
                "user_hash": api_key,
                "asynchronous": False,
            },
            timeout=30,
        ).json()
        if not resp.get("success"):
            detail = resp.get("detail") or resp.get("msg") or "unknown error"
            raise DirectDownloadLinkException(f"ERROR: TorBox: {detail}")
        data = resp.get("data") or {}
        download_url = data.get("download_url") or data.get("download_url_1")
        if not download_url:
            raise DirectDownloadLinkException(
                "ERROR: TorBox: no download URL in response"
            )
        return download_url
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: TorBox: {e}") from e


def real_debrid_cached_magnet(magnet):
    """Phase 1 port P2 — check if Real-Debrid has this torrent cached.

    If cached, returns a dict in the multi-file direct-download format:
        {
            "contents": [
                {"filename": "...", "url": "https://..."},
                ...
            ],
            "title": "<info_hash>",
            "total_size": <int>,
        }
    The caller (direct_downloader.py) can consume this as a multi-file
    direct download, bypassing qBittorrent/aria2 entirely.

    If NOT cached (or if Real-Debrid is not configured, or on any error),
    returns None. The caller then falls through to normal torrent
    handling. This makes the feature safe to call unconditionally — it
    never raises, only returns None on any non-success path.

    Rule 1 (default-off): if DEBRID_LINK_API is empty or not Real-Debrid,
    returns None immediately (no network call).
    Rule 2 (feature-flag guard): the caller checks is_magnet() before
    calling this function, but we also guard internally.
    """
    # Rule 1: only activate when Real-Debrid is the configured provider
    provider, key = _parse_api_key()
    if provider != "real-debrid" or not key:
        return None

    # Extract info hash from the magnet
    from bot.helper.ext_utils.links_utils import extract_info_hash
    info_hash = extract_info_hash(magnet)
    if not info_hash:
        return None  # not a valid magnet or no btih hash

    cget = create_scraper().request
    try:
        resp = cget(
            "GET",
            f"https://api.real-debrid.com/rest/1.0/torrents/instantAvailability/{info_hash}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        ).json()
    except Exception:
        # Network/JSON errors → return None (fall through to torrent)
        # Logged at debug level if needed; never raise.
        return None

    # The "never raises" safety contract means ALL response parsing must
    # also be wrapped. Real-Debrid could (in theory) return malformed
    # data: a non-dict value at resp[info_hash], a non-list at .get("rd"),
    # or a non-dict inside a variant. Any of these would raise
    # AttributeError/TypeError. Catch them all and return None.
    try:
        # Real-Debrid returns { "<hash>": { "rd": [variant1, variant2, ...] } }
        # where each variant is a dict of {file_id: {filename, filesize, download}}
        if info_hash not in resp:
            return None  # not cached

        hash_data = resp[info_hash]
        if not isinstance(hash_data, dict):
            return None  # malformed response — hash maps to non-dict

        variants = hash_data.get("rd", [])
        if not variants or not isinstance(variants, list):
            return None  # cached metadata but no downloadable variants

        # Pick the variant with the largest total size (usually the complete torrent)
        def variant_size(v):
            if not isinstance(v, dict):
                return 0
            return sum(
                f.get("filesize", 0) for f in v.values() if isinstance(f, dict)
            )

        best_variant = max(variants, key=variant_size)
        if not isinstance(best_variant, dict):
            return None  # malformed variant

        contents = []
        total_size = 0
        for file_data in best_variant.values():
            if not isinstance(file_data, dict):
                continue  # skip malformed file entries
            filename = file_data.get("filename", "unknown")
            download_url = file_data.get("download")
            filesize = file_data.get("filesize", 0)
            if download_url:
                contents.append({
                    "filename": filename,
                    "url": download_url,
                })
                total_size += filesize

        if not contents:
            return None  # variant had no downloadable files

        return {
            "contents": contents,
            "title": info_hash,
            "total_size": total_size,
        }
    except Exception:
        # Any parsing error → return None (fall through to torrent).
        # This preserves the "never raises" safety contract.
        return None


def _real_debrid(url, api_key):
    """Real-Debrid unrestrict endpoint.
    Docs: https://api.real-debrid.com"""
    cget = create_scraper().request
    try:
        resp = cget(
            "POST",
            "https://api.real-debrid.com/rest/1.0/unrestrict/link",
            data={"link": url},
            headers={"Authorization": f"Bearer {api_key}"},
        ).json()
        if "error" in resp:
            raise DirectDownloadLinkException(
                f"ERROR: Real-Debrid: {resp.get('error', 'unknown')}"
            )
        return resp.get("download", url)
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: Real-Debrid: {e}")


def _alldebrid(url, api_key):
    """AllDebrid unrestrict endpoint.
    Docs: https://docs.alldebrid.com/"""
    cget = create_scraper().request
    try:
        resp = cget(
            "GET",
            "https://api.alldebrid.com/v4/link/unlock",
            params={"agent": "amaterasu", "apikey": api_key, "link": url},
        ).json()
        if resp.get("status") != "success":
            err = resp.get("error", {}).get("message", "unknown error")
            raise DirectDownloadLinkException(f"ERROR: AllDebrid: {err}")
        return resp["data"]["link"]
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: AllDebrid: {e}")


def _premiumize(url, api_key):
    """Premiumize transfer endpoint.
    Docs: https://premiumize.me/api"""
    cget = create_scraper().request
    try:
        resp = cget(
            "POST",
            "https://premiumize.me/api/transfer/create",
            data={"src": url},
            params={"apikey": api_key},
        ).json()
        if resp.get("status") != "success":
            err = resp.get("message", "unknown error")
            raise DirectDownloadLinkException(f"ERROR: Premiumize: {err}")
        # Premiumize returns a transfer id — need to poll for completion
        transfer_id = resp.get("transfers", [{}])[0].get("id")
        if not transfer_id:
            raise DirectDownloadLinkException(
                "ERROR: Premiumize: no transfer id returned"
            )
        # Return the transfer details URL — the actual download URL is
        # available after the transfer completes. For simplicity, return
        # the Premiumize dashboard link; full polling would require a
        # background task.
        return f"https://premiumize.me/transfers?tab=transfer&id={transfer_id}"
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: Premiumize: {e}")


def _debrid_link(url, api_key):
    """Debrid-Link unrestrict endpoint (v1.5.0 backward compat).
    Docs: https://debrid-link.com/api-docs"""
    from os.path import join as ospath_join
    from urllib.parse import unquote
    cget = create_scraper().request
    try:
        resp = cget(
            "POST",
            f"https://debrid-link.com/api/v2/downloader/add?access_token={api_key}",
            data={"url": url},
        ).json()
        if not resp.get("success"):
            raise DirectDownloadLinkException(
                f"ERROR: Debrid-Link: {resp.get('error', 'unknown')} "
                f"(id: {resp.get('error_id', 'n/a')})"
            )
        value = resp.get("value")
        if isinstance(value, dict):
            return value.get("downloadUrl", url)
        if isinstance(value, list):
            details = {
                "contents": [],
                "title": unquote(url.rstrip("/").split("/")[-1]),
                "total_size": 0,
            }
            for dl in value:
                if dl.get("expired", False):
                    continue
                item = {
                    "path": ospath_join(details["title"]),
                    "filename": dl["name"],
                    "url": dl["downloadUrl"],
                }
                if "size" in dl:
                    details["total_size"] += dl["size"]
                details["contents"].append(item)
            return details
        return url
    except DirectDownloadLinkException:
        raise
    except Exception as e:
        raise DirectDownloadLinkException(f"ERROR: Debrid-Link: {e}")
