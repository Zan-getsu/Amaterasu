from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from json import dumps, loads
from struct import pack, unpack
from time import time

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {char: index for index, char in enumerate(_B58_ALPHABET)}


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return urlsafe_b64decode(data + padding)


def _b58encode(data: bytes) -> str:
    if not data:
        return ""
    leading_zeroes = len(data) - len(data.lstrip(b"\0"))
    value = int.from_bytes(data, "big")
    encoded = ""
    while value:
        value, remainder = divmod(value, 58)
        encoded = _B58_ALPHABET[remainder] + encoded
    return ("1" * leading_zeroes) + (encoded or "1")


def _b58decode(data: str) -> bytes:
    if not data:
        return b""
    value = 0
    for char in data:
        if char not in _B58_INDEX:
            raise ValueError("Invalid base58 character")
        value = value * 58 + _B58_INDEX[char]
    leading_zeroes = len(data) - len(data.lstrip("1"))
    decoded = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
    return (b"\0" * leading_zeroes) + decoded


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


def make_route_token(
    secret: str,
    purpose: str,
    chat_id: int,
    message_id: int,
) -> str:
    payload = pack(">qI", int(chat_id), int(message_id))
    mac = hmac_new(
        secret.encode(),
        purpose.encode() + b":" + payload,
        sha256,
    ).digest()[:12]
    return f"r{_b58encode(payload + mac)}"


def verify_route_token(
    token: str | None,
    secret: str,
    purpose: str,
) -> tuple[int, int] | None:
    if not token or not secret:
        return None
    candidates = []
    if token.startswith("r"):
        try:
            candidates.append(_b58decode(token[1:]))
        except Exception:
            pass
    try:
        candidates.append(_b64decode(token))
    except Exception:
        pass

    for data in candidates:
        if len(data) != 24:
            continue
        payload, mac = data[:12], data[12:]
        expected = hmac_new(
            secret.encode(),
            purpose.encode() + b":" + payload,
            sha256,
        ).digest()[:12]
        if not compare_digest(mac, expected):
            continue
        return unpack(">qI", payload)
    return None
