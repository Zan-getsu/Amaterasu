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
FILETOLINK_MODULE_PATH = Path(__file__).parents[1] / "bot" / "modules" / "filetolink.py"


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
        assert limit == 1
        self.requested.append(offset)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(offset, 0))
            yield self.chunks[offset]
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
        "Semaphore": asyncio.Semaphore,
        "_filetolink_chunk_slots": {},
        "create_task": asyncio.create_task,
        "gather": asyncio.gather,
        "sleep": asyncio.sleep,
    }
    return load_functions(
        {
            "_chunk_slots_for_client",
            "_fetch_telegram_chunk",
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
    assert client.max_in_flight > 1
    assert sorted(client.requested) == [0, 1, 2]


@pytest.mark.asyncio
async def test_chunk_pool_caps_each_telegram_worker(stream_namespace):
    stream_namespace["FILETOLINK_GETFILE_CONCURRENCY"] = 2
    client = FakeStreamClient([bytes([index]) * 16 for index in range(6)])

    chunks = await asyncio.gather(
        *(
            stream_namespace["_fetch_telegram_chunk"](4, client, object(), index)
            for index in range(6)
        )
    )

    assert chunks == [bytes([index]) * 16 for index in range(6)]
    assert client.max_in_flight == 2


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

    assert namespace["_transfer_prefetch_depth"](3) == 4
    fake_client_type.stream_loads[3] = 3
    assert namespace["_transfer_prefetch_depth"](3) == 2
    fake_client_type.stream_loads[3] = 8
    assert namespace["_transfer_prefetch_depth"](3) == 1


def test_runtime_snapshot_tracks_progress_speed_and_worker_health():
    namespace = {
        "FILETOLINK_CACHE_TOTAL_MAX_BYTES": 4096,
        "_filetolink_active_streams": {},
        "_filetolink_worker_counts": lambda: (2, 1),
        "monotonic": lambda: 100.0,
        "wall_time": lambda: 1000.0,
        "token_urlsafe": lambda _size: "transfer-1",
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

    namespace["_finish_filetolink_transfer"](transfer_id)
    assert namespace["_filetolink_active_streams"] == {}


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
        "Config": SimpleNamespace(BASE_URL="https://files.example"),
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
    assert buttons == [("↻ REFRESH", "status 77 fl"), ("↩ TASKS", "status 77 home")]

    snapshot.update({"stale": True, "transfers": [], "active_count": 0})
    text, buttons = namespace["build_filetolink_status"](77, standalone=True)
    assert "No active transfers" in text
    assert "🔴 Offline" in text
    assert buttons[-1] == ("✕ CLOSE", "status 77 dismiss")


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
