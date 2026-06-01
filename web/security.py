from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from json import dumps, loads
from time import time


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + padding)


def _signature(secret: str, payload: str) -> str:
    return _b64encode(hmac_new(secret.encode(), payload.encode(), sha256).digest())


def make_signed_token(
    secret: str,
    purpose: str,
    subject: str | int,
    *,
    ttl: int | None = None,
    extra: dict | None = None,
) -> str:
    payload = {
        "p": purpose,
        "s": str(subject),
        "e": int(time() + ttl) if ttl else 0,
        "x": extra or {},
    }
    body = _b64encode(dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_signature(secret, body)}"


def verify_signed_token(
    token: str | None,
    secret: str,
    purpose: str,
    subject: str | int,
    *,
    extra: dict | None = None,
) -> bool:
    if not token or "." not in token or not secret:
        return False
    try:
        body, sig = token.rsplit(".", 1)
        expected = _signature(secret, body)
        if not compare_digest(sig, expected):
            return False
        payload = loads(_b64decode(body))
    except Exception:
        return False

    expires_at = int(payload.get("e") or 0)
    return bool(
        payload.get("p") == purpose
        and payload.get("s") == str(subject)
        and payload.get("x", {}) == (extra or {})
        and (not expires_at or expires_at >= int(time()))
    )


def make_short_token(
    secret: str,
    purpose: str,
    subject: str | int,
    *,
    length: int = 12,
) -> str:
    payload = f"{purpose}:{subject}"
    digest = hmac_new(secret.encode(), payload.encode(), sha256).digest()
    return _b64encode(digest)[:length]


def verify_short_token(
    token: str | None,
    secret: str,
    purpose: str,
    subject: str | int,
    *,
    length: int = 12,
) -> bool:
    if not token or not secret:
        return False
    expected = make_short_token(secret, purpose, subject, length=length)
    return compare_digest(token, expected)
