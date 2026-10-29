import ast
import asyncio
import logging
import os
import time
from pathlib import Path
from time import monotonic
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import raw
from pyrogram.errors import FloodWait

from bot.core.config_manager import Config
from bot.core.tg_client import TgClient
from bot.helper.ext_utils import hyperdl_utils
from bot.helper.ext_utils.hyperdl_utils import HypertgDownload
from bot.helper.telegram_helper import tg_transfer


def _load_scheduling_class(relative_path, name, methods, module):
    # Load scheduling without importing Linux-only media probing dependencies.
    path = Path(__file__).parents[1] / relative_path
    node = next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.ClassDef) and n.name == name)
    node.body = [n for n in node.body if getattr(n, "name", None) in methods]
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), module.__dict__)
    return getattr(module, name)


hyperul_utils = ModuleType("hypertg_upload_scheduling")
hyperul_utils.__dict__.update(
    HypertgTransfer=tg_transfer.HypertgTransfer, Config=Config,
    Semaphore=asyncio.Semaphore, Lock=asyncio.Lock, sleep=asyncio.sleep,
    monotonic=monotonic, time=time.time, ospath=os.path,
    LOGGER=logging.getLogger(__name__), FloodWait=FloodWait, FloodPremiumWait=FloodWait,
)
HypertgUpload = _load_scheduling_class(
    "bot/helper/ext_utils/hyperul_utils.py", "HypertgUpload",
    {"__init__", "_hyper_send", "_send_with_retry", "_progress"}, hyperul_utils,
)
TelegramUploader = _load_scheduling_class(
    "bot/helper/mirror_leech_utils/upload_utils/telegram_uploader.py", "TelegramUploader",
    {"__init__"}, hyperul_utils,
)


@pytest.fixture
def helpers(monkeypatch):
    bots = {i: SimpleNamespace(me=SimpleNamespace(is_premium=False)) for i in range(1, 9)}
    users = {i: SimpleNamespace(me=SimpleNamespace(is_premium=True)) for i in range(1, 3)}
    monkeypatch.setattr(TgClient, "helper_bots", bots)
    monkeypatch.setattr(TgClient, "helper_users", users)
    monkeypatch.setattr(TgClient, "user", None)
    monkeypatch.setattr(tg_transfer, "_global_work_loads", None)
    monkeypatch.setattr(Config, "USE_HYPER", True)
    monkeypatch.setattr(Config, "LEECH_DUMP_CHAT", -100123)
    return bots, users


def test_download_auto_uses_all_helpers_and_preserves_explicit_cap(helpers, monkeypatch):
    monkeypatch.setattr(Config, "HYPER_THREADS", 0)
    obj = SimpleNamespace(_listener=SimpleNamespace(transmission_mode="both"))
    assert HypertgDownload(obj).num_parts == 10
    monkeypatch.setattr(Config, "HYPER_THREADS", 2)
    assert HypertgDownload(obj).num_parts == 2


@pytest.mark.parametrize("mode,limit,expected", [
    ("bot", 0, 8), ("user", 0, 3), ("both", 0, 10), ("both", 2, 2),
])
def test_upload_auto_scales_to_eligible_helpers(helpers, monkeypatch, mode, limit, expected):
    monkeypatch.setattr(Config, "UPLOAD_PARALLELISM", limit)
    listener = SimpleNamespace(transmission_mode=mode, thumb=None, user_id=123)
    uploader = TelegramUploader(listener, "uploads")
    assert uploader._file_upload_parallelism == expected


def test_upload_auto_keeps_preparation_bounded_for_large_helper_pools(helpers, monkeypatch):
    bots, _users = helpers
    bots.update({i: SimpleNamespace() for i in range(9, 51)})
    monkeypatch.setattr(Config, "UPLOAD_PARALLELISM", 0)
    listener = SimpleNamespace(transmission_mode="bot", thumb=None, user_id=123)
    assert TelegramUploader(listener, "uploads")._file_upload_parallelism == 16
    monkeypatch.setattr(Config, "USE_HYPER", False)
    assert TelegramUploader(listener, "uploads")._file_upload_parallelism == 3


@pytest.mark.asyncio
async def test_reference_retry_respects_account_download_cooldown(helpers, monkeypatch):
    now = [100.0]
    invoked = []
    bots, _users = helpers
    client = bots[1]

    async def get_messages(*_args):
        invoked.append(now[0])
        if len(invoked) == 1:
            raise FloodWait(3)
        return SimpleNamespace(document=SimpleNamespace(file_id="reference"))

    async def pause(delay):
        now[0] += delay

    client.get_messages = get_messages
    monkeypatch.setattr(tg_transfer, "monotonic", lambda: now[0])
    monkeypatch.setattr(tg_transfer, "sleep", pause)
    monkeypatch.setattr(hyperdl_utils, "sleep", AsyncMock())
    fid = SimpleNamespace(dc_id=5)
    monkeypatch.setattr(hyperdl_utils.FileId, "decode", lambda _value: fid)
    downloader = HypertgDownload(SimpleNamespace(_listener=object()))
    downloader.message, downloader.dump_chat = SimpleNamespace(id=42), -100123
    assert await downloader._fetch_ref(1, client) is fid
    assert invoked == [100, 104]
    assert tg_transfer._download_pacer(client).flood_until == 104


@pytest.mark.asyncio
@pytest.mark.parametrize("premium,per_account", [(False, 2), (True, 1)])
async def test_helper_uploads_share_account_gates_and_release_cancelled_loads(premium, per_account):
    clients = {i: SimpleNamespace(me=SimpleNamespace(is_premium=premium)) for i in range(1, 6)}
    loads = dict.fromkeys(clients, 0)
    active = dict.fromkeys(clients, 0)
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(_key, client, _kwargs):
        idx = next(i for i, value in clients.items() if value is client)
        active[idx] += 1
        if sum(active.values()) == len(clients) * per_account:
            entered.set()
        try:
            await release.wait()
            return "sent"
        finally:
            active[idx] -= 1

    uploaders = [object.__new__(HypertgUpload) for _ in range(2)]
    for uploader in uploaders:
        uploader.clients, uploader.work_loads = clients, loads
        uploader._try_send, uploader._progress = send, AsyncMock()
    previous = asyncio.all_tasks()
    tasks = [asyncio.create_task(uploaders[i % 2]._hyper_send(
        f"file-{i}.zip", "documents", None, "caption", -100123, None,
    )) for i in range(20)]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert set(active.values()) == {per_account}
        assert sum(loads.values()) == 20
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert set(loads.values()) == {0}
    assert set(active.values()) == {0}
    assert all(c._amaterasu_hyper_upload_gate._value == per_account for c in clients.values())
    assert not (asyncio.all_tasks() - previous)


def test_helper_selection_prefers_healthy_accounts_without_crossing_account_type():
    uploader = object.__new__(HypertgUpload)
    uploader.clients = {1: SimpleNamespace(), 2: SimpleNamespace(), -1: SimpleNamespace()}
    uploader.work_loads = {1: 0, 2: 1, -1: 0}
    uploader.clients[1]._amaterasu_send_flood_until = monotonic() + 60
    assert uploader._pick_client(user_only=False) == 2
    uploader.clients[1]._amaterasu_send_flood_until = 0
    uploader.clients[1]._amaterasu_upload_pacer = SimpleNamespace(flood_until=monotonic() + 60)
    assert uploader._pick_client(user_only=False) == 2
    assert uploader._pick_client(user_only=True) == -1


@pytest.mark.asyncio
async def test_send_cooldown_is_shared_and_honors_extensions(monkeypatch):
    now = [100.0]
    sleeping = asyncio.Event()
    calls = sleeps = 0

    async def pause(delay):
        nonlocal sleeps
        assert delay > 0
        sleeps += 1
        if sleeps == 2:
            sleeping.set()
        await release.wait()

    class Client:
        async def send(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FloodWait(10)
            return "sent"

    release = asyncio.Event()
    monkeypatch.setattr(hyperul_utils, "monotonic", lambda: now[0])
    monkeypatch.setattr(hyperul_utils, "sleep", pause)
    client = Client()
    uploader = object.__new__(HypertgUpload)
    uploader._up_file = "file.zip"
    first = asyncio.create_task(uploader._send_with_retry(client.send))
    await asyncio.sleep(0)
    second = asyncio.create_task(uploader._send_with_retry(client.send))
    try:
        await asyncio.wait_for(sleeping.wait(), 1)
        assert calls == 1
        assert client._amaterasu_send_flood_until == 111
        client._amaterasu_send_flood_until = 121
        now[0] = 111
        # Wake both waiters once; they must recheck the extended deadline.
        async def finish_wait(delay):
            assert delay == 10
            now[0] = 121
        monkeypatch.setattr(hyperul_utils, "sleep", finish_wait)
        release.set()
        assert await asyncio.wait_for(asyncio.gather(first, second), 1) == ["sent", "sent"]
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
    assert calls == 3


@pytest.mark.asyncio
async def test_download_admission_is_shared_across_transfers_but_separate_per_account():
    first, second = SimpleNamespace(), SimpleNamespace()
    assert tg_transfer._download_pacer(first) is tg_transfer._download_pacer(first)
    assert tg_transfer._download_pacer(first) is not tg_transfer._download_pacer(second)
    pacer = tg_transfer._download_pacer(first)
    pacer.bucket.acquire = AsyncMock()
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0

    async def invoke(_query, **kwargs):
        nonlocal active
        assert kwargs == {"retries": 1, "timeout": 15, "sleep_threshold": 0}
        active += 1
        if active == 24:
            entered.set()
        try:
            await release.wait()
            return raw.types.upload.File(type=raw.types.storage.FileUnknown(), mtime=0, bytes=b"part")
        finally:
            active -= 1

    downloaders = [object.__new__(HypertgDownload) for _ in range(2)]
    tasks = [asyncio.create_task(downloaders[i % 2]._do_req(
        SimpleNamespace(invoke=invoke), first, "location", i * 1024, 1024,
    )) for i in range(48)]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert active == 24
        async with tg_transfer._download_pacer(second).slot():
            assert active == 24
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert active == 0
    assert pacer.in_flight._value == 24


@pytest.mark.asyncio
async def test_download_cooldown_extends_and_cancellation_releases_admission(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tg_transfer, "monotonic", lambda: now[0])
    pacer = tg_transfer._DownloadPacer()
    with pytest.raises(FloodWait):
        async with pacer.slot():
            raise FloodWait(10)
    assert pacer.flood_until == 111
    assert pacer.bucket.rate < 32
    sleeping, release = asyncio.Event(), asyncio.Event()
    delays = []

    async def pause(delay):
        delays.append(delay)
        sleeping.set()
        await release.wait()
        release.clear()

    monkeypatch.setattr(tg_transfer, "sleep", pause)
    admitted = False

    async def request():
        nonlocal admitted
        async with pacer.slot():
            admitted = True

    task = asyncio.create_task(request())
    try:
        await asyncio.wait_for(sleeping.wait(), 1)
        sleeping.clear()
        pacer.flood_until = 121
        now[0] = 111
        release.set()
        await asyncio.wait_for(sleeping.wait(), 1)
        assert delays == [11, 10]
        assert not admitted
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert pacer.in_flight._value == 24
    assert not pacer.lock.locked()
