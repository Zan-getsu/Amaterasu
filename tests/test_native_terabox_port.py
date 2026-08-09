from asyncio import Lock
from contextlib import asynccontextmanager
from datetime import timedelta
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

    assert Config._normalize_default_upload("tb") == "rc"
    assert Config._normalize_default_upload("TBX") == "rc"
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
        __version__,
    )

    assert TeraboxClient
    assert TeraboxFile
    assert issubclass(TeraboxCancelled, TeraboxError)
    assert issubclass(TeraboxPasswordError, TeraboxError)
    assert __version__ == "2.0.3-amaterasu"




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


@pytest.mark.parametrize(
    ("page_token", "expected_token"),
    [
        ("direct-page-token", "direct-page-token"),
        ("prefix%28%22encoded-page-token%22%29", "encoded-page-token"),
    ],
)
def test_terabox_page_auth_parser_supports_current_token_formats(
    page_token,
    expected_token,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    page = (
        '<script>var templateData = {"jsToken":"'
        + page_token
        + '","bdstoken":"write-token","csrf":"csrf-token",'
        '"pcftoken":"pcf-token"};</script>'
    )

    assert terabox._page_auth_data(page) == {
        "jstoken": expected_token,
        "csrfToken": "csrf-token",
    }


def test_terabox_page_auth_parser_supports_encoded_page_fallback():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    page = (
        "prefix window.jsToken%20%3D%20a%7D%3Bfn%28%22"
        "fallback-page-token%22%29 suffix"
    )

    assert terabox._page_auth_data(page) == {
        "jstoken": "fallback-page-token",
        "csrfToken": "",
    }


def test_public_terabox_page_parser_supports_current_template_tokens():
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    page = (
        '<script>var templateData = {"jsToken":'
        '"prefix%28%22mixed-Page_Token%22%29",'
        '"pcftoken":"pcf.Token-2"};</script>'
    )

    assert direct_link_generator._terabox_page_tokens(page) == (
        "mixed-Page_Token",
        "pcf.Token-2",
    )


def test_public_terabox_fallback_error_is_safe_and_actionable():
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    response = SimpleNamespace(
        status_code=503,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    secret_body = "private upstream maintenance page"

    reason = direct_link_generator._terabox_fallback_reason(
        response,
        ValueError(secret_body),
    )

    assert reason == "HTTP 503; non-JSON response"
    assert secret_body not in reason


def test_public_terabox_request_retries_transient_connection_failure(monkeypatch):
    from niquests.exceptions import ConnectionError

    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    response = SimpleNamespace(status_code=200)
    session = SimpleNamespace(
        get=MagicMock(side_effect=[ConnectionError("temporary"), response])
    )
    retry_sleep = MagicMock()
    monkeypatch.setattr(direct_link_generator, "sleep", retry_sleep)

    result = direct_link_generator._terabox_request_with_retry(
        session,
        "get",
        "https://www.terabox.com/sharing/link?surl=example",
        timeout=30,
    )

    assert result is response
    assert session.get.call_count == 2
    retry_sleep.assert_called_once_with(0.5)


def test_public_terabox_request_reports_exhausted_retries(monkeypatch):
    from niquests.exceptions import ConnectionError

    from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    session = SimpleNamespace(
        get=MagicMock(side_effect=ConnectionError("temporary"))
    )
    retry_sleep = MagicMock()
    monkeypatch.setattr(direct_link_generator, "sleep", retry_sleep)

    with pytest.raises(
        DirectDownloadLinkException,
        match=r"failed after 5 attempts \(ConnectionError\)",
    ):
        direct_link_generator._terabox_request_with_retry(
            session,
            "get",
            "https://www.terabox.com/sharing/link?surl=example",
        )

    assert session.get.call_count == 5
    assert [call.args for call in retry_sleep.call_args_list] == [
        (0.5,),
        (1.0,),
        (2.0,),
        (2.0,),
    ]


def test_public_terabox_request_retries_service_unavailable(monkeypatch):
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    unavailable = SimpleNamespace(status_code=503)
    available = SimpleNamespace(status_code=200)
    session = SimpleNamespace(
        get=MagicMock(side_effect=[unavailable, available])
    )
    retry_sleep = MagicMock()
    monkeypatch.setattr(direct_link_generator, "sleep", retry_sleep)

    result = direct_link_generator._terabox_request_with_retry(
        session,
        "get",
        "https://www.terabox.com/sharing/link?surl=example",
    )

    assert result is available
    assert session.get.call_count == 2
    retry_sleep.assert_called_once_with(0.5)


def test_public_terabox_request_reports_exhausted_http_retries(monkeypatch):
    from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    session = SimpleNamespace(
        get=MagicMock(return_value=SimpleNamespace(status_code=503))
    )
    monkeypatch.setattr(direct_link_generator, "sleep", MagicMock())

    with pytest.raises(
        DirectDownloadLinkException,
        match=r"failed after 5 attempts \(HTTP 503\)",
    ):
        direct_link_generator._terabox_request_with_retry(
            session,
            "get",
            "https://www.terabox.com/sharing/link?surl=example",
        )

    assert session.get.call_count == 5


def test_public_terabox_request_does_not_retry_forbidden_response(monkeypatch):
    from bot.helper.mirror_leech_utils.download_utils import direct_link_generator

    response = SimpleNamespace(
        status_code=403,
        json=MagicMock(side_effect=ValueError("forbidden HTML")),
    )
    session = SimpleNamespace(get=MagicMock(return_value=response))
    retry_sleep = MagicMock()
    monkeypatch.setattr(direct_link_generator, "sleep", retry_sleep)

    with pytest.raises(ValueError, match="forbidden HTML"):
        direct_link_generator._terabox_request_with_retry(
            session,
            "get",
            "https://www.terabox.com/api/shorturlinfo",
            expect_json=True,
        )

    session.get.assert_called_once()
    retry_sleep.assert_not_called()


async def test_terabox_refresh_retains_current_page_session_tokens():
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
    captured = []

    class Response:
        async def text(self):
            return (
                '<script>var templateData = {"jsToken":"page-token",'
                '"bdstoken":"write-token","csrf":"csrf-token",'
                '"pcftoken":"pcf-token"};</script>'
            )

    @asynccontextmanager
    async def request(method, url, **kwargs):
        captured.append((method, url, kwargs))
        yield Response()

    client._request = request
    client._session_from_cookie_jar = lambda: {
        "ndus": "authenticated",
        "browserid": "rotated-browser",
    }

    result = await client.refresh_cookies()

    assert client.js_token == "page-token"
    assert client._cookies["csrfToken"] == "csrf-token"
    assert result["cookies"]["browserid"] == "rotated-browser"
    assert captured == [
        (
            "GET",
            "https://www.terabox.com/main",
            {"clean_cookies": False, "timeout": 10},
        )
    ]


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


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.terabox.com/main", "https://www.terabox.com"),
        ("https://dm.terabox.com/main", "https://dm.terabox.com"),
        ("https://dm.1024terabox.com/main", "https://dm.1024terabox.com"),
        ("http://dm.terabox.com/main", None),
        ("https://user@dm.terabox.com/main", None),
        ("https://dm.terabox.com.evil.example/main", None),
        ("https://d.terabox.com/main", None),
    ],
)
def test_terabox_account_response_origin_is_safely_validated(url, expected):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    assert terabox._account_base_url(url) == expected


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


async def test_terabox_request_adopts_safe_final_redirect_origin():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class Response:
        headers = {"logid": "response-log-id"}
        url = "https://dm.1024terabox.com/main"

        def release(self):
            return None

    class Session:
        cookie_jar = ()

        async def request(self, _method, _url, **_kwargs):
            return Response()

    cookies = {
        "jstoken": "",
        "csrfToken": "",
        "browserid": "",
        "ndus": "authenticated",
    }
    client = terabox._RegionalAccountClient("", "", Session(), cookies=cookies)
    assert client.use_region("dm")

    async with client._request("GET", "https://www.terabox.com/main"):
        pass

    assert client.base_url == "https://dm.1024terabox.com"
    assert client._base_headers["Origin"] == "https://dm.1024terabox.com"
    assert client._base_headers["Referer"] == "https://dm.1024terabox.com/main"


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
        "region:dm",
        "bootstrap",
        "region:dm:alternate",
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
            if self._bootstrap_calls == 1:
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
        "region:dm",
        "bootstrap",
        "region:dm:alternate",
        "bootstrap",
        "validate",
        "quota",
    ]
    await client.aclose()


async def test_terabox_login_uses_alternate_domain_when_regional_validation_fails(
    monkeypatch,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class AlternateValidationAccount(_FakeAccountClient):
        events = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        async def refresh_cookies(self):
            self.events.append("bootstrap")
            return {}

        async def ensure_logged_in(self):
            self.events.append("validate")
            self._ensure_calls += 1
            if self._ensure_calls == 1:
                raise OSError("private regional validation details")
            return {}

    monkeypatch.setattr(terabox, "_RegionalAccountClient", AlternateValidationAccount)
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

    assert AlternateValidationAccount.events == [
        "region:dm",
        "bootstrap",
        "validate",
        "region:dm:alternate",
        "bootstrap",
        "validate",
        "quota",
    ]
    await client.aclose()


async def test_terabox_login_uses_alternate_domain_after_regional_auth_rejection(
    monkeypatch,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class AlternateAuthAccount(_FakeAccountClient):
        events = []

        async def refresh_cookies(self):
            self.events.append("bootstrap")
            return {}

        async def ensure_logged_in(self):
            self.events.append("validate")
            self._ensure_calls += 1
            if self._ensure_calls == 1:
                raise terabox._SdkUnauthorizedError("Invalid cookies")
            return {}

    monkeypatch.setattr(terabox, "_RegionalAccountClient", AlternateAuthAccount)
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

    assert AlternateAuthAccount.events == [
        "region:dm",
        "bootstrap",
        "validate",
        "region:dm:alternate",
        "bootstrap",
        "validate",
        "quota",
    ]
    await client.aclose()


async def test_terabox_requests_fresh_cookie_only_after_all_regional_routes_reject(
    monkeypatch,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    class RejectedRegionalAccount(_FakeAccountClient):
        events = []

        async def refresh_cookies(self):
            self.events.append("bootstrap")
            return {}

        async def ensure_logged_in(self):
            self.events.append("validate")
            raise terabox._SdkUnauthorizedError("Invalid cookies")

    monkeypatch.setattr(terabox, "_RegionalAccountClient", RejectedRegionalAccount)
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

    with pytest.raises(terabox.TeraboxError, match="all available account routes"):
        await client.login()

    assert RejectedRegionalAccount.events == [
        "region:dm",
        "bootstrap",
        "validate",
        "region:dm:alternate",
        "bootstrap",
        "validate",
    ]


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


class _DownloadContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class _DownloadResponse:
    request_info = MagicMock()
    history = ()

    def __init__(self, status, chunks=(), headers=None):
        self.status = status
        self.headers = headers or {}
        self.content = _DownloadContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")


class _DownloadSession:
    closed = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.asyncio
async def test_terabox_download_resumes_partial_file_and_finalizes_atomically(
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "episode.bin"
    partial = tmp_path / "episode.bin.part"
    partial.write_bytes(b"abc")
    session = _DownloadSession(
        [
            _DownloadResponse(
                206,
                [b"def"],
                {
                    "Content-Length": "3",
                    "Content-Range": "bytes 3-5/6",
                    "Content-Type": "application/octet-stream",
                },
            )
        ]
    )
    monkeypatch.setenv("TERABOX_PROXY", "http://proxy.example:8080")
    client = TeraboxClient()
    client._session = session
    progress = []

    await client.download_file(
        TeraboxFile("episode.bin", "/episode.bin", "1", size=6, url="https://d.example/file"),
        str(destination),
        progress_cb=lambda done, total: progress.append((done, total)),
    )

    assert destination.read_bytes() == b"abcdef"
    assert not partial.exists()
    assert session.calls[0][1]["headers"]["Range"] == "bytes=3-"
    assert session.calls[0][1]["proxy"] == "http://proxy.example:8080"
    assert progress[-1] == (6, 6)


@pytest.mark.asyncio
async def test_terabox_resume_without_content_range_uses_remaining_length(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "unknown-size.bin"
    partial = tmp_path / "unknown-size.bin.part"
    partial.write_bytes(b"abc")
    client = TeraboxClient()
    client._session = _DownloadSession(
        [
            _DownloadResponse(
                206,
                [b"def"],
                {
                    "Content-Length": "3",
                    "Content-Type": "application/octet-stream",
                },
            )
        ]
    )

    await client.download_file(
        TeraboxFile(
            "unknown-size.bin",
            "/unknown-size.bin",
            "1",
            url="https://d.example/file",
        ),
        str(destination),
    )

    assert destination.read_bytes() == b"abcdef"
    assert not partial.exists()


@pytest.mark.asyncio
async def test_terabox_download_refreshes_expired_direct_link_once(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "fresh.bin"
    session = _DownloadSession(
        [
            _DownloadResponse(403),
            _DownloadResponse(
                200,
                [b"fresh"],
                {
                    "Content-Length": "5",
                    "Content-Type": "application/octet-stream",
                },
            ),
        ]
    )
    client = TeraboxClient()
    client._session = session
    file = TeraboxFile("fresh.bin", "/fresh.bin", "1", size=5, url="https://d.example/expired")

    async def refresh(target):
        target.url = "https://d.example/refreshed"
        return True

    client._refresh_file_url = AsyncMock(side_effect=refresh)

    await client.download_file(file, str(destination))

    assert destination.read_bytes() == b"fresh"
    assert [call[0] for call in session.calls] == [
        "https://d.example/expired",
        "https://d.example/refreshed",
    ]
    client._refresh_file_url.assert_awaited_once_with(file)


@pytest.mark.asyncio
async def test_terabox_download_refreshes_direct_link_after_connection_failure(
    monkeypatch,
    tmp_path,
):
    aiohttp = pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    destination = tmp_path / "reconnected.bin"
    session = _DownloadSession(
        [
            aiohttp.ServerDisconnectedError(),
            _DownloadResponse(
                200,
                [b"fresh"],
                {
                    "Content-Length": "5",
                    "Content-Type": "application/octet-stream",
                },
            ),
        ]
    )
    client = terabox.TeraboxClient()
    client._session = session
    file = terabox.TeraboxFile(
        "reconnected.bin",
        "/reconnected.bin",
        "1",
        size=5,
        url="https://d.example/stale",
    )

    async def refresh(target):
        target.url = "https://d.example/refreshed"
        return True

    client._refresh_file_url = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(terabox, "sleep", AsyncMock())

    await client.download_file(file, str(destination))

    assert destination.read_bytes() == b"fresh"
    assert [call[0] for call in session.calls] == [
        "https://d.example/stale",
        "https://d.example/refreshed",
    ]
    client._refresh_file_url.assert_awaited_once_with(file)


@pytest.mark.asyncio
async def test_terabox_download_retries_incomplete_responses_without_publishing(
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    responses = [
        _DownloadResponse(
            200,
            [b"bad"],
            {"Content-Length": "3", "Content-Type": "application/octet-stream"},
        )
        for _ in range(4)
    ]
    client = terabox.TeraboxClient()
    client._session = _DownloadSession(responses)
    client._refresh_file_url = AsyncMock(return_value=False)
    monkeypatch.setattr(terabox, "sleep", AsyncMock())
    destination = tmp_path / "incomplete.bin"

    with pytest.raises(terabox.TeraboxError, match="after 4 attempts"):
        await client.download_file(
            terabox.TeraboxFile(
                "incomplete.bin",
                "/incomplete.bin",
                "1",
                size=10,
                url="https://d.example/truncated",
            ),
            str(destination),
        )

    assert not destination.exists()
    assert (tmp_path / "incomplete.bin.part").read_bytes() == b"bad"
    assert len(client._session.calls) == 4


@pytest.mark.asyncio
async def test_terabox_account_download_sends_authenticated_cookies(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "account.bin"
    session = _DownloadSession(
        [
            _DownloadResponse(
                200,
                [b"account"],
                {
                    "Content-Length": "7",
                    "Content-Type": "application/octet-stream",
                },
            )
        ]
    )
    client = TeraboxClient()
    client._session = session
    client._client = SimpleNamespace(
        request_cookies={"ndus": "authenticated", "lang": "en"},
        _base_headers={
            "User-Agent": "account-agent",
            "Referer": "https://dm.1024terabox.com/main",
        },
        base_url="https://dm.1024terabox.com",
    )

    await client.download_file(
        TeraboxFile(
            "account.bin",
            "/account.bin",
            "1",
            size=7,
            url="https://d.terabox.com/file/account",
        ),
        str(destination),
    )

    request = session.calls[0][1]
    assert destination.read_bytes() == b"account"
    assert request["cookies"] == {"ndus": "authenticated", "lang": "en"}
    assert request["headers"]["User-Agent"] == "account-agent"
    assert request["headers"]["Referer"] == "https://dm.1024terabox.com/main"
    assert request["headers"]["Accept-Encoding"] == "identity"


@pytest.mark.asyncio
async def test_terabox_account_listing_fetches_every_page(monkeypatch):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    client = terabox._RegionalAccountClient(
        "",
        "",
        MagicMock(),
        cookies={
            "jstoken": "token",
            "csrfToken": "",
            "browserid": "",
            "ndus": "authenticated",
        },
    )
    pages = []

    @asynccontextmanager
    async def request(_method, _url, **kwargs):
        page = int(kwargs["params"]["page"])
        pages.append(page)
        items = (
            [
                {
                    "server_filename": "one.bin",
                    "path": "/one.bin",
                    "fs_id": 1,
                    "size": 1,
                    "isdir": 0,
                },
                {
                    "server_filename": "two.bin",
                    "path": "/two.bin",
                    "fs_id": 2,
                    "size": 2,
                    "isdir": 0,
                },
            ]
            if page == 1
            else [
                {
                    "server_filename": "three.bin",
                    "path": "/three.bin",
                    "fs_id": 3,
                    "size": 3,
                    "isdir": 0,
                }
            ]
        )
        yield SimpleNamespace(json=AsyncMock(return_value={"errno": 0, "list": items}))

    monkeypatch.setattr(terabox, "_ACCOUNT_PAGE_SIZE", 2)
    client._request = request

    entries = await client.list_remote_directory("/")

    assert pages == [1, 2]
    assert [entry.name for entry in entries] == ["one.bin", "two.bin", "three.bin"]


@pytest.mark.asyncio
async def test_terabox_complete_partial_finalizes_without_network(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "complete.bin"
    partial = tmp_path / "complete.bin.part"
    partial.write_bytes(b"done")
    client = TeraboxClient()
    client._session = _DownloadSession([])

    await client.download_file(
        TeraboxFile(
            "complete.bin",
            "/complete.bin",
            "1",
            size=4,
            url="https://d.example/file",
        ),
        str(destination),
    )

    assert destination.read_bytes() == b"done"
    assert not partial.exists()
    assert client._session.calls == []


@pytest.mark.asyncio
async def test_terabox_oversized_partial_restarts_cleanly(tmp_path):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    from terabox import TeraboxClient, TeraboxFile

    destination = tmp_path / "oversized.bin"
    partial = tmp_path / "oversized.bin.part"
    partial.write_bytes(b"stale-data")
    client = TeraboxClient()
    client._session = _DownloadSession(
        [
            _DownloadResponse(
                200,
                [b"new"],
                {
                    "Content-Length": "3",
                    "Content-Type": "application/octet-stream",
                },
            )
        ]
    )

    await client.download_file(
        TeraboxFile(
            "oversized.bin",
            "/oversized.bin",
            "1",
            size=3,
            url="https://d.example/file",
        ),
        str(destination),
    )

    assert destination.read_bytes() == b"new"
    assert "Range" not in client._session.calls[0][1]["headers"]


@pytest.mark.asyncio
async def test_terabox_mismatched_resume_range_restarts_from_zero(
    monkeypatch,
    tmp_path,
):
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    destination = tmp_path / "range.bin"
    partial = tmp_path / "range.bin.part"
    partial.write_bytes(b"abc")
    client = terabox.TeraboxClient()
    client._session = _DownloadSession(
        [
            _DownloadResponse(
                206,
                [b"wrong"],
                {
                    "Content-Length": "3",
                    "Content-Range": "bytes 0-2/6",
                    "Content-Type": "application/octet-stream",
                },
            ),
            _DownloadResponse(
                200,
                [b"abcdef"],
                {
                    "Content-Length": "6",
                    "Content-Type": "application/octet-stream",
                },
            ),
        ]
    )
    client._refresh_file_url = AsyncMock(return_value=False)
    monkeypatch.setattr(terabox, "sleep", AsyncMock())

    await client.download_file(
        terabox.TeraboxFile(
            "range.bin",
            "/range.bin",
            "1",
            size=6,
            url="https://d.example/file",
        ),
        str(destination),
    )

    assert destination.read_bytes() == b"abcdef"
    assert client._session.calls[0][1]["headers"]["Range"] == "bytes=3-"
    assert "Range" not in client._session.calls[1][1]["headers"]


@pytest.mark.asyncio
async def test_terabox_public_resolver_blocks_private_download_url():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    client = terabox.TeraboxClient()
    client._session = _DownloadSession([])

    with pytest.raises(terabox.TeraboxError, match="blocked private"):
        await client._normalize_resolved("http://127.0.0.1/internal")


@pytest.mark.asyncio
async def test_terabox_account_dlink_rejects_untrusted_cookie_target():
    pytest.importorskip("aiohttp")
    pytest.importorskip("aioterabox")
    import terabox

    client = terabox.TeraboxClient()
    client._client = SimpleNamespace(
        get_files_meta=AsyncMock(
            return_value=[{"dlink": "https://attacker.example/collect"}]
        )
    )

    with pytest.raises(terabox.TeraboxError, match="untrusted account"):
        await client._account_download_url(
            terabox.TeraboxFile("private.bin", "/private.bin", "1")
        )
