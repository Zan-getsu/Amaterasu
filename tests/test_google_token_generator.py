"""Focused tests for the per-user Google token generator."""

from __future__ import annotations

import ast
import json
import pickle
import sys
from asyncio import run
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "bot/helper/ext_utils/google_token.py"
SPEC = spec_from_file_location("amaterasu_google_token", MODULE_PATH)
assert SPEC and SPEC.loader
google_token = module_from_spec(SPEC)
SPEC.loader.exec_module(google_token)

GOOGLE_AUTH_URI = google_token.GOOGLE_AUTH_URI
GOOGLE_DRIVE_SCOPE = google_token.GOOGLE_DRIVE_SCOPE
build_google_authorization_url = google_token.build_google_authorization_url
parse_google_credentials_file = google_token.parse_google_credentials_file
parse_google_scopes = google_token.parse_google_scopes
protect_blob = google_token.protect_blob
serialize_google_credentials = google_token.serialize_google_credentials
unprotect_blob = google_token.unprotect_blob
validate_google_client_values = google_token.validate_google_client_values


def test_credentials_json_web_client_is_supported():
    data = json.dumps(
        {
            "web": {
                "client_id": "123.apps.googleusercontent.com",
                "client_secret": "secret-value",
            }
        }
    ).encode()

    assert parse_google_credentials_file(data) == (
        "123.apps.googleusercontent.com",
        "secret-value",
    )


def test_credentials_json_rejects_desktop_client():
    data = json.dumps({"installed": {"client_id": "desktop", "client_secret": "secret"}}).encode()

    with pytest.raises(ValueError, match="Desktop app"):
        parse_google_credentials_file(data)


def test_manual_client_values_are_trimmed_and_validated():
    assert validate_google_client_values("  client-id  ", "  secret  ") == (
        "client-id",
        "secret",
    )
    with pytest.raises(ValueError, match="Client Secret"):
        validate_google_client_values("client-id", "")


def test_scopes_accept_spaces_commas_and_newlines():
    assert parse_google_scopes("") == [GOOGLE_DRIVE_SCOPE]
    assert parse_google_scopes("scope:a,scope:b\nscope:c") == [
        "scope:a",
        "scope:b",
        "scope:c",
    ]


def test_sensitive_blob_encryption_roundtrip_and_legacy_support():
    original = b"private-token-material"
    encrypted = protect_blob(original, "deployment-secret", "token-pickle")

    assert encrypted != original
    assert unprotect_blob(encrypted, "deployment-secret", "token-pickle") == original
    assert unprotect_blob(original, "deployment-secret", "token-pickle") == original
    with pytest.raises(ValueError, match="cannot be decrypted"):
        unprotect_blob(encrypted, "different-secret", "token-pickle")


def test_authorization_url_uses_fixed_google_endpoint_and_offline_consent():
    url = build_google_authorization_url(
        "client-id",
        "https://example.test/app/token-generator/callback",
        "state-value",
        [GOOGLE_DRIVE_SCOPE],
        "user@example.com",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert url.startswith(GOOGLE_AUTH_URI)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["select_account consent"]
    assert query["state"] == ["state-value"]
    assert query["login_hint"] == ["user@example.com"]


def test_private_page_token_is_user_bound_and_expires(monkeypatch):
    from web import security

    monkeypatch.setattr(security, "time", lambda: 1_000)
    token = security.make_signed_token("private-secret", "google-token", 42, ttl=15 * 60)

    assert security.verify_signed_token(token, "private-secret", "google-token", 42)
    assert not security.verify_signed_token(token, "private-secret", "google-token", 43)
    assert not security.verify_signed_token(token, "private-secret", "encode-profile", 42)
    monkeypatch.setattr(security, "time", lambda: 1_901)
    assert not security.verify_signed_token(token, "private-secret", "google-token", 42)


def test_serialized_pickle_is_downloadable_and_contains_refresh_credentials():
    pickle_bytes, json_bytes, has_refresh_token = serialize_google_credentials(
        {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "expires_in": 3600,
        },
        "client-id",
        "client-secret",
        [GOOGLE_DRIVE_SCOPE],
    )

    credentials = pickle.loads(pickle_bytes)
    token_json = json.loads(json_bytes)
    assert b"google.auth._regional_access_boundary_utils" not in pickle_bytes
    assert credentials.refresh_token == "refresh-token"
    assert credentials.client_id == "client-id"
    assert token_json["refresh_token"] == "refresh-token"
    assert has_refresh_token is True


def test_template_has_dual_entry_activation_and_mobile_guards():
    template = (ROOT / "web/templates/token_generator.html").read_text(encoding="utf-8")

    assert "Upload credentials.json" in template
    assert "Enter manually" in template
    assert 'name="credentials_file"' in template
    assert 'name="client_id"' in template
    assert "Use in Amaterasu" in template
    assert template.index("Download token.pickle") < template.index("Use in Amaterasu")
    assert "@media (max-width: 980px)" in template
    assert "@media (max-width: 640px)" in template
    assert "@media (max-width: 380px)" in template
    assert "font-size: 16px" in template
    assert "min-width: 0" in template
    assert "overflow-x: hidden" in template


def test_generation_does_not_replace_the_active_amaterasu_token():
    source = (ROOT / "bot/helper/ext_utils/db_handler.py").read_text(encoding="utf-8")
    web_source = (ROOT / "web/wserver.py").read_text(encoding="utf-8")
    save_generated = source.split("async def save_generated_google_token", 1)[1].split(
        "async def get_generated_google_token", 1
    )[0]
    activate = source.split("async def activate_generated_google_token", 1)[1].split(
        "async def save_encode_profile", 1
    )[0]

    assert "self.db.google_tokens" in save_generated
    assert "self.db.users" not in save_generated
    assert "self.db.users" in activate
    assert '"TOKEN_PICKLE"' in activate
    assert 'update_user_ldata(user_id, "TOKEN_PICKLE", str(token_path))' in web_source


def test_database_state_is_one_time_and_activation_is_explicit(monkeypatch, tmp_path):
    bot_package = ModuleType("bot")
    bot_package.__path__ = [str(ROOT / "bot")]
    bot_package.LOGGER = MagicMock()
    bot_package.qbit_options = {}
    bot_package.rss_dict = {}
    bot_package.user_data = {}
    config_module = ModuleType("bot.core.config_manager")
    config_module.Config = SimpleNamespace(BOT_TOKEN="123456:token", DATABASE_URL="")
    tg_module = ModuleType("bot.core.tg_client")
    tg_module.TgClient = SimpleNamespace(ID=123456, PARTITION="p_token_test")
    tg_module.db_partition_id = lambda _bot_id: "p_token_test"
    secrets_module = ModuleType("bot.helper.ext_utils.secrets")
    secrets_module.get_web_secret = lambda: "database-test-secret"
    monkeypatch.setitem(sys.modules, "bot", bot_package)
    monkeypatch.setitem(sys.modules, "bot.core.config_manager", config_module)
    monkeypatch.setitem(sys.modules, "bot.core.tg_client", tg_module)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.secrets", secrets_module)

    module_path = ROOT / "bot/helper/ext_utils/db_handler.py"
    spec = spec_from_file_location("bot.helper.ext_utils.db_handler", module_path)
    assert spec and spec.loader
    db_module = module_from_spec(spec)
    spec.loader.exec_module(db_module)

    async def exercise_database():
        from mongomock_motor import AsyncMongoMockClient

        class PartitionedCollection:
            def __init__(self, database, prefix):
                self.database = database
                self.prefix = prefix

            def __getitem__(self, partition):
                return self.database[f"{self.prefix}.{partition}"]

        class MotorCompatibleDatabase:
            """Add Motor's collection[subcollection] API to mongomock-motor."""

            def __init__(self, database):
                self.database = database

            def __getattr__(self, name):
                if name == "users":
                    return PartitionedCollection(self.database, name)
                return getattr(self.database, name)

        manager = db_module.DbManager()
        manager._return = False
        manager.db = MotorCompatibleDatabase(AsyncMongoMockClient().amaterasu)
        now = datetime.now(UTC)

        uploaded_token = tmp_path / "uploaded-token.pickle"
        uploaded_token.write_bytes(b"existing-user-token")
        await manager.update_user_doc(42, "TOKEN_PICKLE", uploaded_token)
        uploaded_record = await manager.db.users["p_token_test"].find_one({"_id": 42})
        encrypted_upload = uploaded_record["TOKEN_PICKLE"]
        assert encrypted_upload != b"existing-user-token"
        assert (
            unprotect_blob(encrypted_upload, "database-test-secret", "token-pickle")
            == b"existing-user-token"
        )

        assert await manager.create_google_oauth_state(
            "state-one", 42, b"first", now, now + timedelta(minutes=15)
        )
        assert await manager.create_google_oauth_state(
            "state-two", 42, b"second", now, now + timedelta(minutes=15)
        )
        assert await manager.consume_google_oauth_state("state-one") is None
        consumed = await manager.consume_google_oauth_state("state-two")
        assert consumed["payload"] == b"second"
        assert await manager.consume_google_oauth_state("state-two") is None

        assert await manager.save_generated_google_token(
            42, b"encrypted-one", b"json-one", 101, [GOOGLE_DRIVE_SCOPE], now, True
        )
        generated = await manager.get_generated_google_token(42)
        assert generated["is_active"] is False

        assert await manager.activate_generated_google_token(42, now) == b"encrypted-one"
        generated = await manager.get_generated_google_token(42)
        assert generated["is_active"] is True

        assert await manager.save_generated_google_token(
            42, b"encrypted-two", b"json-two", 102, [GOOGLE_DRIVE_SCOPE], now, True
        )
        generated = await manager.get_generated_google_token(42)
        assert generated["is_active"] is False
        active = await manager.db.users["p_token_test"].find_one({"_id": 42})
        assert active["TOKEN_PICKLE"] == b"encrypted-one"

    run(exercise_database())


def test_google_and_web_dependency_versions_are_current_and_pinned():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "google-auth==2.56.3" in requirements
    assert "google-auth-oauthlib==1.4.0" in requirements
    assert "google-auth-httplib2==0.4.1" in requirements
    assert "google-api-python-client==2.199.0" in requirements
    assert "cryptography>=50.0.0" in requirements
    assert "python-multipart>=0.0.32,<1" in requirements


def test_desktop_flow_uses_loopback_pkce_and_requires_refresh_token(monkeypatch, tmp_path):
    spec = spec_from_file_location(
        "desktop_tokengen", ROOT / "gen_scripts/gen_token_pickle/script.py"
    )
    desktop = module_from_spec(spec)
    spec.loader.exec_module(desktop)
    config = tmp_path / "credentials.json"
    config.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "secret"}}))
    monkeypatch.setattr(desktop, "CREDENTIALS_FILE", config)
    flow = MagicMock()
    flow.run_local_server.return_value = SimpleNamespace(refresh_token="refresh")
    factory = MagicMock(return_value=flow)
    monkeypatch.setattr(desktop.InstalledAppFlow, "from_client_config", factory)
    assert desktop.run_flow().refresh_token == "refresh"
    assert factory.call_args.kwargs == {"autogenerate_code_verifier": True}
    flow.run_local_server.assert_called_once_with(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        timeout_seconds=300,
        access_type="offline",
        prompt="consent",
    )
    flow.run_local_server.return_value.refresh_token = None
    with pytest.raises(ValueError, match="no refresh token"):
        desktop.run_flow()
    config.write_text(json.dumps({"web": {"client_id": "id"}}))
    with pytest.raises(ValueError, match="Desktop app"):
        desktop.run_flow()
    monkeypatch.setattr(
        desktop, "load_token", lambda: SimpleNamespace(valid=True, refresh_token=None)
    )
    replacement = SimpleNamespace(refresh_token="new-refresh")
    monkeypatch.setattr(desktop, "run_flow", lambda: replacement)
    save = MagicMock()
    monkeypatch.setattr(desktop, "save_token", save)
    assert desktop.get_credentials() is replacement
    save.assert_called_once_with(replacement)


def test_desktop_download_is_private_and_contains_only_generator_files(monkeypatch):
    from fastapi import HTTPException, Request
    from fastapi.responses import Response

    from web import security

    # Execute the real route/auth functions without starting external bot services.
    source = ROOT / "web/wserver.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"_require_google_token_user", "_no_store", "google_token_generator_desktop"}
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
    ]
    assert len(nodes) == 3
    for node in nodes:
        node.decorator_list = []
    namespace = {
        "__file__": str(source),
        "Path": Path,
        "Request": Request,
        "Response": Response,
        "HTTPException": HTTPException,
        "_web_secret": lambda: "download-secret",
        "verify_signed_token": security.verify_signed_token,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    monkeypatch.setattr(security, "time", lambda: 1000)
    token = security.make_signed_token("download-secret", "google-token", 42, ttl=900)
    route = namespace["google_token_generator_desktop"]
    request = SimpleNamespace(query_params={"user_id": "42", "token": token})
    response = run(route(request))
    assert "no-store" in response.headers["Cache-Control"]
    assert response.media_type == "application/zip"
    with ZipFile(BytesIO(response.body)) as bundle:
        assert set(bundle.namelist()) == {"script.py", "README.md"}
        assert (
            bundle.read("script.py")
            == (ROOT / "gen_scripts/gen_token_pickle/script.py").read_bytes()
        )
    request.query_params["user_id"] = "43"
    with pytest.raises(HTTPException) as exc:
        run(route(request))
    assert exc.value.status_code == 403
    request.query_params["user_id"] = "42"
    monkeypatch.setattr(security, "time", lambda: 1901)
    with pytest.raises(HTTPException) as exc:
        run(route(request))
    assert exc.value.status_code == 403
