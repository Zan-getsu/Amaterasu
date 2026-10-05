#!/usr/bin/env python3
"""
Generate Google Drive OAuth Token

This script authenticates with Google Drive API and generates a token file
for use with other Google Drive-related scripts.
"""

import pickle
import sys
from argparse import ArgumentParser
from json import loads
from os.path import exists
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_FILE = Path(__file__).resolve().parents[1] / "config/credentials.json"
TOKEN_FILE = Path(__file__).resolve().parents[1] / "tokens/token.pickle"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
_MISSING = object()


def dump_legacy_compatible_credentials(creds, file_obj) -> None:
    """Write a token that older google-auth clients can still unpickle."""
    rab_manager = getattr(creds, "_rab_manager", _MISSING)
    if rab_manager is not _MISSING:
        creds._rab_manager = None
    try:
        pickle.dump(creds, file_obj, protocol=4)
    finally:
        if rab_manager is not _MISSING:
            creds._rab_manager = rab_manager


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)


def print_step(step: int, total: int, message: str) -> None:
    """Print a step indicator."""
    print(f"\n[{step}/{total}] {message}")


def load_token() -> pickle:
    """Load existing token from file."""
    if not exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def save_token(creds) -> None:
    """Save credentials to token file."""
    try:
        Path(TOKEN_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(TOKEN_FILE, "wb") as f:
            dump_legacy_compatible_credentials(creds, f)
        print(f"\n[OK] Token saved to: {TOKEN_FILE}")
    except Exception as e:
        print(f"\n[ERROR] Failed to save token: {e}")
        sys.exit(1)


def refresh_token(creds) -> pickle:
    """Refresh expired credentials."""
    try:
        creds.refresh(Request())
        return creds
    except Exception:
        return None


def run_flow():
    """Authorize on the user's computer with a loopback callback and PKCE."""
    if not exists(CREDENTIALS_FILE):
        print("\n[ERROR] credentials.json not found!")
        print(f"\nPlease ensure '{CREDENTIALS_FILE}' exists.")
        print("\nTo get credentials:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project or select existing")
        print("3. Enable Google Drive API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download and save as 'credentials.json'")
        sys.exit(1)

    print("\n[INFO] Starting OAuth authentication...")
    config = loads(Path(CREDENTIALS_FILE).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("installed"), dict):
        raise ValueError("Use a Google OAuth Desktop app credentials.json for this script.")
    flow = InstalledAppFlow.from_client_config(config, SCOPES, autogenerate_code_verifier=True)
    creds = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        timeout_seconds=300,
        access_type="offline",
        prompt="consent",
    )
    if not creds.refresh_token:
        raise ValueError("Google returned no refresh token. Revoke the app's access and try again.")
    return creds


def get_credentials():
    """Get valid credentials, refreshing or regenerating if needed."""
    print_header("Google Drive Token Generator")

    # Step 1: Check for existing token
    print_step(1, 3, "Checking for existing token...")
    creds = load_token()
    if creds and (not creds.refresh_token or not creds.has_scopes(SCOPES)):
        creds = None

    if creds and creds.valid:
        print("[OK] Valid token found!")
        return creds

    # Step 2: Check if token can be refreshed
    if creds and creds.expired and creds.refresh_token:
        print("[INFO] Token expired. Attempting to refresh...")
        creds = refresh_token(creds)
        if creds:
            print("[OK] Token refreshed successfully!")
            save_token(creds)
            return creds

    # Step 3: Generate new token
    print_step(2, 3, "Generating new token...")
    creds = run_flow()
    save_token(creds)
    return creds


def main():
    global CREDENTIALS_FILE, TOKEN_FILE, SCOPES
    parser = ArgumentParser(description="Generate a Google OAuth Desktop app token locally.")
    parser.add_argument("--credentials", type=Path, default=CREDENTIALS_FILE)
    parser.add_argument("--output", type=Path, default=TOKEN_FILE)
    parser.add_argument("--scopes", nargs="+", default=SCOPES)
    args = parser.parse_args()
    CREDENTIALS_FILE, TOKEN_FILE, SCOPES = args.credentials, args.output, args.scopes
    try:
        print("\nThis script will authenticate with Google Drive API")
        print("and save a token for future use.\n")
        print("Google External/Testing projects issue refresh tokens that expire after 7 days.")
        print("Use In production for longer-lived access; Desktop alone does not change expiry.")

        creds = get_credentials()

        print_step(3, 3, "Verification")
        if creds and creds.valid:
            print("\n" + "=" * 50)
            print("  SUCCESS! Token generated and saved.")
            print("=" * 50)
            print(f"\nToken location: {TOKEN_FILE}")
            print("\nYou can now use other scripts that require Google Drive access.")
        else:
            print("\n[ERROR] Failed to obtain valid credentials")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n[INFO] Cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
