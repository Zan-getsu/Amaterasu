"""Validation helpers for the private Telegram session generator."""

from re import fullmatch, sub

SESSION_PAGE_TTL_SECONDS = 15 * 60
SESSION_ATTEMPT_TTL_SECONDS = 10 * 60


def validate_telegram_api_credentials(api_id, api_hash) -> tuple[int, str]:
    """Return a validated Telegram API ID and hash."""

    try:
        clean_id = int(str(api_id).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid Telegram API ID.") from exc
    clean_hash = str(api_hash or "").strip().lower()
    if clean_id <= 0 or clean_id >= 2**31:
        raise ValueError("Enter a valid Telegram API ID.")
    if not fullmatch(r"[0-9a-f]{32}", clean_hash):
        raise ValueError("Enter the 32-character API hash from my.telegram.org.")
    return clean_id, clean_hash


def normalize_phone_number(phone: str) -> str:
    """Normalize common phone formatting while requiring international form."""

    raw = str(phone or "").strip()
    if len(raw) > 64 or not fullmatch(r"[+0-9()\s-]+", raw):
        raise ValueError("Enter a valid phone number in international format.")
    clean = sub(r"[()\s-]", "", raw)
    if not fullmatch(r"\+[1-9][0-9]{6,14}", clean):
        raise ValueError("Use international format, for example +14154566376.")
    return clean


def normalize_login_code(code: str) -> str:
    """Accept Telegram login codes with optional spaces or hyphens."""

    raw = str(code or "").strip()
    if len(raw) > 32 or not fullmatch(r"[0-9\s-]+", raw):
        raise ValueError("Enter the login code using digits only.")
    clean = sub(r"[\s-]", "", raw)
    if not fullmatch(r"[0-9]{5,6}", clean):
        raise ValueError("Enter the 5 or 6 digit login code from Telegram.")
    return clean


def validate_two_step_password(password: str) -> str:
    """Reject empty or unreasonably large two-step passwords."""

    value = str(password or "")
    if not value:
        raise ValueError("Enter your two-step verification password.")
    if len(value) > 256 or "\x00" in value:
        raise ValueError("The two-step verification password is invalid.")
    return value
