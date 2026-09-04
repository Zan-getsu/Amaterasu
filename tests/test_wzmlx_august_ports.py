import asyncio
import ast
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.core.config_manager import Config, DEFAULT_CONFIG
from bot.helper.ext_utils import hyperdl_utils
from bot.helper.ext_utils.bot_lock import SmartLock
from bot.helper.ext_utils.links_utils import is_mega_link
from bot.helper.mirror_leech_utils.download_utils import direct_link_generator as dlg
from bot.helper.telegram_helper.button_build import valid_url
from bot.helper.telegram_helper.filters import _chat_context


ROOT = Path(__file__).parents[1]


def source(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_real_config_defaults_are_isolated_and_mirror_is_enabled_by_default():
    assert Config.DISABLE_MIRROR is False
    assert DEFAULT_CONFIG["DISABLE_MIRROR"] is False
    assert DEFAULT_CONFIG["BOT_MAX_TASKS"] == 10
    assert DEFAULT_CONFIG["USER_MAX_TASKS"] == 3
    assert DEFAULT_CONFIG["YT_TAGS"] == ["telegram", "bot", "youtube"]
    assert DEFAULT_CONFIG["YT_TAGS"] is not Config.YT_TAGS


def test_url_buttons_and_mega_detection_reject_ambiguous_targets():
    assert valid_url(" https://example.com/file ") == "https://example.com/file"
    assert valid_url("tg://resolve?domain=example")
    assert valid_url("javascript:alert(1)") == ""
    assert valid_url("https://example.com/a b") == ""
    assert is_mega_link("https://mega.nz/file/abc")
    assert is_mega_link("https://www.mega.co.nz/folder/abc")
    assert not is_mega_link("https://mega.nz.evil.example/file/abc")
    button_source = source("bot/helper/telegram_helper/button_build.py")
    assert "unusable URL" in button_source
    assert "{link!r}" not in button_source


def test_callback_query_uses_its_source_message_chat_context():
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-100123),
        is_topic_message=True,
        message_thread_id=77,
    )
    assert _chat_context(SimpleNamespace(message=message)) == (-100123, 77)


def test_youtube_options_prefer_user_values_and_category_is_string_ready():
    tree = ast.parse(
        source(
            "bot/helper/mirror_leech_utils/youtube_utils/youtube_upload.py"
        )
    )
    upload_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "YouTubeUpload"
    )
    method = next(
        node
        for node in upload_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "_yt_opt"
    )
    namespace = {"Config": Config}
    exec(compile(ast.Module([method], type_ignores=[]), "youtube_upload.py", "exec"), namespace)
    upload = SimpleNamespace()
    upload.listener = SimpleNamespace(
        user_dict={"YT_CATEGORY_ID": 24, "YT_PRIVACY_STATUS": "private"}
    )
    yt_opt = namespace["_yt_opt"]
    assert str(yt_opt(upload, "YT_CATEGORY_ID")) == "24"
    assert yt_opt(upload, "YT_PRIVACY_STATUS") == "private"
    assert yt_opt(upload, "YT_DESP") == Config.YT_DESP


@pytest.mark.asyncio
async def test_smart_lock_ignores_duplicate_release():
    releases = []
    lock = SmartLock.__new__(SmartLock)
    lock._lock = asyncio.Lock()
    lock._active = 0
    lock._throttled = False
    lock._pause_targets = []
    lock._semaphore = SimpleNamespace(release=lambda: releases.append(True))

    await lock.release()

    assert releases == []
    assert lock._active == 0


@pytest.mark.asyncio
async def test_nzb_cleanup_falls_back_even_when_history_cleanup_raises():
    tree = ast.parse(source("bot/helper/listeners/nzb_listener.py"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_remove_job"
    )
    calls = []

    class Client:
        async def delete_history(self, job_id, delete_files):
            calls.append(("history", job_id, delete_files))
            raise RuntimeError("history unavailable")

        async def delete_category(self, category):
            calls.append(("category", category))
            return True

        async def delete_job(self, job_id, delete_files):
            calls.append(("job", job_id, delete_files))
            return True

    jobs = {"job-id": {}}
    namespace = {
        "LOGGER": SimpleNamespace(error=lambda *_args, **_kwargs: None),
        "gather": asyncio.gather,
        "nzb_jobs": jobs,
        "nzb_listener_lock": asyncio.Lock(),
        "sab_par2_lock": None,
        "sabnzbd_client": Client(),
    }
    exec(
        compile(ast.Module([function], type_ignores=[]), "nzb_listener.py", "exec"),
        namespace,
    )

    await namespace["_remove_job"]("job-id", 0)

    assert ("category", "0") in calls
    assert ("job", "job-id", True) in calls
    assert "job-id" not in jobs


def test_multi_uphoster_ignores_duplicate_terminal_callbacks():
    multi_upload = source(
        "bot/helper/mirror_leech_utils/uphoster_utils/multi_upload.py"
    )
    assert multi_upload.count("if service in self.results:") == 2


@pytest.mark.asyncio
async def test_cancelall_rejects_non_sudo_global_menu_callbacks():
    tree = ast.parse(source("bot/modules/cancel_task.py"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "cancel_all_update"
    )
    function.decorator_list = []
    answers = []

    class Filters:
        @staticmethod
        async def sudo(*_args):
            return False

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("unauthorized callback continued past ownership check")

    async def answer(text=None, **kwargs):
        answers.append((text, kwargs))

    namespace = {
        "CustomFilters": Filters,
        "cancel_all": unexpected,
        "create_cancel_buttons": unexpected,
        "delete_message": unexpected,
        "edit_message": unexpected,
        "send_message": unexpected,
    }
    exec(
        compile(ast.Module([function], type_ignores=[]), "cancel_task.py", "exec"),
        namespace,
    )
    query = SimpleNamespace(
        data="canall All confirm 0",
        from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(reply_to_message=None),
        answer=answer,
    )

    await namespace["cancel_all_update"](None, query)

    assert answers == [("Not Yours!", {"show_alert": True})]


@pytest.mark.asyncio
async def test_hyperdl_pwrite_reuses_a_memoryview(monkeypatch):
    chunks = []

    async def fake_to_thread(_func, _fd, data, _offset):
        chunks.append(data)
        return len(data)

    monkeypatch.setattr(hyperdl_utils.os, "pwrite", lambda *_args: 0, raising=False)
    monkeypatch.setattr(hyperdl_utils, "to_thread", fake_to_thread)

    await hyperdl_utils.HypertgDownload._pwrite(1, b"payload", 0)

    assert len(chunks) == 1
    assert isinstance(chunks[0], memoryview)
    assert bytes(chunks[0]) == b"payload"


def test_gofile_uses_dynamic_salt_and_supports_single_file(monkeypatch):
    captured_headers = {}

    class Response:
        def __init__(self, data=None, text=""):
            self._data = data
            self.text = text

        def json(self):
            return self._data

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, _url, **_kwargs):
            return Response({"status": "ok", "data": {"token": "token"}})

        def get(self, _url, headers=None, **_kwargs):
            captured_headers.update(headers or {})
            return Response(
                {
                    "status": "ok",
                    "data": {
                        "type": "file",
                        "name": "single.bin",
                        "link": "https://cdn.example/single.bin",
                        "size": "12",
                    },
                }
            )

    salt = "1234567890abcd"
    monkeypatch.setattr(dlg, "Session", Session)
    monkeypatch.setattr(
        dlg,
        "get",
        lambda *_args, **_kwargs: Response(text=f"generateWT() {{ return '{salt}'; }}"),
    )
    dlg._gofile_salt.cache_clear()

    result = dlg.gofile("https://gofile.io/d/file-id")

    assert result == (
        "https://cdn.example/single.bin",
        "Cookie: accountToken=token",
    )
    time_slot = int(dlg.time()) // 14400
    expected = sha256(
        f"{dlg.user_agent}::en-US::token::{time_slot}::{salt}".encode()
    ).hexdigest()
    assert captured_headers["X-Website-Token"] == expected


def test_new_hoster_routes_and_amaterasu_selector_features_remain_available(
    monkeypatch,
):
    monkeypatch.setattr(dlg, "buzzheavier", lambda url: f"buzz:{url}")
    assert dlg.direct_link_generator("https://bzzhr.co/abc") == (
        "buzz:https://bzzhr.co/abc"
    )
    monkeypatch.setattr(dlg, "sharer_scraper", lambda url: f"share:{url}")
    assert dlg.direct_link_generator("https://hubdrive.xyz/file/abc") == (
        "share:https://hubdrive.xyz/file/abc"
    )
    assert callable(dlg.hubdrive)
    assert callable(dlg.hubcloud)
    assert callable(dlg.gdflix)

    selector = source("web/templates/page.html")
    assert 'id="fileSearch"' in selector
    assert 'id="sortNameBtn"' in selector
    assert 'id="sortSizeBtn"' in selector
    assert 'id="selectEverythingBtn"' in selector
    assert "event.shiftKey" in selector


def test_safety_ports_are_wired_to_the_existing_amaterasu_paths():
    mirror = source("bot/modules/mirror_leech.py")
    nzb = source("bot/helper/listeners/nzb_listener.py")
    settings = source("bot/modules/users_settings.py")
    bot_settings = source("bot/modules/bot_settings.py")
    imdb = source("bot/modules/imdb.py")
    drive_download = source(
        "bot/helper/mirror_leech_utils/gdrive_utils/download.py"
    )
    direct_links = source(
        "bot/helper/mirror_leech_utils/download_utils/direct_link_generator.py"
    )
    selector = source("web/templates/page.html")

    assert "Config.DISABLE_MIRROR and not self.is_uphoster" in mirror
    assert "await _remove_job(nzo_id)" in nzb
    assert 'back_to = option.split("_")[0].lower()' in settings
    assert 'val = "\\n   ".join(lines)' in settings
    assert "InputRichFilePhoto" in imdb
    assert "template.format(**{**imdb, **locals()})" in imdb
    assert "rich IMDb peer resolution failed; using text" in imdb
    assert "previous_usenet_servers" in bot_settings
    assert 'if data[2] == "USENET_SERVERS":' in bot_settings
    assert "remove(output_path)" in drive_download
    assert direct_links.count("timeout=20") >= 8
    assert "function sortNodes(nodes)" in selector
    assert "return sortNodes(nodes);" in selector
    assert "? !areAllChildrenSelected(node)" in selector
