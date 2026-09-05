"""Focused checks for the private Telegram session generator."""

from __future__ import annotations

import sys
from asyncio import run
from datetime import UTC, datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = spec_from_file_location(name, path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


telegram_session = _load_module(
    "amaterasu_telegram_session",
    ROOT / "bot/helper/ext_utils/telegram_session.py",
)
google_token = _load_module(
    "amaterasu_google_token_for_session",
    ROOT / "bot/helper/ext_utils/google_token.py",
)


def test_session_input_validation_accepts_friendly_formats():
    assert telegram_session.validate_telegram_api_credentials(
        " 123456 ", "0123456789ABCDEF0123456789ABCDEF"
    ) == (123456, "0123456789abcdef0123456789abcdef")
    assert telegram_session.normalize_phone_number("+1 (415) 456-6376") == "+14154566376"
    assert telegram_session.normalize_login_code("1 2 3 4 5") == "12345"
    assert telegram_session.validate_two_step_password("correct horse") == "correct horse"


@pytest.mark.parametrize(
    ("function", "value"),
    [
        (telegram_session.normalize_phone_number, "415-456-6376"),
        (telegram_session.normalize_login_code, "12AB5"),
        (telegram_session.validate_two_step_password, ""),
    ],
)
def test_session_input_validation_rejects_unsafe_values(function, value):
    with pytest.raises(ValueError):
        function(value)


def test_session_command_replaces_exportsession_and_is_authorized():
    commands = (ROOT / "bot/helper/telegram_helper/bot_commands.py").read_text(
        encoding="utf-8"
    )
    module_source = (ROOT / "bot/modules/gen_pyro_sess.py").read_text(
        encoding="utf-8"
    )
    handler_source = (ROOT / "bot/core/handlers.py").read_text(encoding="utf-8")
    command_handler = handler_source.split(
        "filters=command(BotCommands.GenPyroSessCommand", 1
    )[1].split(")", 2)[1]

    assert '"GenPyroSess": "sessiongen"' in commands
    assert "exportsession" not in commands
    assert "CustomFilters.authorized" in command_handler
    assert "CustomFilters.sudo" not in command_handler
    assert "ChatType.PRIVATE" in module_source


def test_private_page_uses_user_bound_expiring_token(monkeypatch):
    from web import security

    monkeypatch.setattr(security, "time", lambda: 1_000)
    token = security.make_signed_token(
        "private-secret", "telegram-session", 42, ttl=15 * 60
    )

    assert security.verify_signed_token(
        token, "private-secret", "telegram-session", 42
    )
    assert not security.verify_signed_token(
        token, "private-secret", "telegram-session", 43
    )
    assert not security.verify_signed_token(token, "private-secret", "google-token", 42)
    monkeypatch.setattr(security, "time", lambda: 1_901)
    assert not security.verify_signed_token(
        token, "private-secret", "telegram-session", 42
    )


def test_session_page_has_complete_secure_responsive_flow():
    template = (ROOT / "web/templates/session_generator.html").read_text(
        encoding="utf-8"
    )

    assert "/api/session-generator/start" in template
    assert "/api/session-generator/verify" in template
    assert "/api/session-generator/password" in template
    assert "/api/session-generator/cancel" in template
    assert "/api/session-generator/copy" in template
    assert 'name="api_id"' in template
    assert 'name="api_hash"' in template
    assert "uses_config_credentials" not in template
    assert "Replace saved session" not in template
    assert 'id="replace-session"' not in template
    assert 'autocomplete="one-time-code"' in template
    assert 'autocomplete="current-password"' in template
    assert "Saved Messages" in template
    assert "decrypted only when you press Copy" in template
    assert 'data-copy-session="{{ saved.session_id }}"' in template
    assert "{{ session_string" not in template
    assert "@media (max-width: 980px)" in template
    assert "@media (max-width: 640px)" in template
    assert "@media (max-width: 380px)" in template
    assert "prefers-reduced-motion" in template
    assert ":active:not(:disabled)" in template
    assert "transition: all" not in template
    assert "—" not in template
    assert "–" not in template


def test_session_start_always_uses_user_supplied_api_credentials():
    server = (ROOT / "web/wserver.py").read_text(encoding="utf-8")
    session_start = server.split(
        '@app.post("/api/session-generator/start")', 1
    )[1].split('@app.post("/api/session-generator/verify")', 1)[0]

    assert "config.TELEGRAM_API" not in session_start
    assert "config.TELEGRAM_HASH" not in session_start
    assert "validate_telegram_api_credentials(\n            api_id,\n            api_hash," in session_start


@pytest.mark.parametrize("step", ["details", "code", "password"])
def test_session_page_renders_each_authentication_state(step):
    environment = Environment(
        loader=FileSystemLoader(ROOT / "web/templates"),
        autoescape=select_autoescape(),
    )
    rendered = environment.get_template("session_generator.html").render(
        user_id=42,
        page_token="private-page-token",
        step=step,
        attempt_id="private-attempt-token",
        phone_hint="+14*****6376",
        password_hint="<not markup>",
        session_history=[],
        error="",
        success=False,
    )

    assert "Telegram Session Generator" in rendered
    assert "private-page-token" in rendered
    if step == "password":
        assert "&lt;not markup&gt;" in rendered


def test_database_updates_current_session_and_keeps_encrypted_history(monkeypatch):
    bot_package = ModuleType("bot")
    bot_package.__path__ = [str(ROOT / "bot")]
    bot_package.LOGGER = MagicMock()
    bot_package.qbit_options = {}
    bot_package.rss_dict = {}
    bot_package.user_data = {}
    config_module = ModuleType("bot.core.config_manager")
    config_module.Config = SimpleNamespace(BOT_TOKEN="123456:token", DATABASE_URL="")
    tg_module = ModuleType("bot.core.tg_client")
    tg_module.TgClient = SimpleNamespace(ID=123456, PARTITION="p_session_test")
    tg_module.db_partition_id = lambda _bot_id: "p_session_test"
    monkeypatch.setitem(sys.modules, "bot", bot_package)
    monkeypatch.setitem(sys.modules, "bot.core.config_manager", config_module)
    monkeypatch.setitem(sys.modules, "bot.core.tg_client", tg_module)

    db_module = _load_module(
        "bot.helper.ext_utils.db_handler_session_test",
        ROOT / "bot/helper/ext_utils/db_handler.py",
    )

    async def exercise_database():
        from mongomock_motor import AsyncMongoMockClient

        manager = db_module.DbManager()
        manager._return = False
        manager.db = AsyncMongoMockClient().amaterasu
        now = datetime.now(UTC)
        first = google_token.protect_blob(
            b"first-session", "database-test-secret", "telegram-session"
        )
        second = google_token.protect_blob(
            b"second-session", "database-test-secret", "telegram-session"
        )

        assert await manager.save_generated_telegram_session(
            42, "session-1", first, 1001, "First Account", "first", False, now
        )
        assert await manager.save_generated_telegram_session(
            42, "session-2", second, 1002, "Second Account", "second", True, now
        )
        record = await manager.get_generated_telegram_session(42)

        assert await manager.db.telegram_sessions.count_documents({}) == 1
        assert record["current_session_id"] == "session-2"
        assert record["telegram_user_id"] == 1002
        assert record["username"] == "second"
        assert record["is_premium"] is True
        assert [item["session_id"] for item in record["history"]] == [
            "session-2",
            "session-1",
        ]
        assert google_token.unprotect_blob(
            record["session_string"], "database-test-secret", "telegram-session"
        ) == b"second-session"
        first_saved = await manager.get_generated_telegram_session_value(
            42, "session-1"
        )
        assert google_token.unprotect_blob(
            first_saved, "database-test-secret", "telegram-session"
        ) == b"first-session"
        other_user = google_token.protect_blob(
            b"other-user-session", "database-test-secret", "telegram-session"
        )
        assert await manager.save_generated_telegram_session(
            43, "session-1", other_user, 2001, "Other User", "other", False, now
        )
        isolated = await manager.get_generated_telegram_session_value(42, "session-1")
        assert google_token.unprotect_blob(
            isolated, "database-test-secret", "telegram-session"
        ) == b"first-session"
        assert await manager.get_generated_telegram_session_value(42, "missing") is None

    run(exercise_database())
