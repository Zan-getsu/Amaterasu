from asyncio import Lock
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_terabox_domains_and_false_positive():
    from bot.helper.ext_utils.links_utils import is_terabox_link

    for domain in (
        "terabox.com",
        "terabox.app",
        "terabox.club",
        "1024terabox.com",
        "nephobox.com",
        "dubox.com",
    ):
        assert is_terabox_link(f"https://{domain}/s/example")
    assert not is_terabox_link("https://example.com/terabox.com/file")
    assert not is_terabox_link(None)


def test_default_upload_normalization():
    from bot.core.config_manager import Config

    assert Config._normalize_default_upload("tb") == "tbx"
    assert Config._normalize_default_upload("TBX") == "tbx"
    assert Config._normalize_default_upload("mega") == "mega"
    assert Config._normalize_default_upload("invalid") == "rc"


def test_stream_bot_tokens_merge_and_deduplicate_helpers():
    """FileToLink merges helper tokens without duplicating explicit workers."""
    from bot.core.config_manager import Config

    previous = (
        Config.BOT_TOKEN,
        Config.HELPER_TOKENS,
        Config.USE_HELPER_BOTS_FOR_FILETOLINK,
        Config.MULTI_TOKENS,
    )
    try:
        Config.BOT_TOKEN = "main"
        Config.HELPER_TOKENS = "helper-a helper-b helper-a main"
        Config.USE_HELPER_BOTS_FOR_FILETOLINK = True
        Config.MULTI_TOKENS = {
            "MULTI_TOKEN10": "stream-b",
            "MULTI_TOKEN2": "helper-a",
            "MULTI_TOKEN1": "stream-a",
            "MULTI_TOKEN3": "",
        }

        assert Config.helper_bot_tokens() == [
            "helper-a",
            "helper-b",
            "main",
        ]
        assert Config.stream_bot_tokens() == [
            "stream-a",
            "helper-a",
            "stream-b",
            "helper-b",
        ]

        Config.USE_HELPER_BOTS_FOR_FILETOLINK = False
        assert Config.stream_bot_tokens() == [
            "stream-a",
            "helper-a",
            "stream-b",
        ]
    finally:
        (
            Config.BOT_TOKEN,
            Config.HELPER_TOKENS,
            Config.USE_HELPER_BOTS_FOR_FILETOLINK,
            Config.MULTI_TOKENS,
        ) = previous


def test_effective_bin_channel_preserves_separate_channel_value():
    """The reuse toggle selects the dump chat without overwriting BIN_CHANNEL."""
    from bot.core.config_manager import Config

    previous = (
        Config.BIN_CHANNEL,
        Config.LEECH_DUMP_CHAT,
        Config.USE_LEECH_DUMP_AS_BIN_CHANNEL,
    )
    try:
        Config.BIN_CHANNEL = -1001
        Config.LEECH_DUMP_CHAT = "-1002"
        Config.USE_LEECH_DUMP_AS_BIN_CHANNEL = False
        assert Config.effective_bin_channel() == -1001

        Config.USE_LEECH_DUMP_AS_BIN_CHANNEL = True
        assert Config.effective_bin_channel() == -1002
        assert Config.BIN_CHANNEL == -1001

        Config.LEECH_DUMP_CHAT = ""
        assert Config.effective_bin_channel() == -1001
    finally:
        (
            Config.BIN_CHANNEL,
            Config.LEECH_DUMP_CHAT,
            Config.USE_LEECH_DUMP_AS_BIN_CHANNEL,
        ) = previous


def test_shared_worker_options_follow_related_settings():
    """Telegram settings preserve the intended discoverable ordering."""
    from bot.core.config_manager import Config

    keys = list(Config.get_all())
    assert keys.index("USE_HELPER_BOTS_FOR_FILETOLINK") == (
        keys.index("HELPER_TOKENS") + 1
    )
    assert keys.index("USE_LEECH_DUMP_AS_BIN_CHANNEL") == (
        keys.index("LEECH_DUMP_CHAT") + 1
    )


@pytest.mark.asyncio
async def test_shared_telegram_client_is_stopped_and_restarted_once():
    """A client assigned to helper and stream roles has one lifecycle call."""
    from bot.core.tg_client import TgClient

    shared = SimpleNamespace(
        stop=AsyncMock(),
        restart=AsyncMock(),
    )

    class IsolatedTgClient(TgClient):
        _lock = Lock()
        bot = shared
        user = None
        helper_bots = {1: shared}
        helper_loads = {1: 0}
        helper_bot_clients = {"token": shared}
        stream_clients = {0: shared, 1: shared}
        stream_loads = {0: 0, 1: 0}
        stream_prewarm = {0: True, 1: True}
        helper_users = {}
        helper_user_loads = {}

    await IsolatedTgClient.reload()
    shared.restart.assert_awaited_once()

    await IsolatedTgClient.stop()
    shared.stop.assert_awaited_once()
    assert IsolatedTgClient.helper_bot_clients == {}
    assert IsolatedTgClient.stream_clients == {}


@pytest.mark.asyncio
async def test_stream_startup_reuses_helper_and_deduplicates_token_pool():
    """Dual-role tokens reuse the helper client while new tokens start once."""
    from bot.core.config_manager import Config
    from bot.core.tg_client import TgClient

    previous = (
        Config.BOT_TOKEN,
        Config.HELPER_TOKENS,
        Config.HELPER_BOT_PROXIES,
        Config.USE_HELPER_BOTS_FOR_FILETOLINK,
        Config.MULTI_TOKENS,
    )
    shared = SimpleNamespace(me=SimpleNamespace(username="shared_helper"))
    fresh = SimpleNamespace(
        me=SimpleNamespace(username="fresh_stream"),
        start=AsyncMock(),
    )
    created_tokens = []

    class IsolatedTgClient(TgClient):
        bot = SimpleNamespace(me=SimpleNamespace(username="main"))
        helper_bot_clients = {"helper-token": shared}
        stream_clients = {}
        stream_loads = {}
        stream_prewarm = {}

        @staticmethod
        def tgClient(_name, *, bot_token, **_kwargs):
            created_tokens.append(bot_token)
            return fresh

        @classmethod
        async def prewarm_stream_clients(cls):
            cls.stream_prewarm = {
                client_id: True for client_id in cls.stream_clients
            }

    try:
        Config.BOT_TOKEN = "main-token"
        Config.HELPER_TOKENS = "helper-token helper-token"
        Config.HELPER_BOT_PROXIES = ""
        Config.USE_HELPER_BOTS_FOR_FILETOLINK = True
        Config.MULTI_TOKENS = {
            "MULTI_TOKEN2": "fresh-token",
            "MULTI_TOKEN1": "helper-token",
        }

        await IsolatedTgClient.start_stream_clients()

        assert IsolatedTgClient.stream_clients == {
            0: IsolatedTgClient.bot,
            1: shared,
            2: fresh,
        }
        assert created_tokens == ["fresh-token"]
        fresh.start.assert_awaited_once()
    finally:
        (
            Config.BOT_TOKEN,
            Config.HELPER_TOKENS,
            Config.HELPER_BOT_PROXIES,
            Config.USE_HELPER_BOTS_FOR_FILETOLINK,
            Config.MULTI_TOKENS,
        ) = previous


def test_qbit_compat_tags_and_seconds():
    from bot.helper.mirror_leech_utils.qbit_compat import (
        TERMINAL_SEED_STATES,
        seconds_value,
        torrent_tags,
    )

    assert torrent_tags(SimpleNamespace(tags=["one", "two"])) == ["one", "two"]
    assert torrent_tags(SimpleNamespace(tags="one, two")) == ["one", "two"]
    assert torrent_tags(SimpleNamespace()) == []
    assert seconds_value(12) == 12
    assert seconds_value(3.9) == 3
    assert seconds_value(timedelta(seconds=9)) == 9
    assert seconds_value(None) == 0
    assert {"stoppedUP", "pausedUP", "stoppedDL", "pausedDL"} <= TERMINAL_SEED_STATES


def test_selector_tokens_are_type_scoped():
    from web.security import make_short_token, verify_short_token

    secret = "selector-test-secret"
    gid = "terabox_abc123"
    token = make_short_token(secret, "torrent-select", gid)
    assert verify_short_token(token, secret, "torrent-select", gid)
    assert not verify_short_token(token, secret, "terabox-select", gid)


def test_amaterasu_terabox_adapter_exports_sdk_surface():
    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import (
        TeraboxCancelled,
        TeraboxClient,
        TeraboxError,
        TeraboxFile,
        TeraboxPasswordError,
    )

    assert TeraboxClient
    assert TeraboxFile
    assert issubclass(TeraboxCancelled, TeraboxError)
    assert issubclass(TeraboxPasswordError, TeraboxError)


def test_terabox_cookie_parser_allows_sdk_refreshable_values(monkeypatch):
    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    cookies = [
        SimpleNamespace(name="ndus", value="authenticated"),
        SimpleNamespace(name="browserid", value="browser"),
    ]
    jar = MagicMock()
    jar.__iter__.return_value = iter(cookies)
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    parsed = terabox._read_cookie_file("cookies.txt")

    assert parsed["ndus"] == "authenticated"
    assert parsed["browserid"] == "browser"
    assert parsed["jstoken"] == ""
    assert parsed["csrfToken"] == ""


def test_terabox_cookie_parser_requires_auth_cookie(monkeypatch):
    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    jar = MagicMock()
    jar.__iter__.return_value = iter([])
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    with pytest.raises(terabox.TeraboxError, match="ndus"):
        terabox._read_cookie_file("cookies.txt")


def test_terabox_multiline_headers_are_split():
    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import _headers_dict

    assert _headers_dict("Cookie: one=1\nReferer: https://terabox.com/") == {
        "Cookie": "one=1",
        "Referer": "https://terabox.com/",
    }


async def test_terabox_upload_creates_parent_once(monkeypatch):
    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient

    account = SimpleNamespace(
        create_directory=AsyncMock(return_value={"errno": 0}),
        upload_file=AsyncMock(return_value={"fs_id": 123}),
    )
    client = TeraboxClient("cookies.txt")
    client._client = account
    monkeypatch.setattr("terabox.os.path.getsize", lambda _path: 10)

    await client.upload_file("one.bin", "/Amaterasu/folder/one.bin")
    await client.upload_file("two.bin", "/Amaterasu/folder/two.bin")

    account.create_directory.assert_awaited_once_with("/Amaterasu/folder")
    assert account.upload_file.await_count == 2


async def test_terabox_upload_cancellation_is_reported():
    import asyncio

    import pytest

    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxCancelled, TeraboxClient

    async def never_finishes(_local, _remote):
        await asyncio.Event().wait()

    account = SimpleNamespace(upload_file=never_finishes)
    client = TeraboxClient("cookies.txt")
    client._client = account
    cancel_event = asyncio.Event()
    cancel_event.set()

    with pytest.raises(TeraboxCancelled, match="cancelled"):
        await client.upload_file(
            "one.bin",
            "/one.bin",
            cancel_event=cancel_event,
        )


@pytest.mark.parametrize(
    "module_name",
    ("web.rclone_selection_store", "web.terabox_selection_store"),
)
def test_selector_store_round_trip_and_rejects_traversal(
    module_name,
    monkeypatch,
    tmp_path,
):
    from importlib import import_module

    store = import_module(module_name)
    monkeypatch.setattr(store, "_BASE_DIR", str(tmp_path))

    assert not store.write_state("../escape", [], [])
    assert store.read_state("../escape") is None
    assert store.write_state(
        "safe_gid",
        [{"id": "1", "name": "one.bin"}],
        ["1"],
    )
    assert store.get_selected_ids("safe_gid") == ["1"]
    assert store.update_selected_ids("safe_gid", [])
    assert store.get_selected_ids("safe_gid") == []
    assert not store.update_selected_ids("safe_gid", ["../outside.bin"])
    assert store.get_selected_ids("safe_gid") == []
    store.delete_state("safe_gid")
    assert store.read_state("safe_gid") is None


def test_terabox_tree_preserves_implicit_folders():
    from web.nodes import make_terabox_tree

    tree = make_terabox_tree(
        [
            {
                "id": "file-1",
                "name": "one.bin",
                "path": "/parent/child/one.bin",
                "size": 5,
                "is_dir": False,
            }
        ]
    )

    parent = tree["files"][0]
    child = parent["children"][0]
    file_node = child["children"][0]
    assert parent["name"] == "parent"
    assert child["name"] == "child"
    assert file_node["id"] == "file-1"
