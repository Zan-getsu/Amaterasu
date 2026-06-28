from re import match as re_match
from base64 import urlsafe_b64decode, urlsafe_b64encode


def is_magnet(url: str):
    return bool(
        re_match(
            r"^magnet:\?.*xt=urn:(btih|btmh):([a-zA-Z0-9]{32,40}|[a-z2-7]{32}).*", url
        )
    )


def extract_info_hash(magnet: str):
    """Phase 1 port P2 — extract the 40-char hex info hash from a magnet URI.

    Returns the lowercase hex hash string, or None if no btih hash is found.
    Used by the Real-Debrid cached-magnet check to query RD's
    /torrents/instantAvailability/{hash} endpoint.

    Handles both v1 (btih:HEX) and v2 (btmh:HEX) magnet formats.
    """
    if not magnet or not isinstance(magnet, str):
        return None
    from re import search
    # btih: followed by 40 hex chars (v1) — most common
    m = search(r"btih:([a-fA-F0-9]{40})", magnet)
    if m:
        return m.group(1).lower()
    # btih: followed by 32 base32 chars (v1 alternate)
    m = search(r"btih:([A-Z2-7]{32})", magnet)
    if m:
        # Decode base32 to hex
        import base64
        try:
            decoded = base64.b32decode(m.group(1))
            return decoded.hex().lower()
        except Exception:
            return None
    return None


def is_url(url: str):
    return bool(
        re_match(
            r"^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?(\?[^#\s]*)?(#.*)?$",
            url,
        )
    )


def is_gdrive_link(url: str):
    return "drive.google.com" in url or "drive.usercontent.google.com" in url


def is_telegram_link(url: str):
    return url.startswith(("https://t.me/", "tg://openmessage?user_id="))


def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url


def is_pixeldrain_link(url: str):
    return "pixeldrain.com" in url


def is_mega_folder_link(link: str) -> bool:
    if not link:
        return False
    return "/folder/" in link or "#F!" in link


def get_mega_subfolder_handle(link: str) -> str | None:
    if not link:
        return None
    parts = link.split("/folder/")
    if len(parts) >= 3:
        return parts[-1].split("#")[0].split("/")[0].split("?")[0]
    parts = link.split("#F!")
    if len(parts) >= 3:
        return parts[-1].split("!")[0].split("/")[0].split("?")[0]
    return None


def get_mega_link_type(url):
    return "folder" if "folder" in url or "/#F!" in url else "file"


def is_share_link(url: str):
    """Detect drive share-link intermediary pages.

    These sites wrap a Google Drive link behind ads + countdowns + JS
    redirects. Each family needs a dedicated scraper (or the generic
    sharer_scraper fallback) to extract the underlying GDrive URL.

    Recognized families (Phase 1 port P4 expanded the list):
      - gdtot (any *.gdtot.* domain — requires subdomain)
      - filepress, filebee, appdrive, gdflix (bare domain only;
        www./sub. NOT matched — preserved from v1.6.3 for backward compat)
      - drivelinks, hubdrive, katdrive, kolop, sharerpp (Phase 1 port P4:
        newly recognized, same bare-domain pattern, route to sharer_scraper)
    """
    if not url or not isinstance(url, str):
        return False
    return bool(
        re_match(
            r"https?:\/\/.+\.gdtot\.\S+"
            r"|https?:\/\/(filepress|filebee|appdrive|gdflix)\.\S+"
            r"|https?:\/\/(drivelinks|hubdrive|katdrive|kolop|sharerpp)\.\S+",
            url,
        )
    )


def is_rclone_path(path: str):
    return bool(
        re_match(
            r"^(mrcc:)?(?!(magnet:|mtp:|sa:|tp:))(?![- ])[a-zA-Z0-9_\. -]+(?<! ):(?!.*\/\/).*$|^rcl$",
            path,
        )
    )


def is_gdrive_id(id_: str):
    return bool(
        re_match(
            r"^(tp:|sa:|mtp:)?(?:[a-zA-Z0-9-_]{33}|[a-zA-Z0-9_-]{19})$|^gdl$|^(tp:|mtp:)?root$",
            id_,
        )
    )


def encode_slink(string):
    return (urlsafe_b64encode(string.encode("ascii")).decode("ascii")).strip("=")


def decode_slink(b64_str):
    return urlsafe_b64decode(
        (b64_str.strip("=") + "=" * (-len(b64_str.strip("=")) % 4)).encode("ascii")
    ).decode("ascii")
