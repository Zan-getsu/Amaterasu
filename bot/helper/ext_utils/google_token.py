"""Google OAuth helpers for the per-user token generator.

The web flow accepts either a Google OAuth Web client ``credentials.json``
file or the equivalent client ID/secret values.  Client values are kept only
inside a short-lived, encrypted OAuth-state record.  Generated credentials
are serialized with pickle protocol 4 for compatibility with older mirror
and automation clients.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import JSONDecodeError, dumps, loads
from pickle import dumps as pickle_dumps
from re import split as re_split
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken

try:
    from google.oauth2.credentials import Credentials as GoogleCredentials
except Exception:  # pragma: no cover - reported cleanly by the web route
    GoogleCredentials = None

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_OAUTH_STATE_TTL_SECONDS = 15 * 60
TOKEN_PAGE_TTL_SECONDS = 15 * 60
MAX_CREDENTIALS_FILE_SIZE = 64 * 1024

_ENCRYPTED_BLOB_MAGIC = b"AMATERASU_FERNET_V1\0"


def parse_google_scopes(raw: str) -> list[str]:
    """Parse comma, space, or newline-separated OAuth scopes."""

    scopes = [part.strip() for part in re_split(r"[\s,]+", (raw or "").strip()) if part.strip()]
    return scopes or [GOOGLE_DRIVE_SCOPE]


def validate_google_client_values(client_id: str, client_secret: str) -> tuple[str, str]:
    """Validate manually entered OAuth Web client values."""

    clean_id = (client_id or "").strip()
    clean_secret = (client_secret or "").strip()
    if not clean_id:
        raise ValueError("Enter your Google OAuth Client ID.")
    if not clean_secret:
        raise ValueError("Enter your Google OAuth Client Secret.")
    if len(clean_id) > 512 or "\r" in clean_id or "\n" in clean_id:
        raise ValueError("The Google OAuth Client ID is invalid.")
    if len(clean_secret) > 512 or "\r" in clean_secret or "\n" in clean_secret:
        raise ValueError("The Google OAuth Client Secret is invalid.")
    return clean_id, clean_secret


def parse_google_credentials_file(data: bytes) -> tuple[str, str]:
    """Extract a Web OAuth client ID and secret from credentials.json."""

    if not data:
        raise ValueError("Choose a credentials.json file.")
    if len(data) > MAX_CREDENTIALS_FILE_SIZE:
        raise ValueError("credentials.json is too large.")
    try:
        payload = loads(data.decode("utf-8"))
    except (UnicodeDecodeError, JSONDecodeError) as exc:
        raise ValueError("credentials.json is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("credentials.json must contain a JSON object.")
    web = payload.get("web")
    if not isinstance(web, dict):
        if isinstance(payload.get("installed"), dict):
            raise ValueError(
                "This is a Desktop app credential. Create a Google OAuth Web application instead."
            )
        raise ValueError("credentials.json must contain a Google OAuth Web application client.")
    return validate_google_client_values(web.get("client_id", ""), web.get("client_secret", ""))


def validate_login_hint(login_hint: str) -> str:
    value = (login_hint or "").strip()
    if len(value) > 320 or "\r" in value or "\n" in value:
        raise ValueError("The Google account hint is invalid.")
    return value


def build_google_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: list[str],
    login_hint: str = "",
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "select_account consent",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{GOOGLE_AUTH_URI}?{urlencode(params)}"


def serialize_google_credentials(
    token_data: dict,
    client_id: str,
    client_secret: str,
    scopes: list[str],
) -> tuple[bytes, bytes, bool]:
    """Build legacy-compatible token.pickle and token.json payloads."""

    if GoogleCredentials is None:
        raise RuntimeError("Google OAuth libraries are unavailable.")
    if not token_data.get("access_token"):
        raise ValueError("Google did not return an access token.")

    expiry = None
    try:
        expires_in = int(token_data.get("expires_in") or 0)
        if expires_in > 0:
            # google-auth 2.17.x expects a naive UTC datetime internally.
            expiry = datetime.now(UTC).replace(tzinfo=None) + timedelta(
                seconds=expires_in
            )
    except (TypeError, ValueError):
        expiry = None

    credentials = GoogleCredentials(
        token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=GOOGLE_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
        expiry=expiry,
    )
    pickle_bytes = pickle_dumps(credentials, protocol=4)
    json_bytes = credentials.to_json().encode("utf-8")
    return pickle_bytes, json_bytes, bool(credentials.refresh_token)


def oauth_state_payload(**values) -> bytes:
    return dumps(values, separators=(",", ":"), sort_keys=True).encode("utf-8")


def parse_oauth_state_payload(data: bytes) -> dict:
    payload = loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid OAuth state payload.")
    return payload


def _fernet(secret: str, purpose: str) -> Fernet:
    if not secret:
        raise RuntimeError("AMATERASU_WEB_SECRET is required for encrypted token storage.")
    material = f"amaterasu:{purpose}:v1:{secret}".encode()
    key = urlsafe_b64encode(sha256(material).digest())
    return Fernet(key)


def protect_blob(data: bytes, secret: str, purpose: str) -> bytes:
    """Encrypt a sensitive database value with a purpose-separated key."""

    return _ENCRYPTED_BLOB_MAGIC + _fernet(secret, purpose).encrypt(bytes(data))


def unprotect_blob(data: bytes, secret: str, purpose: str) -> bytes:
    """Decrypt a protected value while accepting legacy plaintext records."""

    value = bytes(data)
    if not value.startswith(_ENCRYPTED_BLOB_MAGIC):
        return value
    try:
        return _fernet(secret, purpose).decrypt(value[len(_ENCRYPTED_BLOB_MAGIC) :])
    except InvalidToken as exc:
        raise ValueError(
            "The saved token cannot be decrypted. Verify that AMATERASU_WEB_SECRET has not changed."
        ) from exc
