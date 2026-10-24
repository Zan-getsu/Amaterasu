"""Regression coverage for HTTP probing, compatibility retries, and cancellation."""

import ast
import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from re import compile as re_compile
from re import match as re_match
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlparse

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
COLOROS_URL = (
    "https://downgradefs.coloros.com/downgrade/26/08/31/2ba1d8a90ed84f59b145c68b51de9353.zip"
)


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
        or isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_BROWSER_USER_AGENT"
            for target in node.targets
        )
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def helpers():
    return load_functions(
        "bot/helper/ext_utils/bot_utils.py",
        {
            "get_download_user_agent",
            "get_content_info",
            "get_filename_from_headers",
            "parse_download_headers",
            "get_aria2_retry_options",
        },
        {
            "urlparse": urlparse,
            "unquote": unquote,
            "re_compile": re_compile,
            "RequestError": httpx.RequestError,
        },
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file.zip",
        "https://www.coloros.com/file.zip",
        "https://downgradefs.coloros.com.example.com/file.zip",
        "https://example.com/downgradefs.coloros.com/file.zip",
    ],
)
def test_other_hosts_keep_browser_user_agent(helpers, url):
    assert helpers["get_download_user_agent"](url) == helpers["DEFAULT_BROWSER_USER_AGENT"]


@pytest.mark.asyncio
@pytest.mark.parametrize("head_status", [200, 405])
async def test_coloros_metadata_probe_uses_download_user_agent(helpers, head_status):
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "HEAD" and head_status == 405:
            return httpx.Response(405)
        if request.headers["user-agent"] == "aria2":
            return httpx.Response(200, headers={"Content-Type": "application/zip"})
        return httpx.Response(403, headers={"Content-Type": "text/html"})

    helpers["Config"] = SimpleNamespace(INSECURE_HOSTS=[])
    helpers["AsyncClient"] = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    content_type, filename = await helpers["get_content_info"](COLOROS_URL)

    assert content_type == "application/zip"
    assert filename == "2ba1d8a90ed84f59b145c68b51de9353.zip"
    assert [request.method for request in requests] == (
        ["HEAD"] if head_status == 200 else ["HEAD", "GET"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "header", "expected_agent"),
    [
        (COLOROS_URL, "", "aria2"),
        ("https://example.com/file.zip", "", "browser"),
        (COLOROS_URL, "User-Agent: custom-client\nReferer: https://example.com/", None),
    ],
)
async def test_aria2_options_use_host_agent_and_preserve_explicit_headers(
    helpers, url, header, expected_agent
):
    add_uri = AsyncMock(side_effect=RuntimeError("Stop after recording download options"))
    namespace = load_functions(
        "bot/helper/mirror_leech_utils/download_utils/aria2_download.py",
        {"add_aria2_download", "_sourceforge_filename"},
        {
            "get_download_user_agent": helpers["get_download_user_agent"],
            "parse_download_headers": helpers["parse_download_headers"],
            "Config": SimpleNamespace(DISABLE_TORRENTS=False, TORRENT_TIMEOUT=0),
            "check_running_tasks": AsyncMock(return_value=(False, None)),
            "aiopath": SimpleNamespace(exists=AsyncMock(return_value=False)),
            "TorrentManager": SimpleNamespace(aria2=SimpleNamespace(addUri=add_uri)),
            "LOGGER": logging.getLogger(__name__),
            "ClientError": httpx.HTTPError,
            "urlparse": urlparse,
            "unquote": unquote,
        },
    )
    listener = SimpleNamespace(link=url, name="", is_stream=False)
    await namespace["add_aria2_download"](
        listener, "/downloads/test", header, None, None, notify_error=False
    )
    options = add_uri.call_args.kwargs["options"]

    if expected_agent == "browser":
        expected_agent = helpers["DEFAULT_BROWSER_USER_AGENT"]
    assert options.get("user-agent") == expected_agent
    if header:
        assert helpers["parse_download_headers"](options["header"]) == helpers[
            "parse_download_headers"
        ](header)


@pytest.mark.parametrize(
    "headers",
    [
        "Authorization: Bearer abc\nuser-agent: custom\nReferer: https://example.com/a:b",
        "Authorization: Bearer abc\\nuser-agent: custom\\nReferer: https://example.com/a:b",
        ["Authorization: Bearer abc", "user-agent: custom", "Referer: https://example.com/a:b"],
        {
            "Authorization": "Bearer abc",
            "User-Agent": "custom",
            "Referer": "https://example.com/a:b",
        },
    ],
)
def test_custom_headers_keep_values_and_normalize_names(helpers, headers):
    assert helpers["parse_download_headers"](headers) == {
        "authorization": "Bearer abc",
        "user-agent": "custom",
        "referer": "https://example.com/a:b",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("head_status", [400, 403, 404, 405, 406, 501, "disconnect"])
async def test_failed_head_uses_streamed_get_with_same_credentials(helpers, head_status):
    seen = []
    closed = []

    class HeadersOnly(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("Metadata probe must not download the file body")
            yield b""

        async def aclose(self):
            closed.append(True)

    def respond(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer abc"
        assert request.headers["user-agent"] == "custom"
        if request.method == "HEAD":
            if head_status == "disconnect":
                raise httpx.RemoteProtocolError("HEAD disconnected", request=request)
            return httpx.Response(head_status)
        return httpx.Response(
            200, headers={"Content-Type": "application/zip"}, stream=HeadersOnly()
        )

    helpers["Config"] = SimpleNamespace(INSECURE_HOSTS=[])
    helpers["AsyncClient"] = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), **kwargs
    )
    assert await helpers["get_content_info"](
        "https://example.com/file.zip", "Authorization: Bearer abc\nUSER-AGENT: custom"
    ) == ("application/zip", "file.zip")
    assert [request.method for request in seen] == ["HEAD", "GET"]
    assert closed == [True]


@pytest.mark.asyncio
async def test_probe_does_not_present_error_page_as_file_metadata(helpers):
    helpers["Config"] = SimpleNamespace(INSECURE_HOSTS=[])
    helpers["AsyncClient"] = lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(403, headers={"Content-Type": "text/html"})
        ),
        **kwargs,
    )
    assert await helpers["get_content_info"]("https://example.com/file.zip") == (None, "")


@pytest.mark.parametrize(
    "error",
    [
        "status=403",
        "HTTP 406",
        "HTTP 416",
        "HTTP 429",
        "HTTP 503",
        "Timeout",
        "Connection reset",
        "Could not resolve host",
        "Name resolution failed",
    ],
)
def test_retry_profile_reduces_connections_and_is_bounded(helpers, error):
    options = helpers["get_aria2_retry_options"]("https://example.com/a.zip", error)
    assert options["split"] == options["max-connection-per-server"] == "1"
    assert options["max-tries"] == "3"
    if "403" in error or "406" in error:
        assert options["user-agent"] == "aria2"
    if "resolve" in error.lower() or "resolution" in error.lower():
        assert options["async-dns"] == "false"


@pytest.mark.parametrize(
    "url,error,completed",
    [
        ("https://example.com/a.zip", "HTTP 403", 1),
        ("https://example.com/a.zip", "HTTP 404", 0),
        ("https://example.com/a.zip", "HTTP 401", 0),
        ("https://example.com/a.zip", "Not enough disk space", 0),
        ("magnet:?xt=urn:btih:abc", "HTTP 503", 0),
        ("ftp://example.com/a.zip", "HTTP 403", 0),
    ],
)
def test_retry_profile_leaves_partial_data_permanent_failures_and_torrents_alone(
    helpers, url, error, completed
):
    assert helpers["get_aria2_retry_options"](url, error, completed) == {}


def test_retry_does_not_override_explicit_user_agent(helpers):
    assert "user-agent" not in helpers["get_aria2_retry_options"](
        "https://example.com/a.zip", "HTTP 403", 0, "USER-AGENT: custom"
    )


def load_method(path, class_name, method_name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(node for node in cls.body if getattr(node, "name", "") == method_name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, "exec"), namespace)
    return namespace[method_name]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_during_wait", [False, True])
async def test_cancelled_download_does_not_restart_or_invoke_fallback(helpers, cancel_during_wait):
    listener = SimpleNamespace(
        is_cancelled=not cancel_during_wait,
        link=COLOROS_URL,
        aria2_fallback_error="HTTP 403",
        aria2_fallback_completed=0,
    )

    async def wait(_):
        listener.is_cancelled = True

    add = AsyncMock()
    metadata = AsyncMock()
    retry = load_method(
        "bot/modules/mirror_leech.py",
        "Mirror",
        "_retry_aria2_or_ytdlp",
        {
            "sleep": wait,
            "get_aria2_retry_options": helpers["get_aria2_retry_options"],
            "add_aria2_download": add,
            "get_content_info": metadata,
        },
    )
    await retry(listener, "/downloads")
    add.assert_not_awaited()
    metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_download_never_automatically_switches_to_ytdlp():
    listener = SimpleNamespace(
        is_cancelled=False,
        aria2_fallback_retried=True,
        aria2_fallback_completed=4096,
        aria2_fallback_error="Connection reset",
        on_download_error=AsyncMock(),
        _add_ytdlp_fallback=AsyncMock(),
    )
    retry = load_method("bot/modules/mirror_leech.py", "Mirror", "_retry_aria2_or_ytdlp", {})
    await retry(listener, "/downloads")
    listener._add_ytdlp_fallback.assert_not_awaited()
    assert "already started receiving data" in listener.on_download_error.call_args.args[0]


@pytest.fixture
def direct_class(helpers):
    path = ROOT / "bot/helper/listeners/direct_listener.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    manager = SimpleNamespace(aria2=None, aria2_remove=AsyncMock())
    namespace = {
        "Semaphore": asyncio.Semaphore,
        "gather": asyncio.gather,
        "sleep": AsyncMock(),
        "suppress": suppress,
        "ClientError": httpx.HTTPError,
        "LOGGER": logging.getLogger(__name__),
        "TorrentManager": manager,
        "Config": SimpleNamespace(DIRECT_PARALLELISM=2),
        **{
            name: helpers[name]
            for name in (
                "get_download_user_agent",
                "parse_download_headers",
                "get_aria2_retry_options",
            )
        },
    }
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["DirectListener"], manager


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [0, 4096])
async def test_collection_retries_only_before_receiving_data(direct_class, completed):
    cls, manager = direct_class
    calls = []

    async def add(**kwargs):
        calls.append(kwargs)
        return str(len(calls))

    async def status(gid):
        return {
            "gid": gid,
            "status": "error" if gid == "1" else "complete",
            "completedLength": str(completed if gid == "1" else 10),
            "totalLength": "10",
            "errorMessage": "HTTP 403" if gid == "1" else "",
        }

    manager.aria2 = SimpleNamespace(addUri=add, tellStatus=status)
    listener = SimpleNamespace(is_cancelled=False, name="Collection")
    direct = cls("/downloads", listener, {"header": "Authorization: Bearer abc"})
    await direct._download_one(
        {"url": "https://example.com/file.zip", "path": "", "filename": "file.zip"}
    )
    assert len(calls) == (1 if completed else 2)
    assert direct._failed == (1 if completed else 0)
    assert direct.download_tasks == {}
    assert calls[0]["options"]["header"] == ["authorization: Bearer abc"]
    if not completed:
        assert calls[1]["options"]["user-agent"] == "aria2"
        assert calls[1]["options"]["split"] == "1"
        assert direct.processed_bytes == 10


@pytest.mark.asyncio
async def test_collection_uses_coloros_host_rule_and_keeps_custom_agent(direct_class):
    cls, manager = direct_class
    add = AsyncMock(side_effect=RuntimeError("stop after recording options"))
    manager.aria2 = SimpleNamespace(addUri=add)
    listener = SimpleNamespace(is_cancelled=False, name="Collection")
    content = {"url": COLOROS_URL, "path": "", "filename": "file.zip"}
    await cls("/downloads", listener, {})._download_one(content)
    assert add.call_args.kwargs["options"]["user-agent"] == "aria2"
    await cls("/downloads", listener, {"header": "User-Agent: custom"})._download_one(content)
    assert "user-agent" not in add.call_args.kwargs["options"]


@pytest.mark.asyncio
async def test_later_failed_attempt_does_not_erase_partial_progress(helpers):
    namespace = load_functions(
        "bot/helper/mirror_leech_utils/download_utils/aria2_download.py",
        {"add_aria2_download", "_sourceforge_filename"},
        {
            **{key: helpers[key] for key in ("get_download_user_agent", "parse_download_headers")},
            "Config": SimpleNamespace(DISABLE_TORRENTS=False, TORRENT_TIMEOUT=0),
            "check_running_tasks": AsyncMock(return_value=(False, None)),
            "aiopath": SimpleNamespace(exists=AsyncMock(return_value=False)),
            "TorrentManager": SimpleNamespace(
                aria2=SimpleNamespace(addUri=AsyncMock(side_effect=RuntimeError("failed")))
            ),
            "LOGGER": logging.getLogger(__name__),
            "ClientError": httpx.HTTPError,
            "urlparse": urlparse,
            "unquote": unquote,
        },
    )
    listener = SimpleNamespace(link=COLOROS_URL, name="", aria2_fallback_completed=4096)
    await namespace["add_aria2_download"](
        listener, "/downloads", "", None, None, notify_error=False
    )
    assert listener.aria2_fallback_completed == 4096


@pytest.mark.asyncio
async def test_single_download_retry_uses_recovery_profile_and_keeps_headers(helpers):
    add = AsyncMock(return_value=True)
    metadata = AsyncMock(return_value=("application/zip", "file.zip"))
    listener = SimpleNamespace(
        is_cancelled=False,
        link="https://example.com/file.zip",
        name="",
        aria2_fallback_error="HTTP 403",
        aria2_fallback_completed=0,
        aria2_fallback_headers="Authorization: Bearer abc",
        aria2_fallback_ratio=None,
        aria2_fallback_seed_time=None,
    )
    retry = load_method(
        "bot/modules/mirror_leech.py",
        "Mirror",
        "_retry_aria2_or_ytdlp",
        {
            "sleep": AsyncMock(),
            "get_aria2_retry_options": helpers["get_aria2_retry_options"],
            "add_aria2_download": add,
            "get_content_info": metadata,
            "re_match": re_match,
            "LOGGER": logging.getLogger(__name__),
        },
    )
    await retry(listener, "/downloads")
    assert listener.aria2_fallback_options["split"] == "1"
    assert listener.aria2_fallback_options["user-agent"] == "aria2"
    assert add.call_args.args[2] == "Authorization: Bearer abc"
    metadata.assert_awaited_once_with(listener.link, "Authorization: Bearer abc")


@pytest.mark.asyncio
async def test_both_engine_errors_remain_visible_when_fallback_fails():
    listener = SimpleNamespace(
        is_cancelled=False,
        link="https://example.com/file.zip",
        aria2_fallback_retried=True,
        aria2_fallback_error="HTTP 403",
        aria2_fallback_completed=0,
        ytdlp_fallback_error="No usable extractor",
        _add_ytdlp_fallback=AsyncMock(return_value=False),
        on_download_error=AsyncMock(),
    )
    retry = load_method(
        "bot/modules/mirror_leech.py",
        "Mirror",
        "_retry_aria2_or_ytdlp",
        {
            "LOGGER": logging.getLogger(__name__),
        },
    )
    await retry(listener, "/downloads")
    error = listener.on_download_error.call_args.args[0]
    assert "HTTP 403" in error
    assert "No usable extractor" in error


@pytest.mark.asyncio
async def test_ytdlp_fallback_preserves_credentials_without_mutating_saved_options(helpers):
    original_options = {"http_headers": {"Referer": "https://example.com/"}}
    listener = SimpleNamespace(
        is_cancelled=False,
        user_dict={"YT_DLP_OPTIONS": original_options},
        download_headers="Authorization: Bearer abc\nUser-Agent: custom",
        link="https://example.com/video",
        on_download_error=AsyncMock(),
    )
    extracted_options = []
    download = AsyncMock()

    async def extract(_function, _link, options):
        extracted_options.append(options)
        return {"extractor_key": "Example"}

    listener._set_mode_engine = lambda: None
    fallback = load_method(
        "bot/modules/mirror_leech.py",
        "Mirror",
        "_add_ytdlp_fallback",
        {
            "Config": SimpleNamespace(YT_DLP_OPTIONS={}),
            "aiopath": SimpleNamespace(exists=AsyncMock(return_value=False)),
            "parse_download_headers": helpers["parse_download_headers"],
            "sync_to_async": extract,
            "extract_ytdlp_info": object(),
            "get_ytdlp_extractor": lambda result: result["extractor_key"],
            "is_generic_ytdlp_result": lambda _: False,
            "YoutubeDLHelper": lambda _: SimpleNamespace(add_download=download),
            "LOGGER": logging.getLogger(__name__),
        },
    )
    assert await fallback(listener, "/downloads") is True
    assert extracted_options[0]["http_headers"] == {
        "referer": "https://example.com/",
        "authorization": "Bearer abc",
        "user-agent": "custom",
    }
    assert download.call_args.args[3]["http_headers"] == extracted_options[0]["http_headers"]
    assert original_options == {"http_headers": {"Referer": "https://example.com/"}}


@pytest.mark.asyncio
async def test_collection_retries_once_then_stops_and_keeps_command_headers(direct_class):
    cls, manager = direct_class
    listener = SimpleNamespace(
        is_cancelled=False,
        name="Collection",
        download_headers="Authorization: Bearer command",
    )
    manager.aria2 = SimpleNamespace(
        addUri=AsyncMock(return_value="gid"),
        tellStatus=AsyncMock(
            return_value={
                "gid": "gid",
                "status": "error",
                "errorMessage": "HTTP 403",
                "completedLength": "0",
            }
        ),
    )
    direct = cls(
        "/downloads", listener, {"header": "Authorization: Bearer manifest\nCookie: session=abc"}
    )
    await direct._download_one(
        {"url": "https://example.com/file.zip", "path": "", "filename": "file.zip"}
    )
    assert manager.aria2.addUri.await_count == 2
    assert manager.aria2.addUri.call_args.kwargs["options"]["header"] == [
        "authorization: Bearer command",
        "cookie: session=abc",
    ]
    assert direct._failed == 1
    assert direct.download_tasks == {}


@pytest.mark.asyncio
async def test_error_callback_keeps_cumulative_partial_progress():
    listener = SimpleNamespace(
        is_cancelled=False,
        allow_ytdlp_fallback=True,
        link="https://example.com/file.zip",
        dir="/downloads",
        aria2_fallback_completed=4096,
        _retry_aria2_or_ytdlp=AsyncMock(),
    )
    callback = load_functions(
        "bot/helper/listeners/aria2_listener.py",
        {"_on_download_error"},
        {
            "_aria2_event_guard": lambda fn: fn,
            "sleep": AsyncMock(),
            "suppress": suppress,
            "LOGGER": logging.getLogger(__name__),
            "get_task_by_gid": AsyncMock(return_value=SimpleNamespace(listener=listener)),
            "TorrentManager": SimpleNamespace(aria2_remove=AsyncMock()),
        },
    )["_on_download_error"]
    api = SimpleNamespace(
        tellStatus=AsyncMock(
            return_value={"gid": "gid", "completedLength": "0", "errorMessage": "HTTP 403"}
        ),
        getOption=AsyncMock(return_value={"follow-torrent": "true"}),
    )
    await callback(api, {"params": [{"gid": "gid"}]})
    assert listener.aria2_fallback_completed == 4096
    listener._retry_aria2_or_ytdlp.assert_awaited_once_with("/downloads")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_after_add", [False, True])
async def test_single_download_cancel_does_not_leave_an_unregistered_job(helpers, cancel_after_add):
    listener = SimpleNamespace(link=COLOROS_URL, name="", is_cancelled=not cancel_after_add)

    async def add(**_kwargs):
        listener.is_cancelled = True
        return "accepted-gid"

    manager = SimpleNamespace(
        aria2=SimpleNamespace(addUri=AsyncMock(side_effect=add)), aria2_remove=AsyncMock()
    )
    namespace = load_functions(
        "bot/helper/mirror_leech_utils/download_utils/aria2_download.py",
        {"add_aria2_download", "_sourceforge_filename"},
        {
            **{key: helpers[key] for key in ("get_download_user_agent", "parse_download_headers")},
            "Config": SimpleNamespace(DISABLE_TORRENTS=False, TORRENT_TIMEOUT=0),
            "check_running_tasks": AsyncMock(return_value=(False, None)),
            "aiopath": SimpleNamespace(exists=AsyncMock(return_value=False)),
            "TorrentManager": manager,
            "LOGGER": logging.getLogger(__name__),
            "ClientError": httpx.HTTPError,
            "urlparse": urlparse,
            "unquote": unquote,
            "suppress": suppress,
        },
    )
    assert await namespace["add_aria2_download"](listener, "/downloads", "", None, None) is False
    assert manager.aria2.addUri.await_count == int(cancel_after_add)
    if cancel_after_add:
        manager.aria2_remove.assert_awaited_once_with({"gid": "accepted-gid", "status": "active"})


@pytest.mark.asyncio
async def test_collection_cleans_up_job_if_initial_status_request_fails(direct_class):
    cls, manager = direct_class
    manager.aria2 = SimpleNamespace(
        addUri=AsyncMock(return_value="accepted-gid"),
        tellStatus=AsyncMock(side_effect=httpx.RequestError("RPC unavailable")),
    )
    listener = SimpleNamespace(is_cancelled=False, name="Collection")
    direct = cls("/downloads", listener, {})
    await direct._download_one(
        {"url": "https://example.com/file.zip", "path": "", "filename": "file.zip"}
    )
    manager.aria2_remove.assert_awaited_once_with({"gid": "accepted-gid", "status": "active"})
    assert direct.download_tasks == {}
    assert direct._failed == 1


@pytest.mark.asyncio
async def test_collection_keeps_parallelism_progress_and_completion_accounting(direct_class):
    cls, manager = direct_class
    active = set()
    maximum = 0
    polls = {}

    async def add(**_kwargs):
        nonlocal maximum
        gid = str(len(polls))
        polls[gid] = 0
        active.add(gid)
        maximum = max(maximum, len(active))
        await asyncio.sleep(0)
        return gid

    async def status(gid):
        polls[gid] += 1
        await asyncio.sleep(0)
        return {
            "gid": gid,
            "status": "complete" if polls[gid] >= 3 else "active",
            "completedLength": "10",
            "totalLength": "10",
        }

    async def remove(download):
        active.discard(download["gid"])

    manager.aria2 = SimpleNamespace(addUri=add, tellStatus=status)
    manager.aria2_remove = remove
    listener = SimpleNamespace(
        is_cancelled=False,
        name="Collection",
        on_download_complete=AsyncMock(),
        on_download_error=AsyncMock(),
    )
    direct = cls("/downloads", listener, {})
    await direct.download(
        [
            {"url": f"https://example.com/{index}.zip", "filename": f"{index}.zip", "path": ""}
            for index in range(5)
        ]
    )
    assert maximum == 2
    assert direct.processed_bytes == 50
    assert direct.download_tasks == {}
    assert active == set()
    listener.on_download_complete.assert_awaited_once()
    listener.on_download_error.assert_not_awaited()
