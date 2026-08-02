import ast
import asyncio
import logging
import re
import sys
from contextlib import suppress
from hashlib import sha256
from html import escape
from pathlib import Path
from secrets import token_urlsafe
from types import ModuleType, SimpleNamespace

import pytest

SOURCE_PATH = Path(__file__).parents[1] / "web" / "wserver.py"
BOT_SETTINGS_PATH = Path(__file__).parents[1] / "bot" / "modules" / "bot_settings.py"
STARTUP_PATH = Path(__file__).parents[1] / "bot" / "core" / "startup.py"
TG_CLIENT_PATH = Path(__file__).parents[1] / "bot" / "core" / "tg_client.py"
FILETOLINK_MODULE_PATH = Path(__file__).parents[1] / "bot" / "modules" / "filetolink.py"
MESSAGE_UTILS_PATH = (
    Path(__file__).parents[1]
    / "bot"
    / "helper"
    / "telegram_helper"
    / "message_utils.py"
)


def load_functions(names, namespace):
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    wanted = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    ]
    exec(compile(ast.Module(wanted, type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class FloodWait(Exception):
    def __init__(self, value):
        super().__init__(value)
        self.value = value


class FakeStreamClient:
    def __init__(self, chunks, delays=None):
        self.chunks = chunks
        self.delays = delays or {}
        self.in_flight = 0
        self.max_in_flight = 0
        self.requested = []

    async def stream_media(self, _message, offset=0, limit=0):
        assert limit > 0
        self.requested.append((offset, limit))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            for chunk_index in range(offset, min(offset + limit, len(self.chunks))):
                await asyncio.sleep(self.delays.get(chunk_index, 0))
                yield self.chunks[chunk_index]
        finally:
            self.in_flight -= 1


@pytest.fixture
def stream_namespace(monkeypatch):
    pyrogram = ModuleType("pyrogram")
    errors = ModuleType("pyrogram.errors")
    errors.FloodWait = FloodWait
    pyrogram.errors = errors
    monkeypatch.setitem(sys.modules, "pyrogram", pyrogram)
    monkeypatch.setitem(sys.modules, "pyrogram.errors", errors)

    namespace = {
        "CancelledError": asyncio.CancelledError,
        "CHUNK_SIZE": 16,
        "FILETOLINK_GETFILE_CONCURRENCY": 4,
        "sleep": asyncio.sleep,
        "suppress": suppress,
    }
    return load_functions(
        {
            "_iter_native_telegram_batch",
            "_iter_telegram_range",
        },
        namespace,
    )


@pytest.mark.asyncio
async def test_telegram_range_prefetches_but_yields_bytes_in_order(stream_namespace):
    stream_namespace["_transfer_prefetch_depth"] = lambda _client_id: 4
    chunk_size = stream_namespace["CHUNK_SIZE"]
    client = FakeStreamClient(
        [b"a" * chunk_size, b"b" * chunk_size, b"c" * 5],
        delays={0: 0.03, 1: 0.001, 2: 0.001},
    )

    received = b"".join(
        [
            part
            async for part in stream_namespace["_iter_telegram_range"](
                7,
                client,
                object(),
                chunk_size - 3,
                chunk_size * 2 + 2,
                chunk_size * 2 + 5,
            )
        ]
    )

    assert received == b"a" * 3 + b"b" * chunk_size + b"c" * 3
    assert client.requested == [(0, 3)]


@pytest.mark.asyncio
async def test_native_batch_resumes_from_the_first_missing_chunk(stream_namespace):
    class FlakyClient(FakeStreamClient):
        async def stream_media(self, message, offset=0, limit=0):
            self.requested.append((offset, limit))
            if len(self.requested) == 1:
                yield self.chunks[offset]
                raise ConnectionError("temporary media session failure")
            async for chunk in super().stream_media(message, offset, limit):
                yield chunk

    client = FlakyClient([bytes([index]) * 16 for index in range(3)])
    received = [
        chunk
        async for chunk in stream_namespace["_iter_native_telegram_batch"](
            client, object(), 0, 2
        )
    ]

    assert received == [
        (0, b"\x00" * 16),
        (1, b"\x01" * 16),
        (2, b"\x02" * 16),
    ]
    assert client.requested[0] == (0, 3)
    assert client.requested[1] == (1, 2)


@pytest.mark.asyncio
async def test_native_batch_stops_after_three_failures_without_progress(
    stream_namespace,
):
    class FailingClient:
        def __init__(self):
            self.requested = []

        async def stream_media(self, _message, offset=0, limit=0):
            self.requested.append((offset, limit))
            raise ConnectionError("Telegram media DC unavailable")
            yield  # pragma: no cover

    async def no_sleep(_delay):
        return None

    stream_namespace["sleep"] = no_sleep
    client = FailingClient()
    with pytest.raises(OSError, match="failed after 3 attempts"):
        _ = [
            chunk
            async for chunk in stream_namespace["_iter_native_telegram_batch"](
                client, object(), 4, 6
            )
        ]

    assert client.requested == [(4, 3), (4, 3), (4, 3)]


@pytest.mark.asyncio
async def test_native_batch_ignores_cleanup_error_after_success(stream_namespace):
    class StreamWithBrokenClose:
        def __init__(self):
            self.sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return b"x" * 16

        async def aclose(self):
            raise ConnectionError("close failed")

    class Client:
        def stream_media(self, _message, offset=0, limit=0):
            assert (offset, limit) == (0, 1)
            return StreamWithBrokenClose()

    received = [
        chunk
        async for chunk in stream_namespace["_iter_native_telegram_batch"](
            Client(), object(), 0, 0
        )
    ]

    assert received == [(0, b"x" * 16)]


def test_prefetch_depth_shares_worker_across_active_transfers(monkeypatch):
    fake_client_type = SimpleNamespace(stream_loads={3: 1})
    tg_client_module = ModuleType("bot.core.tg_client")
    tg_client_module.TgClient = fake_client_type
    monkeypatch.setitem(sys.modules, "bot.core.tg_client", tg_client_module)

    namespace = {
        "FILETOLINK_GETFILE_CONCURRENCY": 8,
        "FILETOLINK_PREFETCH_CHUNKS": 4,
    }
    load_functions({"_transfer_prefetch_depth"}, namespace)

    assert namespace["_transfer_prefetch_depth"](3) == 8
    fake_client_type.stream_loads[3] = 2
    assert namespace["_transfer_prefetch_depth"](3) == 4
    fake_client_type.stream_loads[3] = 3
    assert namespace["_transfer_prefetch_depth"](3) == 2
    fake_client_type.stream_loads[3] = 8
    assert namespace["_transfer_prefetch_depth"](3) == 1


def test_runtime_snapshot_tracks_progress_speed_and_worker_health():
    task = SimpleNamespace()
    namespace = {
        "FILETOLINK_CACHE_TOTAL_MAX_BYTES": 4096,
        "_filetolink_active_streams": {},
        "_filetolink_worker_counts": lambda: (2, 1),
        "monotonic": lambda: 100.0,
        "wall_time": lambda: 1000.0,
        "token_urlsafe": lambda _size: "transfer-1",
        "current_task": lambda: task,
    }
    load_functions(
        {
            "_begin_filetolink_transfer",
            "_update_filetolink_transfer",
            "_finish_filetolink_transfer",
            "_build_filetolink_status_snapshot",
        },
        namespace,
    )

    transfer_id = namespace["_begin_filetolink_transfer"](
        "movie.mkv", "Stream", "Telegram", 1024, 3
    )
    namespace["_filetolink_active_streams"][transfer_id]["started_mono"] = 98.0
    namespace["_update_filetolink_transfer"](transfer_id, 512)
    snapshot = namespace["_build_filetolink_status_snapshot"](2, 2048)

    assert snapshot["state"] == "degraded"
    assert snapshot["workers"] == {"total": 2, "ready": 1}
    assert snapshot["active_count"] == 1
    assert snapshot["aggregate_speed"] == 256
    assert snapshot["transfers"][0]["progress"] == 50
    assert snapshot["transfers"][0]["source"] == "Telegram"
    assert "started_mono" not in snapshot["transfers"][0]
    assert "last_activity_mono" not in snapshot["transfers"][0]
    assert "task" not in snapshot["transfers"][0]

    namespace["_finish_filetolink_transfer"](transfer_id)
    assert namespace["_filetolink_active_streams"] == {}


def test_stale_runtime_transfers_are_cancelled_and_removed():
    class FakeTask:
        def __init__(self, done=False):
            self.cancelled = False
            self.finished = done

        def done(self):
            return self.finished

        def cancel(self):
            self.cancelled = True

    stale_task = FakeTask()
    recent_task = FakeTask()
    completed_task = FakeTask(done=True)
    released = []
    namespace = {
        "FILETOLINK_TRANSFER_STALE_SECONDS": 300,
        "LOGGER": logging.getLogger(__name__),
        "_release_stream_load": released.append,
        "_filetolink_active_streams": {
            "stale": {
                "name": "finished.mkv",
                "client_id": 1,
                "last_activity_mono": 600.0,
                "task": stale_task,
            },
            "recent": {
                "name": "active.mkv",
                "client_id": 2,
                "last_activity_mono": 950.0,
                "task": recent_task,
            },
            "completed": {
                "name": "already-done.mkv",
                "client_id": 3,
                "last_activity_mono": 999.0,
                "task": completed_task,
            },
        },
        "monotonic": lambda: 1000.0,
    }
    load_functions({"_prune_stale_filetolink_transfers"}, namespace)

    namespace["_prune_stale_filetolink_transfers"]()

    assert set(namespace["_filetolink_active_streams"]) == {"recent"}
    assert stale_task.cancelled
    assert not recent_task.cancelled
    assert released == [3]


def test_streaming_paths_publish_live_filetolink_metrics():
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "_filetolink_status_publisher" in source
    assert '"FILETOLINK_STATUS_FILE"' in source
    assert '"Telegram"' in source
    assert '"Cache"' in source
    assert source.count("_update_filetolink_transfer(transfer_id, bytes_sent)") == 2
    assert source.count("_finish_filetolink_transfer(transfer_id)") == 2


@pytest.mark.asyncio
async def test_status_publisher_throttles_cache_directory_scans():
    clock = [1.0]
    scans = []
    written = []

    def cache_usage():
        scans.append(clock[0])
        return 4, 2048

    namespace = {
        "_filetolink_cache_metrics": {"files": 0, "bytes": 0, "sampled_at": 0.0},
        "_filetolink_cache_usage": cache_usage,
        "_build_filetolink_status_snapshot": lambda files, size, state: {
            "files": files,
            "bytes": size,
            "state": state,
        },
        "_write_filetolink_status_snapshot": written.append,
        "_prune_stale_filetolink_transfers": lambda: None,
        "monotonic": lambda: clock[0],
        "to_thread": asyncio.to_thread,
    }
    load_functions({"_publish_filetolink_status"}, namespace)

    await namespace["_publish_filetolink_status"]()
    clock[0] = 3.0
    await namespace["_publish_filetolink_status"]()
    clock[0] = 7.0
    await namespace["_publish_filetolink_status"]()

    assert scans == [1.0, 7.0]
    assert len(written) == 3
    assert written[-1]["files"] == 4


def test_status_snapshot_number_parser_rejects_non_finite_values():
    tree = ast.parse(FILETOLINK_MODULE_PATH.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_safe_number", "_safe_count"}
    ]
    namespace = {"isfinite": __import__("math").isfinite}
    exec(
        compile(
            ast.Module(functions, type_ignores=[]),
            str(FILETOLINK_MODULE_PATH),
            "exec",
        ),
        namespace,
    )

    assert namespace["_safe_number"]("nan") == 0
    assert namespace["_safe_number"]("inf") == 0
    assert namespace["_safe_count"]("not-a-number", 3) == 3


def test_filetolink_status_renderer_executes_active_and_idle_views():
    class FakeButtonMaker:
        def __init__(self):
            self.buttons = []

        def data_button(self, label, data, **_kwargs):
            self.buttons.append((label, data))

        def build_menu(self, **_kwargs):
            return self.buttons

    tree = ast.parse(FILETOLINK_MODULE_PATH.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {
            "_safe_number",
            "_safe_count",
            "_filetolink_state",
            "build_filetolink_status",
        }
    ]
    snapshot = {
        "stale": False,
        "state": "streaming",
        "updated_at": 990,
        "workers": {"ready": 2, "total": 2},
        "active_count": 1,
        "aggregate_speed": 256,
        "cache": {"files": 3, "bytes": 1024, "max_bytes": 4096},
        "transfers": [
            {
                "name": "movie<final>.mkv",
                "mode": "Stream",
                "source": "Telegram",
                "bytes_sent": 512,
                "total": 1024,
                "progress": 50,
                "speed": 256,
                "started_at": 990,
            }
        ],
    }
    namespace = {
        "ButtonMaker": FakeButtonMaker,
        "ButtonStyle": SimpleNamespace(PRIMARY="primary"),
        "Config": SimpleNamespace(
            BASE_URL="https://files.example",
            STATUS_LIMIT=1,
        ),
        "_read_filetolink_status": lambda: snapshot,
        "escape": escape,
        "get_progress_bar_string": lambda value: f"bar-{value}",
        "get_readable_file_size": lambda value: f"{int(value)}B",
        "get_readable_time": lambda value: f"{int(value)}s",
        "isfinite": __import__("math").isfinite,
        "time": lambda: 1000,
    }
    exec(
        compile(
            ast.Module(functions, type_ignores=[]),
            str(FILETOLINK_MODULE_PATH),
            "exec",
        ),
        namespace,
    )

    text, buttons = namespace["build_filetolink_status"](77)
    assert "TRANSFER 01" in text
    assert "movie&lt;final&gt;.mkv" in text
    assert "bar-50.0 50.0%" in text
    assert "🟢 Streaming" in text
    assert buttons == [
        ("↻ REFRESH", "status 77 flp 1"),
        ("↩ TASKS", "status 77 home"),
    ]

    snapshot["transfers"] = [
        {**snapshot["transfers"][0], "name": f"movie-{index}.mkv"}
        for index in range(1, 4)
    ]
    snapshot["active_count"] = 3
    text, buttons = namespace["build_filetolink_status"](77, page_no=2)
    assert "TRANSFER 02" in text
    assert "TRANSFER 01" not in text
    assert ("❮ PREV", "status 77 flp 1") in buttons
    assert ("NEXT ❯", "status 77 flp 3") in buttons
    assert len(text) <= 820

    snapshot.update({"stale": True, "transfers": [], "active_count": 0})
    text, buttons = namespace["build_filetolink_status"](77, standalone=True)
    assert "No active transfers" in text
    assert "🔴 Offline" in text
    assert buttons[-1] == ("✕ CLOSE", "status 77 dismiss")


@pytest.mark.asyncio
async def test_status_timer_refreshes_the_visible_filetolink_panel(monkeypatch):
    tree = ast.parse(MESSAGE_UTILS_PATH.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "update_status_message"
    )
    filetolink_module = ModuleType("bot.modules.filetolink")
    filetolink_module.build_filetolink_status = lambda sid, **_kwargs: (
        f"filetolink-{sid}-updated",
        "buttons",
    )
    modules_package = ModuleType("bot.modules")
    modules_package.__path__ = []
    monkeypatch.setitem(sys.modules, "bot.modules", modules_package)
    monkeypatch.setitem(sys.modules, "bot.modules.filetolink", filetolink_module)

    edited = []

    async def edit_message(message, text, buttons, **_kwargs):
        edited.append((message, text, buttons))
        return message

    status_message = SimpleNamespace(text="old task status")
    namespace = {
        "Config": SimpleNamespace(STATUS_UPDATE_INTERVAL=1),
        "LOGGER": logging.getLogger(__name__),
        "edit_message": edit_message,
        "get_idle_status_message": lambda sid: (f"idle-{sid}", None),
        "get_readable_message": None,
        "intervals": {"stopAll": False, "status": {}},
        "re_search": re.search,
        "status_dict": {
            77: {
                "message": status_message,
                "time": 0,
                "page_no": 1,
                "page_step": 1,
                "status": "All",
                "is_user": False,
                "view": "filetolink",
            }
        },
        "task_dict": {},
        "task_dict_lock": asyncio.Lock(),
        "time": lambda: 100.0,
    }
    exec(
        compile(
            ast.Module([function], type_ignores=[]),
            str(MESSAGE_UTILS_PATH),
            "exec",
        ),
        namespace,
    )

    await namespace["update_status_message"](77)

    assert edited == [(status_message, "filetolink-77-updated", "buttons")]
    assert status_message.text == "filetolink-77-updated"


def test_filetolink_tuning_is_wired_to_bsettings_and_web_process():
    settings_source = BOT_SETTINGS_PATH.read_text(encoding="utf-8")
    startup_source = STARTUP_PATH.read_text(encoding="utf-8")

    for key in (
        "FILETOLINK_GETFILE_CONCURRENCY",
        "FILETOLINK_PREFETCH_CHUNKS",
    ):
        assert key in settings_source
        assert f'proc_env["{key}"]' in startup_source

    assert "_apply_filetolink_web_tuning" in settings_source


def test_filetolink_prewarm_builds_the_native_download_session_pool():
    source = TG_CLIENT_PATH.read_text(encoding="utf-8")

    assert 'getattr(client, "DOWNLOAD_POOL_SIZE", 1)' in source
    assert "client._get_media_session_pool(" in source
    assert "sessions=%s/%s" in source


def test_filetolink_tuning_is_exposed_and_safely_bounded():
    from bot.core.config_manager import Config

    original_concurrency = Config.FILETOLINK_GETFILE_CONCURRENCY
    original_prefetch = Config.FILETOLINK_PREFETCH_CHUNKS
    try:
        assert "FILETOLINK_GETFILE_CONCURRENCY" in Config.get_all()
        assert "FILETOLINK_PREFETCH_CHUNKS" in Config.get_all()

        Config.set("FILETOLINK_GETFILE_CONCURRENCY", 0)
        assert Config.FILETOLINK_GETFILE_CONCURRENCY == 1
        assert Config.FILETOLINK_PREFETCH_CHUNKS == 1

        Config.set("FILETOLINK_GETFILE_CONCURRENCY", 100)
        Config.set("FILETOLINK_PREFETCH_CHUNKS", 100)
        assert Config.FILETOLINK_GETFILE_CONCURRENCY == 32
        assert Config.FILETOLINK_PREFETCH_CHUNKS == 32
    finally:
        Config.set("FILETOLINK_GETFILE_CONCURRENCY", original_concurrency)
        Config.set("FILETOLINK_PREFETCH_CHUNKS", original_prefetch)


def test_stream_health_resets_only_after_a_completed_transfer():
    namespace = {
        "STREAM_CLIENT_COOLDOWN_SECONDS": 45,
        "_stream_client_health": {},
        "monotonic": lambda: 100.0,
    }
    load_functions(
        {
            "_stream_health",
            "_stream_client_available",
            "_record_stream_failure",
            "_record_stream_success",
            "get_message_with_stream_client",
        },
        namespace,
    )

    namespace["_record_stream_failure"](2, "timeout")
    namespace["_record_stream_failure"](2, "timeout")
    assert not namespace["_stream_client_available"](2)

    # Reading message metadata must not rehabilitate a worker whose media
    # transfers are failing; only stream_generator calls this on completion.
    metadata_function = ast.parse(
        ast.get_source_segment(
            SOURCE_PATH.read_text(encoding="utf-8"),
            next(
                node
                for node in ast.parse(
                    SOURCE_PATH.read_text(encoding="utf-8")
                ).body
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "get_message_with_stream_client"
            ),
        )
    )
    assert "_record_stream_success" not in ast.dump(metadata_function)

    namespace["_record_stream_success"](2)
    assert namespace["_stream_client_available"](2)


def test_progressive_cache_promotes_only_complete_files(tmp_path):
    namespace = {
        "FILETOLINK_CACHE_DIR": str(tmp_path),
        "FILETOLINK_CACHE_MAX_BYTES": 1024,
        "FILETOLINK_CACHE_TOTAL_MAX_BYTES": 4096,
        "LOGGER": logging.getLogger(__name__),
        "Path": Path,
        "re": re,
        "sha256": sha256,
        "suppress": suppress,
        "token_urlsafe": token_urlsafe,
        "_filetolink_cache_writers": set(),
    }
    load_functions(
        {
            "_cache_path_for_media",
            "_prune_filetolink_cache",
            "_begin_progressive_cache",
            "_finish_progressive_cache",
        },
        namespace,
    )

    reservation = namespace["_begin_progressive_cache"](
        1, 2, "uid", "movie.bin", 5
    )
    assert reservation is not None
    _, temp_path, cache_path = reservation
    temp_path.write_bytes(b"12345")

    namespace["_finish_progressive_cache"](reservation, 5, complete=True)

    assert cache_path.read_bytes() == b"12345"
    assert not temp_path.exists()
    assert not namespace["_filetolink_cache_writers"]
