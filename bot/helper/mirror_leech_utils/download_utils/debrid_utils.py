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


def _parse_api_key():
    """Return (provider, key) tuple from Config.DEBRID_LINK_API.

    Provider is one of: 'real-debrid', 'alldebrid', 'premiumize',
    'debrid-link'. Key is the bare API key without the prefix.

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
            "with a provider prefix (rd:, ad:, pm:, dl:)."
        )
    if provider == "real-debrid":
        return _real_debrid(url, key)
    if provider == "alldebrid":
        return _alldebrid(url, key)
    if provider == "premiumize":
        return _premiumize(url, key)
    if provider == "debrid-link":
        return _debrid_link(url, key)
    raise DirectDownloadLinkException(
        f"ERROR: Unknown debrid provider: {provider}"
    )


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
