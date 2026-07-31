from asyncio import Lock
from contextlib import asynccontextmanager
from datetime import timedelta
from hashlib import md5 as calculate_md5
from pathlib import Path
from traceback import format_exception
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


def test_terabox_cookie_parser_normalizes_jstoken_alias(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    jar = MagicMock()
    jar.__iter__.return_value = iter(
        [
            SimpleNamespace(name="ndus", value="authenticated"),
            SimpleNamespace(name="jsToken", value="page-token"),
        ]
    )
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    parsed = terabox._read_cookie_file("cookies.txt")

    assert parsed["jstoken"] == "page-token"


def test_terabox_cookie_parser_preserves_regional_domain_hint(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    jar = MagicMock()
    jar.__iter__.return_value = iter(
        [
            SimpleNamespace(
                name="ndus",
                value="authenticated",
                domain=".terabox.com",
            ),
            SimpleNamespace(
                name="captcha_ticket",
                value="challenge",
                domain=".dm.terabox.com",
            ),
        ]
    )
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    parsed = terabox._read_cookie_file("cookies.txt")

    assert parsed.region_hint == "dm"
    assert "region_hint" not in parsed


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


def test_terabox_cookie_parser_rejects_empty_auth_cookie(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    jar = MagicMock()
    jar.__iter__.return_value = iter(
        [SimpleNamespace(name="ndus", value="")]
    )
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    with pytest.raises(terabox.TeraboxError, match="ndus"):
        terabox._read_cookie_file("cookies.txt")


def test_terabox_cookie_parser_redacts_malformed_file(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "should-never-appear"
    jar = MagicMock()
    jar.load.side_effect = ValueError(secret)
    monkeypatch.setattr(terabox, "MozillaCookieJar", lambda _path: jar)

    with pytest.raises(terabox.TeraboxError) as raised:
        terabox._read_cookie_file("cookies.txt")

    assert "Netscape-format" in str(raised.value)
    assert secret not in str(raised.value)
    assert secret not in "".join(
        format_exception(raised.type, raised.value, raised.tb)
    )


def test_terabox_regional_origin_is_validated_and_per_client():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    first = terabox._RegionalAccountClient("", "", object(), cookies=cookies)
    second = terabox._RegionalAccountClient("", "", object(), cookies=cookies)
    alternate = terabox._RegionalAccountClient("", "", object(), cookies=cookies)

    first.account["account_id"] = "cached-account"
    first.is_vip = True
    first._signb = "cached-signature"
    first._public_key = "cached-public-key"
    assert first.use_region("dm")
    assert first._rewrite_url("https://www.terabox.com/api/quota") == (
        "https://dm.terabox.com/api/quota"
    )
    assert first.account["account_id"] is None
    assert first.is_vip is None
    assert first._signb is None
    assert first._public_key is None
    assert second.base_url == "https://www.terabox.com"
    assert alternate.use_region("dm", alternate=True)
    assert alternate.base_url == "https://dm.1024terabox.com"
    assert not first.use_region("dm.example.com")
    assert not first.use_region("../dm")
    second._remember_region("DM")
    assert second.detected_region_prefix == "dm"
    second._remember_region("dm.example.com")
    assert second.detected_region_prefix == "dm"


async def test_terabox_request_captures_region_header_and_rewrites_origin():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class Response:
        def __init__(self, headers):
            self.headers = headers

        def release(self):
            return None

    class Session:
        cookie_jar = ()

        def __init__(self):
            self.calls = []
            self.headers = {"Url-Domain-Prefix": "dm"}

        async def request(self, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            return Response(self.headers)

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    session = Session()
    client = terabox._RegionalAccountClient("", "", session, cookies=cookies)

    async with client._request("GET", "https://www.terabox.com/api/check/login"):
        pass

    assert client.detected_region_prefix == "dm"
    assert client.use_region(client.detected_region_prefix)
    session.headers = {}

    async with client._request("GET", "https://www.terabox.com/api/quota"):
        pass

    _method, url, kwargs = session.calls[-1]
    assert url == "https://dm.terabox.com/api/quota"
    assert kwargs["headers"]["Origin"] == "https://dm.terabox.com"
    assert kwargs["headers"]["Referer"] == "https://dm.terabox.com/main"


async def test_terabox_http_proxy_is_opt_in_and_applied_per_client(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    proxy_url = "http://proxy-user:proxy-pass@proxy.example:8080"
    monkeypatch.setenv("TERABOX_PROXY", proxy_url)

    class Response:
        headers = {}

        def release(self):
            return None

    class Session:
        cookie_jar = ()

        def __init__(self):
            self.kwargs = None

        async def request(self, _method, _url, **kwargs):
            self.kwargs = kwargs
            return Response()

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    session = Session()
    client = terabox._RegionalAccountClient("", "", session, cookies=cookies)

    async with client._request("GET", "https://www.terabox.com/main"):
        pass

    assert session.kwargs["proxy"] == proxy_url

    monkeypatch.setenv("TERABOX_PROXY", "socks5://proxy.example:1080")
    without_socks = terabox._RegionalAccountClient("", "", Session(), cookies=cookies)
    assert without_socks.proxy_url is None


async def test_terabox_corrects_reversed_sdk_upload_limits():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    client = terabox._RegionalAccountClient("", "", object(), cookies=cookies)
    client.check_vip_status = AsyncMock(return_value=False)
    assert await client.get_max_file_size() == 4 * 1024**3

    client.check_vip_status = AsyncMock(return_value=True)
    assert await client.get_max_file_size() == 20 * 1024**3 - 1


async def test_terabox_large_upload_keeps_final_partial_chunk(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    client = terabox._RegionalAccountClient("", "", object(), cookies=cookies)
    content = b"a" * (10 * 1024 * 1024) + b"final-byte"
    source = tmp_path / "remainder.bin"
    source.write_bytes(content)
    captured = {}

    async def capture_chunks(**kwargs):
        captured["upload_host"] = kwargs["upload_host"]
        captured["remote_path"] = kwargs["remote_path"]
        captured["upload_id"] = kwargs["uploadid"]
        captured["chunks"] = [
            (size, digest, Path(path).read_bytes())
            for path, size, digest in kwargs["file_chunks_md5"]
        ]
        return []

    client.get_max_file_size = AsyncMock(return_value=20 * 1024**3 - 1)
    client._locate_upload_host = AsyncMock(return_value="upload.example")
    client._precreate_file = AsyncMock(return_value="upload-id")
    client._upload_chunks = AsyncMock(side_effect=capture_chunks)
    client._postcreate_file = AsyncMock(return_value={"errno": 0, "fs_id": 123})

    result = await client.upload_file(str(source), "/Target/remainder.bin")

    chunks = captured["chunks"]
    assert [size for size, _digest, _data in chunks] == [
        4 * 1024 * 1024,
        4 * 1024 * 1024,
        2 * 1024 * 1024 + len(b"final-byte"),
    ]
    assert b"".join(data for _size, _digest, data in chunks) == content
    assert all(
        digest == calculate_md5(data, usedforsecurity=False).hexdigest()
        for _size, digest, data in chunks
    )
    assert captured["upload_host"] == "upload.example"
    assert captured["remote_path"] == "/Target/remainder.bin"
    assert captured["upload_id"] == "upload-id"
    client._precreate_file.assert_awaited_once()
    client._postcreate_file.assert_awaited_once_with(
        remote_path="/Target/remainder.bin",
        uploadid="upload-id",
        file_size=len(content),
        md5_list_json=[digest for _size, digest, _data in chunks],
    )
    assert result["fs_id"] == 123


async def test_terabox_postcreate_normalizes_root_and_does_not_log_token(caplog):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "synthetic-js-token"
    cookies = {
        "jstoken": secret,
        "csrfToken": "csrf",
        "browserid": "browser",
        "ndus": "authenticated",
    }
    client = terabox._RegionalAccountClient("", "", object(), cookies=cookies)
    captured = []

    class Response:
        async def json(self):
            return {"errno": 0, "fs_id": 123}

    @asynccontextmanager
    async def request(method, url, **kwargs):
        captured.append((method, url, kwargs))
        yield Response()

    client._request = request
    result = await client._postcreate_file(
        "/root.bin",
        "upload-id",
        10,
        ["digest"],
    )

    assert result["fs_id"] == 123
    assert captured[0][2]["data"]["target_path"] == "/"
    assert secret not in caplog.text


async def test_terabox_postcreate_error_exposes_only_code_and_message():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "response-private-field"
    cookies = {
        "jstoken": "page-token",
        "csrfToken": "csrf",
        "browserid": "browser",
        "ndus": "authenticated",
    }
    client = terabox._RegionalAccountClient("", "", object(), cookies=cookies)

    class Response:
        async def json(self):
            return {"errno": 2, "errmsg": "denied", "private": secret}

    @asynccontextmanager
    async def request(_method, _url, **_kwargs):
        yield Response()

    client._request = request

    with pytest.raises(terabox._SdkApiError) as raised:
        await client._postcreate_file(
            "/Folder/file.bin",
            "upload-id",
            10,
            ["digest"],
        )

    assert "errno=2" in str(raised.value)
    assert "message=denied" in str(raised.value)
    assert secret not in str(raised.value)


class _FakeTeraboxSession:
    def __init__(self):
        self.closed = False
        self.close = AsyncMock(side_effect=self._mark_closed)

    def _mark_closed(self):
        self.closed = True


class _FakeAccountClient:
    events = None
    bootstrap_error = None
    validation_error = None
    quota = {"errno": 0, "available": 1}
    regional_retry = False

    def __init__(self, _email, _password, _session, *, cookies):
        self.cookies = cookies
        self.detected_region_prefix = None
        self._ensure_calls = 0

    async def refresh_cookies(self):
        self.events.append("bootstrap")
        if self.bootstrap_error:
            raise self.bootstrap_error
        self.cookies.update(
            {
                "jstoken": "derived-page-token",
                "csrfToken": "derived-csrf-token",
                "browserid": "derived-browser-id",
            }
        )
        return {}

    async def ensure_logged_in(self):
        self.events.append("validate")
        self._ensure_calls += 1
        if self.regional_retry and self._ensure_calls == 1:
            from aioterabox.exceptions import TeraboxUnauthorizedError

            self.detected_region_prefix = "dm"
            raise TeraboxUnauthorizedError("Invalid cookies")
        if self.validation_error:
            raise self.validation_error
        return {}

    async def get_storage_quota(self):
        self.events.append("quota")
        return self.quota

    def use_region(self, prefix, *, alternate=False):
        suffix = ":alternate" if alternate else ""
        self.events.append(f"region:{prefix}{suffix}")
        return prefix == "dm"


def _fake_account_type(**overrides):
    return type(
        "FakeAccountClient",
        (_FakeAccountClient,),
        {
            "events": [],
            "bootstrap_error": None,
            "validation_error": None,
            "quota": {"errno": 0, "available": 1},
            "regional_retry": False,
            **overrides,
        },
    )


async def test_terabox_login_bootstraps_before_authenticated_validation(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    fake_type = _fake_account_type()
    monkeypatch.setattr(terabox, "_RegionalAccountClient", fake_type)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    await client.login()

    assert fake_type.events == ["bootstrap", "validate", "quota"]
    assert all(
        client._client.cookies[key]
        for key in ("jstoken", "csrfToken", "browserid", "ndus")
    )
    await client.aclose()


async def test_terabox_login_rebootstraps_on_detected_regional_host(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    fake_type = _fake_account_type(regional_retry=True)
    monkeypatch.setattr(terabox, "_RegionalAccountClient", fake_type)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    await client.login()

    assert fake_type.events == [
        "bootstrap",
        "validate",
        "region:dm",
        "bootstrap",
        "validate",
        "quota",
    ]
    await client.aclose()


async def test_terabox_login_retries_bootstrap_using_cookie_domain_hint(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class RegionalBootstrapAccount(_FakeAccountClient):
        events = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._bootstrap_calls = 0

        async def refresh_cookies(self):
            self.events.append("bootstrap")
            self._bootstrap_calls += 1
            if self._bootstrap_calls == 1:
                raise TimeoutError("private transport details")
            self.cookies.update(
                {
                    "jstoken": "derived-page-token",
                    "csrfToken": "derived-csrf-token",
                    "browserid": "derived-browser-id",
                }
            )
            return {}

    monkeypatch.setattr(terabox, "_RegionalAccountClient", RegionalBootstrapAccount)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: terabox._CookieData(
            {
                "jstoken": "",
                "csrfToken": "",
                "browserid": "",
                "ndus": "authenticated",
            },
            region_hint="dm",
        ),
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    await client.login()

    assert RegionalBootstrapAccount.events == [
        "bootstrap",
        "region:dm",
        "bootstrap",
        "validate",
        "quota",
    ]
    assert "region_hint" not in client._client.cookies
    await client.aclose()


async def test_terabox_login_uses_alternate_domain_when_regional_network_fails(
    monkeypatch,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class AlternateBootstrapAccount(_FakeAccountClient):
        events = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._bootstrap_calls = 0

        async def refresh_cookies(self):
            self.events.append("bootstrap")
            self._bootstrap_calls += 1
            if self._bootstrap_calls <= 2:
                raise OSError("private regional network details")
            self.cookies.update(
                {
                    "jstoken": "derived-page-token",
                    "csrfToken": "derived-csrf-token",
                    "browserid": "derived-browser-id",
                }
            )
            return {}

    monkeypatch.setattr(terabox, "_RegionalAccountClient", AlternateBootstrapAccount)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: terabox._CookieData(
            {
                "jstoken": "",
                "csrfToken": "",
                "browserid": "",
                "ndus": "authenticated",
            },
            region_hint="dm",
        ),
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    await client.login()

    assert AlternateBootstrapAccount.events == [
        "bootstrap",
        "region:dm",
        "bootstrap",
        "region:dm:alternate",
        "bootstrap",
        "validate",
        "quota",
    ]
    await client.aclose()


async def test_terabox_bootstrap_failure_is_actionable_and_redacted(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "private-cookie-value"
    fake_type = _fake_account_type(bootstrap_error=RuntimeError(secret))
    monkeypatch.setattr(terabox, "_RegionalAccountClient", fake_type)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": secret,
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    with pytest.raises(terabox.TeraboxError) as raised:
        await client.login()

    assert "bootstrap failed" in str(raised.value)
    assert "cookie file was parsed successfully" in str(raised.value)
    assert "aioterabox version" in str(raised.value)
    assert secret not in str(raised.value)
    assert secret not in "".join(
        format_exception(raised.type, raised.value, raised.tb)
    )


async def test_terabox_errno_minus_six_quota_is_not_a_successful_login(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    fake_type = _fake_account_type(quota={"errno": -6, "errmsg": "user not login"})
    monkeypatch.setattr(terabox, "_RegionalAccountClient", fake_type)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    with pytest.raises(terabox.TeraboxError, match="rejected"):
        await client.login()

    assert fake_type.events == ["bootstrap", "validate", "quota"]


async def test_terabox_validation_failure_does_not_expose_sdk_details(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "response-contained-private-value"
    fake_type = _fake_account_type(validation_error=RuntimeError(secret))
    monkeypatch.setattr(terabox, "_RegionalAccountClient", fake_type)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    client._session = _FakeTeraboxSession()

    with pytest.raises(terabox.TeraboxError) as raised:
        await client.login()

    assert "authentication validation failed" in str(raised.value)
    assert secret not in str(raised.value)
    assert secret not in "".join(
        format_exception(raised.type, raised.value, raised.tb)
    )


async def test_terabox_sdk_constructor_failure_closes_session_and_is_redacted(
    monkeypatch,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    secret = "constructor-private-value"

    class BrokenAccountClient:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(secret)

    monkeypatch.setattr(terabox, "_RegionalAccountClient", BrokenAccountClient)
    monkeypatch.setattr(
        terabox,
        "_read_cookie_file",
        lambda _path: {
            "jstoken": "",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    client = terabox.TeraboxClient("cookies.txt")
    session = _FakeTeraboxSession()
    client._session = session

    with pytest.raises(terabox.TeraboxError) as raised:
        await client.login()

    assert session.closed
    assert "authentication validation failed" in str(raised.value)
    assert secret not in "".join(
        format_exception(raised.type, raised.value, raised.tb)
    )


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


async def test_terabox_upload_sdk_failure_is_redacted():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxError

    secret = "sdk-response-private-value"
    account = SimpleNamespace(upload_file=AsyncMock(side_effect=RuntimeError(secret)))
    client = TeraboxClient("cookies.txt")
    client._client = account

    with pytest.raises(TeraboxError) as raised:
        await client.upload_file("one.bin", "/one.bin")

    assert "RuntimeError" in str(raised.value)
    assert secret not in str(raised.value)
    assert secret not in "".join(
        format_exception(raised.type, raised.value, raised.tb)
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
