import asyncio
import importlib
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest


try:
    from aiohttp.client_exceptions import ClientError  # noqa: F401
except ModuleNotFoundError:
    aiohttp = ModuleType("aiohttp")
    client_exceptions = ModuleType("aiohttp.client_exceptions")

    class ClientError(Exception):
        pass

    client_exceptions.ClientError = ClientError
    aiohttp.client_exceptions = client_exceptions
    sys.modules.setdefault("aiohttp", aiohttp)
    sys.modules.setdefault("aiohttp.client_exceptions", client_exceptions)


@pytest.fixture
def direct_module(monkeypatch):
    """Load DirectListener without requiring the optional aria2 RPC client."""
    module_name = "bot.helper.listeners.direct_listener"
    existing = sys.modules.get(module_name)
    if existing is not None:
        yield existing
        return

    torrent_module = ModuleType("bot.core.torrent_manager")

    class TorrentManager:
        aria2 = None

        @staticmethod
        async def aria2_remove(_download):
            return None

    def aria2_name(download):
        return download.get("files", [{}])[0].get("path", "")

    torrent_module.TorrentManager = TorrentManager
    torrent_module.aria2_name = aria2_name
    monkeypatch.setitem(sys.modules, "bot.core.torrent_manager", torrent_module)
    loaded = importlib.import_module(module_name)
    yield loaded

    sys.modules.pop(module_name, None)
    listeners_package = sys.modules.get("bot.helper.listeners")
    if getattr(listeners_package, "direct_listener", None) is loaded:
        delattr(listeners_package, "direct_listener")


class _Listener:
    def __init__(self):
        self.is_cancelled = False
        self.name = "Collection"
        self.completed = 0
        self.errors = []

    async def on_download_complete(self):
        self.completed += 1

    async def on_download_error(self, error):
        self.errors.append(str(error))


class _ParallelAria2:
    def __init__(self):
        self.active = set()
        self.max_active = 0
        self.options = []
        self.polls = {}

    async def addUri(self, *, uris, options, position):
        gid = f"gid-{len(self.options)}"
        self.options.append((uris[0], options, position))
        self.polls[gid] = 0
        self.active.add(gid)
        self.max_active = max(self.max_active, len(self.active))
        return gid

    async def tellStatus(self, gid):
        self.polls[gid] += 1
        complete = self.polls[gid] >= 3
        return {
            "gid": gid,
            "status": "complete" if complete else "active",
            "completedLength": "10" if complete else "5",
            "totalLength": "10",
            "downloadSpeed": "0" if complete else "100",
            "dir": "/downloads",
            "files": [{"path": f"/downloads/{gid}.mkv"}],
        }


async def _yield_once(_delay):
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_direct_listener_downloads_files_with_bounded_parallelism(monkeypatch, direct_module):
    aria2 = _ParallelAria2()
    listener = _Listener()
    direct = direct_module.DirectListener("/downloads/Collection", listener, {"header": "X: y"})
    direct.parallelism = 3

    async def remove_download(download):
        aria2.active.discard(download["gid"])

    monkeypatch.setattr(direct_module.TorrentManager, "aria2", aria2)
    monkeypatch.setattr(
        direct_module.TorrentManager,
        "aria2_remove",
        AsyncMock(side_effect=remove_download),
    )
    monkeypatch.setattr(direct_module, "sleep", _yield_once)

    contents = [
        {
            "url": f"https://index.example/file-{index}.mkv",
            "filename": f"file-{index}.mkv",
            "path": f"Season {index % 2}",
        }
        for index in range(7)
    ]
    await direct.download(contents)

    assert aria2.max_active == 3
    assert direct.processed_bytes == 70
    assert direct.speed == 0
    assert direct.download_tasks == {}
    assert listener.completed == 1
    assert listener.errors == []
    assert [options["out"] for _, options, _ in aria2.options] == [
        item["filename"] for item in contents
    ]
    assert [options["dir"] for _, options, _ in aria2.options] == [
        f"/downloads/Collection/{item['path']}" for item in contents
    ]
    assert len({id(options) for _, options, _ in aria2.options}) == len(contents)


def test_direct_listener_aggregates_live_progress_and_speed(direct_module):
    direct = direct_module.DirectListener("/downloads/Collection", _Listener(), {})
    direct._proc_bytes = 100
    direct.download_tasks = {
        "one": {"completedLength": "20", "downloadSpeed": "50", "status": "active"},
        "two": {"completedLength": "30", "downloadSpeed": "70", "status": "waiting"},
    }

    assert direct.processed_bytes == 150
    assert direct.speed == 120
    assert direct.all_waiting is False

    direct.download_tasks["one"]["status"] = "waiting"
    assert direct.all_waiting is True


def test_direct_parallelism_config_is_clamped(monkeypatch, direct_module):
    config = direct_module.Config
    monkeypatch.setattr(config, "DIRECT_PARALLELISM", 4)

    config.set("DIRECT_PARALLELISM", 0)
    assert config.DIRECT_PARALLELISM == 1

    config.set("DIRECT_PARALLELISM", 99)
    assert config.DIRECT_PARALLELISM == 16


@pytest.mark.asyncio
async def test_direct_listener_cancels_every_active_file_before_reporting_error(
    monkeypatch, direct_module
):
    listener = _Listener()
    direct = direct_module.DirectListener("/downloads/Collection", listener, {})
    direct.download_tasks = {
        "one": {"gid": "one", "status": "active"},
        "two": {"gid": "two", "status": "waiting"},
    }
    events = []

    async def remove_download(download):
        events.append(("removed", download["gid"]))

    async def report_error(error):
        events.append(("error", str(error)))
        listener.errors.append(str(error))

    monkeypatch.setattr(
        direct_module.TorrentManager,
        "aria2_remove",
        AsyncMock(side_effect=remove_download),
    )
    monkeypatch.setattr(listener, "on_download_error", report_error)

    await direct.cancel_task()

    assert listener.is_cancelled is True
    assert set(events[:2]) == {("removed", "one"), ("removed", "two")}
    assert events[2] == ("error", "Download Cancelled by User!")


@pytest.mark.asyncio
async def test_direct_listener_removes_job_when_initial_status_request_fails(
    monkeypatch, direct_module
):
    class _StatusFailureAria2:
        async def addUri(self, **_kwargs):
            return "accepted-gid"

        async def tellStatus(self, _gid):
            raise ClientError("RPC unavailable")

    listener = _Listener()
    direct = direct_module.DirectListener("/downloads/Collection", listener, {})
    remove = AsyncMock()
    monkeypatch.setattr(direct_module.TorrentManager, "aria2", _StatusFailureAria2())
    monkeypatch.setattr(direct_module.TorrentManager, "aria2_remove", remove)

    await direct.download(
        [
            {
                "url": "https://index.example/episode.mkv",
                "filename": "episode.mkv",
                "path": "",
            }
        ]
    )

    remove.assert_awaited_once_with({"gid": "accepted-gid", "status": "active"})
    assert direct.download_tasks == {}
    assert listener.completed == 0
    assert listener.errors == ["All files are failed to download!"]
