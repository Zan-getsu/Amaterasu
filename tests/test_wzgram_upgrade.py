import ast
import asyncio
import gc
import os
import warnings
from contextlib import asynccontextmanager
from importlib import import_module
from importlib.metadata import version as package_version
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pyrogram
import pytest
import warpcrypto
from pyrogram import Client
from pyrogram.connection.transport.tcp import TCP, TCPAbridged
from pyrogram.crypto import aes
from pyrogram.dispatcher import Dispatcher
from pyrogram.errors import FloodPremiumWait, FloodWait
from pyrogram.handlers import (
    ConnectHandler,
    DisconnectHandler,
    StartHandler,
    StopHandler,
)
from pyrogram.methods.advanced import save_file
from pyrogram.session import Session

from bot.core import tg_client
from bot.core.tg_client import (
    WZGRAM_MEDIA_RESET_COOLDOWN,
    WZGRAM_MEDIA_RESTART_ATTEMPTS,
    WZGRAM_UPLOAD_PART_ATTEMPTS,
    WzgramClient,
    _configure_wzgram_media_pool,
    _configure_wzgram_upload_module,
    _WzgramAsyncioProxy,
    _WzgramUploadPacer,
    _WzgramUploadQueue,
    is_wzgram_media_session_failure,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WZGRAM_VERSION = "3.1.5"
EXPECTED_WARPCRYPTO_VERSION = "2.0.8"


def test_socket_reader_guard_is_idempotent():
    receive = TCP._recv_from_socket
    tg_client._configure_wzgram_socket_reader()
    assert TCP._recv_from_socket is receive


async def test_failed_socket_timeout_does_not_retain_retry_tracebacks():
    transport = TCP()
    transport.reader = asyncio.StreamReader()
    socket_error = TimeoutError(110, "Connection timed out")
    transport.reader.set_exception(socket_error)

    for _ in range(100):
        with pytest.raises(ConnectionError, match="persistent read timeout"):
            await transport._recv_from_socket(1)

    assert socket_error.__traceback__ is None


async def test_failed_socket_timeout_reconnects_instead_of_spinning():
    transport = TCPAbridged()
    transport.reader = asyncio.StreamReader()
    transport.reader.set_exception(TimeoutError(110, "Connection timed out"))
    receive_attempts = 0

    async def receive():
        nonlocal receive_attempts
        receive_attempts += 1
        if receive_attempts > 1:
            raise RuntimeError("Retried a permanently failed socket")
        return await transport.recv()

    session = object.__new__(Session)
    session.connection = SimpleNamespace(recv=receive)
    session.is_started = asyncio.Event()
    session.is_started.set()
    session._teardown_started = False
    session._stopping = False
    session._fail_pending = Mock()
    session._safe_restart = AsyncMock()

    await session.recv_worker()

    assert receive_attempts == 1
    session._safe_restart.assert_awaited_once()
    session._fail_pending.assert_called_once()
    assert isinstance(session._fail_pending.call_args.args[0], ConnectionResetError)


async def test_idle_socket_timeout_can_receive_data_later(monkeypatch):
    transport = TCP()
    transport.reader = asyncio.StreamReader()
    monkeypatch.setattr(TCP, "TIMEOUT", 0.01)

    with pytest.raises(TimeoutError, match="Socket read timed out"):
        await transport._recv_from_socket(1)

    assert transport.reader.exception() is None
    transport.reader.feed_data(b"ok")
    assert await transport._recv_from_socket(2) == b"ok"


async def test_partial_packet_timeout_reconnects_instead_of_reusing_socket(monkeypatch):
    transport = TCPAbridged()
    transport.reader = asyncio.StreamReader()
    # A two-word frame with only one word available reproduces the production timeout.
    transport.reader.feed_data(b"\x02abcd")
    monkeypatch.setattr(TCP, "TIMEOUT", 0.01)
    receive = AsyncMock(side_effect=transport.recv)
    session = object.__new__(Session)
    session.connection = SimpleNamespace(recv=receive)
    session.is_started = asyncio.Event()
    session.is_started.set()
    session._teardown_started = False
    session._stopping = False
    session._fail_pending = Mock()
    session._safe_restart = AsyncMock()

    await session.recv_worker()

    receive.assert_awaited_once()
    session._safe_restart.assert_awaited_once()
    session._fail_pending.assert_called_once()
    error = session._fail_pending.call_args.args[0]
    assert isinstance(error, ConnectionResetError)
    assert "desynchronised mid-message" in str(error)


async def test_socket_failure_during_read_stops_on_next_attempt():
    transport = TCP()
    transport.reader = asyncio.StreamReader()
    socket_error = TimeoutError(110, "Connection timed out")
    asyncio.get_running_loop().call_soon(transport.reader.set_exception, socket_error)

    with pytest.raises(TimeoutError, match="Socket read timed out"):
        await transport._recv_from_socket(1)

    retained_traceback = socket_error.__traceback__
    for _ in range(100):
        with pytest.raises(ConnectionError, match="persistent read timeout"):
            await transport._recv_from_socket(1)
    assert socket_error.__traceback__ is retained_traceback


async def test_socket_read_cancellation_is_preserved():
    transport = TCP()
    transport.reader = asyncio.StreamReader()
    task = asyncio.create_task(transport._recv_from_socket(1))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.reader.exception() is None


def test_all_amaterasu_pyrogram_imports_resolve_with_wzgram():
    failures = []
    for source_root in ("bot", "plugins", "gen_scripts"):
        for path in (ROOT / source_root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if not node.module or not node.module.startswith("pyrogram"):
                    continue
                module = import_module(node.module)
                for alias in node.names:
                    if alias.name != "*" and not hasattr(module, alias.name):
                        failures.append(f"{path}:{node.lineno} {node.module}.{alias.name}")

    assert not failures, "WZGram API compatibility failures:\n" + "\n".join(failures)


def test_wzgram_runtime_and_accelerator_are_current():
    assert pyrogram.__version__ == EXPECTED_WZGRAM_VERSION
    assert package_version("warpcrypto") == EXPECTED_WARPCRYPTO_VERSION
    assert getattr(aes, "warpcrypto", None) is warpcrypto
    assert hasattr(Client, "_get_media_session_pool")
    assert callable(getattr(save_file, "_stop_workers", None))
    assert save_file.MAX_RETRIES == WZGRAM_UPLOAD_PART_ATTEMPTS
    assert not isinstance(save_file.asyncio, _WzgramAsyncioProxy)


def test_legacy_wzgram_upload_cleanup_guard_remains_available():
    legacy_module = SimpleNamespace(MAX_RETRIES=16, asyncio=asyncio)

    assert _configure_wzgram_upload_module(legacy_module) == "compatibility"
    assert legacy_module.MAX_RETRIES == WZGRAM_UPLOAD_PART_ATTEMPTS
    assert isinstance(legacy_module.asyncio, _WzgramAsyncioProxy)

    guarded_asyncio = legacy_module.asyncio
    assert _configure_wzgram_upload_module(legacy_module) == "compatibility"
    assert legacy_module.asyncio is guarded_asyncio


def test_native_upload_cancellation_guard_is_installed_only_once():
    stop_workers = save_file._stop_workers
    assert _configure_wzgram_upload_module(save_file) == "native"
    assert save_file._stop_workers is stop_workers


def test_wzgram_version_is_consistent_across_deployment_files():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    cli_requirements = (
        ROOT / "gen_scripts" / "config" / "requirements-cli.txt"
    ).read_text(encoding="utf-8")
    session_generator = (
        ROOT / "gen_scripts" / "gen_pyro_session" / "script.py"
    ).read_text(encoding="utf-8")
    session_readme = (
        ROOT / "gen_scripts" / "gen_pyro_session" / "README.md"
    ).read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in requirements
    assert f"warpcrypto=={EXPECTED_WARPCRYPTO_VERSION}" in requirements
    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in cli_requirements
    assert f"warpcrypto=={EXPECTED_WARPCRYPTO_VERSION}" in cli_requirements
    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in session_generator
    assert f'wzgram[fast]=={EXPECTED_WZGRAM_VERSION}' in session_readme
    assert "pip install pyrogram tgcrypto" not in session_readme
    assert f"pyrogram.__version__ == '{EXPECTED_WZGRAM_VERSION}'" in dockerfile
    assert f"version('warpcrypto') == '{EXPECTED_WARPCRYPTO_VERSION}'" in dockerfile
    assert f"WZGram {EXPECTED_WZGRAM_VERSION} (`pyrogram` API)" in readme
    assert f"Framework-WZGram_{EXPECTED_WZGRAM_VERSION}" in readme


def test_amaterasu_prefers_wzgram_native_media_pool_with_fallback():
    source = (ROOT / "bot" / "core" / "tg_client.py").read_text(encoding="utf-8")
    uploader_source = (
        ROOT
        / "bot"
        / "helper"
        / "mirror_leech_utils"
        / "upload_utils"
        / "telegram_uploader.py"
    ).read_text(encoding="utf-8")

    assert "await super()._get_media_session_pool(dc_id, requested_size)" in source
    assert "pool = await _get_stable_media_session_pool(" in source
    assert "await self._reset_failed_wzgram_pool(err, user_session)" in uploader_source
    assert 'backend != "WZGram"' in uploader_source


def test_handler_registration_is_safe_while_event_loop_is_stopped():
    client = object.__new__(WzgramClient)
    client.loop = asyncio.new_event_loop()
    client.dispatcher = Dispatcher(SimpleNamespace(listeners=None))
    client.connect_handler = None
    client.disconnect_handler = None
    client.start_handler = None
    client.stop_handler = None
    first_handler = object()
    second_handler = object()

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            assert client.add_handler(first_handler, 5) == (first_handler, 5)
            assert client.add_handler(second_handler, -1) == (second_handler, -1)
            gc.collect()

        assert not [warning for warning in caught if "never awaited" in str(warning.message)]
        assert list(client.dispatcher.groups) == [-1, 5]
        assert client.dispatcher.groups[5] == [first_handler]

        assert client.remove_handler(first_handler, 5) is None
        assert 5 not in client.dispatcher.groups

        async def lifecycle_callback(*_):
            return None

        for handler_type, attribute in (
            (ConnectHandler, "connect_handler"),
            (DisconnectHandler, "disconnect_handler"),
            (StartHandler, "start_handler"),
            (StopHandler, "stop_handler"),
        ):
            handler = handler_type(lifecycle_callback)
            assert client.add_handler(handler) == (handler, 0)
            assert getattr(client, attribute) is lifecycle_callback
            assert client.remove_handler(handler) is None
            assert getattr(client, attribute) is None
    finally:
        client.loop.close()


async def test_dump_upload_keeps_its_log_anchor_in_user_mode():
    from pyrogram.enums import ChatType

    source_path = (
        ROOT
        / "bot"
        / "helper"
        / "mirror_leech_utils"
        / "upload_utils"
        / "telegram_uploader.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    uploader_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TelegramUploader"
    )
    method_node = next(
        node
        for node in uploader_node.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_msg_to_reply"
    )

    async def call_with_flood_retry(method, *args, **kwargs):
        return await method(*args, **kwargs)

    namespace = {
        "__package__": "bot.helper.mirror_leech_utils.upload_utils",
        "ChatType": ChatType,
        "_call_with_flood_retry": call_with_flood_retry,
    }
    harness_node = ast.ClassDef(
        name="UploaderHarness",
        bases=[],
        keywords=[],
        body=[method_node],
        decorator_list=[],
    )
    module_node = ast.fix_missing_locations(
        ast.Module(body=[harness_node], type_ignores=[])
    )
    exec(compile(module_node, str(source_path), "exec"), namespace)
    UploaderHarness = namespace["UploaderHarness"]

    command_chat = SimpleNamespace(id=-100111, type=ChatType.SUPERGROUP)
    dump_chat = SimpleNamespace(id=-100222, type=ChatType.SUPERGROUP)
    command = SimpleNamespace(id=41, chat=command_chat, link="https://t.me/c/111/41")
    bot_log = SimpleNamespace(id=87, chat=dump_chat)
    user_log = SimpleNamespace(id=87, chat=dump_chat)
    command_client = SimpleNamespace(
        get_messages=AsyncMock(),
        send_message=AsyncMock(),
    )
    bot_client = SimpleNamespace(send_message=AsyncMock(return_value=bot_log))
    user_client = SimpleNamespace(get_messages=AsyncMock(return_value=user_log))
    listener = SimpleNamespace(
        up_dest=dump_chat.id,
        message=command,
        message_id=command.id,
        is_super_chat=True,
        user=SimpleNamespace(mention="Tester"),
        user_id=1234,
        source_url="https://example.com/file",
        chat_thread_id=None,
        client=command_client,
        on_upload_error=AsyncMock(),
    )
    uploader = object.__new__(UploaderHarness)
    uploader._listener = listener
    uploader._user_session = True
    uploader._sent_msg = None
    uploader._log_msg = None
    uploader._is_private = False

    namespace["TgClient"] = SimpleNamespace(bot=bot_client, user=user_client)

    assert await uploader._msg_to_reply() is True
    assert uploader._sent_msg is user_log
    user_client.get_messages.assert_awaited_once_with(
        chat_id=dump_chat.id,
        message_ids=bot_log.id,
    )
    command_client.get_messages.assert_not_awaited()
    command_client.send_message.assert_not_awaited()
    listener.on_upload_error.assert_not_awaited()


async def test_mongodb_pool_does_not_force_idle_dns_connections(monkeypatch):
    from bot.core.config_manager import Config
    from bot.helper.ext_utils import db_handler

    class Collection:
        async def create_index(self, *args, **kwargs):
            return kwargs.get("name")

    class Database:
        blacklisted_users = Collection()
        user_stats = Collection()
        google_oauth_states = Collection()

    class MotorClient:
        def __init__(self, url, **kwargs):
            self.url = url
            self.options = kwargs
            self.admin = SimpleNamespace(command=AsyncMock(return_value={"ok": 1}))
            self.amaterasu = Database()

        def close(self):
            return None

    monkeypatch.setattr(Config, "DATABASE_URL", "mongodb://database.example")
    monkeypatch.setattr(db_handler, "AsyncIOMotorClient", MotorClient)
    manager = db_handler.DbManager()

    await manager.connect()

    assert manager._return is False
    assert manager._conn.options["maxPoolSize"] == 50
    assert manager._conn.options["minPoolSize"] == 0
    assert "serverSelectionTimeoutMS" not in manager._conn.options
    assert "connectTimeoutMS" not in manager._conn.options


def test_failed_media_sessions_are_bounded_and_recognized():
    session = type("Session", (), {"MAX_RETRIES": 10})()

    assert _configure_wzgram_media_pool([session]) == [session]
    assert session.MAX_RETRIES == WZGRAM_MEDIA_RESTART_ATTEMPTS
    assert is_wzgram_media_session_failure(TimeoutError("Request timed out"))
    assert not is_wzgram_media_session_failure(ValueError("invalid thumbnail"))


async def test_failed_media_pool_is_stopped_and_removed():
    stopped = []

    class Session:
        def __init__(self):
            from asyncio import Event

            self.is_started = Event()
            self.is_started.set()

        async def stop(self):
            stopped.append(self)

    class Storage:
        @staticmethod
        async def dc_id():
            return 2

    client = object.__new__(WzgramClient)
    sessions = [Session(), Session()]
    client.storage = Storage()
    client.media_session_pools = {2: sessions}
    client.media_sessions = {}
    client._media_sessions_locks = {}

    assert await client.reset_media_session_pool(reason="TimeoutError") == 2
    assert client.media_session_pools == {}
    assert stopped == sessions

    replacement = Session()
    client.media_session_pools = {2: [replacement]}
    assert await client.reset_media_session_pool(reason="TimeoutError") == 0
    assert client.media_session_pools == {2: [replacement]}
    assert replacement not in stopped

    client._amaterasu_media_reset_at[2] -= WZGRAM_MEDIA_RESET_COOLDOWN
    assert await client.reset_media_session_pool(reason="TimeoutError") == 1
    assert replacement in stopped


@pytest.mark.parametrize("flood_type", [FloodWait, FloodPremiumWait])
@pytest.mark.parametrize("wait_seconds", [1, 600])
async def test_upload_part_flood_pauses_all_sessions_for_the_full_wait(
    monkeypatch, flood_type, wait_seconds
):
    clock = [100.0]
    observed = []

    async def pause(delay):
        clock[0] += delay
        await asyncio.sleep(0)

    async def accepted(query, **kwargs):
        observed.append((clock[0], query, kwargs))
        return True

    monkeypatch.setattr(tg_client, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tg_client, "sleep", pause)
    client = SimpleNamespace(me=SimpleNamespace(is_bot=True, is_premium=False))
    first = SimpleNamespace(
        client=client, invoke=AsyncMock(side_effect=flood_type(wait_seconds)),
    )
    second = SimpleNamespace(client=client, invoke=AsyncMock(side_effect=accepted))
    _configure_wzgram_media_pool([first, second])
    part = pyrogram.raw.functions.upload.SaveBigFilePart(
        file_id=123, file_part=0, file_total_parts=2, bytes=b"part",
    )
    with pytest.raises(flood_type):
        await first.invoke(part, sleep_threshold=0)

    await asyncio.gather(*(second.invoke(part, sleep_threshold=0) for _ in range(3)))

    assert len(observed) == 3
    assert all(when >= 100 + wait_seconds + 1 for when, _, _ in observed)
    assert all(query is part and kwargs == {"sleep_threshold": 0} for _, query, kwargs in observed)
    assert first._amaterasu_upload_pacer is second._amaterasu_upload_pacer


async def test_upload_part_guard_preserves_other_calls_and_installation_is_idempotent():
    client = SimpleNamespace(me=SimpleNamespace(is_bot=True, is_premium=False))
    invoke = AsyncMock(return_value=True)
    session = SimpleNamespace(client=client, invoke=invoke)
    _configure_wzgram_media_pool([session])
    guarded = session.invoke
    _configure_wzgram_media_pool([session])
    assert session.invoke is guarded
    session._amaterasu_upload_pacer.flood_until = float("inf")
    query = SimpleNamespace(QUALNAME="upload.GetFile")

    assert await session.invoke(query, timeout=5) is True
    invoke.assert_awaited_once_with(query, timeout=5)


async def test_upload_part_guard_preserves_failures_and_cancellation():
    client = SimpleNamespace(me=SimpleNamespace(is_bot=True, is_premium=False))
    error = OSError("connection lost")
    session = SimpleNamespace(client=client, invoke=AsyncMock(side_effect=error))
    _configure_wzgram_media_pool([session])
    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")
    with pytest.raises(OSError) as caught:
        await session.invoke(part)
    assert caught.value is error

    cancelled = SimpleNamespace(client=client, invoke=AsyncMock(side_effect=asyncio.CancelledError()))
    _configure_wzgram_media_pool([cancelled])
    with pytest.raises(asyncio.CancelledError):
        await cancelled.invoke(part)


@pytest.mark.parametrize("phase", ["capacity", "pacing", "cooldown", "rpc"])
async def test_cancelled_upload_releases_admission_for_the_next_transfer(monkeypatch, phase):
    monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    pacer = _WzgramUploadPacer(SimpleNamespace(me=SimpleNamespace(is_bot=True)))
    entered = asyncio.Event()
    blocked = asyncio.Event()

    async def wait(*_args):
        entered.set()
        await blocked.wait()

    if phase == "capacity":
        for _ in range(16):
            await pacer.in_flight.acquire()
    elif phase == "pacing":
        pacer.bucket.acquire = wait
    elif phase == "cooldown":
        pacer.flood_until = float("inf")
        monkeypatch.setattr(tg_client, "sleep", wait)

    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")
    operation = wait if phase == "rpc" else AsyncMock(return_value=True)
    task = asyncio.create_task(pacer.invoke(operation, part))
    if phase == "capacity":
        await asyncio.sleep(0)
    else:
        await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    if phase == "capacity":
        for _ in range(16):
            pacer.in_flight.release()
    pacer.flood_until = 0
    pacer.bucket.acquire = AsyncMock()
    assert not pacer.lock.locked()
    assert pacer.in_flight._value == 16
    assert await pacer.invoke(AsyncMock(return_value=True), part) is True
    assert pacer.in_flight._value == 16


async def test_upload_rechecks_cooldown_extended_while_waiting_for_a_token(monkeypatch):
    clock = [100.0]
    pacer = _WzgramUploadPacer(SimpleNamespace(me=SimpleNamespace(is_bot=True)))

    async def pause(delay):
        clock[0] += delay

    async def acquire():
        if pacer.bucket.acquire.await_count == 1:
            pacer.flood_until = clock[0] + 10

    monkeypatch.setattr(tg_client, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tg_client, "sleep", pause)
    pacer.bucket.acquire = AsyncMock(side_effect=acquire)
    operation = AsyncMock(return_value=True)
    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")

    assert await pacer.invoke(operation, part) is True
    assert clock[0] == 110
    assert pacer.bucket.acquire.await_count == 2
    operation.assert_awaited_once_with(part)


async def test_native_simultaneous_uploads_recover_without_losing_parts(monkeypatch):
    clock = [100.0]
    accepted = []
    flooded = []
    pool_sizes = []

    async def pause(delay):
        clock[0] += delay
        await asyncio.sleep(0)

    class AsyncioProxy:
        sleep = staticmethod(pause)

        def __getattr__(self, name):
            return getattr(asyncio, name)

    async def send_part(query, **_kwargs):
        if not flooded:
            flooded.append(query)
            raise FloodWait(1)
        accepted.append((clock[0], query.file_id, query.file_part))
        return True

    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "1000")
    monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    _configure_wzgram_upload_module(save_file)
    monkeypatch.setattr(tg_client, "monotonic", lambda: clock[0])
    monkeypatch.setattr(tg_client, "sleep", pause)
    monkeypatch.setattr(save_file, "asyncio", AsyncioProxy())
    file_ids = iter([123, 456])
    client = SimpleNamespace(
        me=SimpleNamespace(is_bot=True, is_premium=False),
        save_file_semaphore=asyncio.Semaphore(2),
        loop=asyncio.get_running_loop(),
        executor=None,
        read_ahead_slots=asyncio.Semaphore(16),
        storage=SimpleNamespace(dc_id=AsyncMock(return_value=2)),
        rnd_id=lambda: next(file_ids),
    )
    sessions = [SimpleNamespace(client=client, invoke=send_part) for _ in range(2)]

    @asynccontextmanager
    async def media_pool(_dc_id, _pool_size):
        pool_sizes.append(_pool_size)
        async def ready():
            return _configure_wzgram_media_pool(sessions)

        yield asyncio.create_task(ready())

    client._media_pool = media_pool
    data = b"x" * (12 * 1024 * 1024)
    results = await asyncio.wait_for(
        asyncio.gather(*(
            save_file.SaveFile.save_file(client, BytesIO(data)) for _ in range(2)
        )),
        timeout=5,
    )

    assert all(isinstance(result, pyrogram.raw.types.InputFileBig) for result in results)
    assert all(result.parts == 24 for result in results)
    assert len(accepted) == 48
    assert {(file_id, part) for _, file_id, part in accepted} == {
        (file_id, part) for file_id in [123, 456] for part in range(24)
    }
    assert all(when >= 102 for when, _, _ in accepted)
    assert pool_sizes == [8, 8]


async def test_upload_cooldown_is_separate_for_other_accounts():
    clients = [SimpleNamespace(me=SimpleNamespace(is_bot=True)) for _ in range(2)]
    sessions = [SimpleNamespace(client=client, invoke=AsyncMock(return_value=True)) for client in clients]
    _configure_wzgram_media_pool(sessions)
    sessions[0]._amaterasu_upload_pacer.flood_until = float("inf")
    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")

    assert await sessions[1].invoke(part) is True
    assert sessions[0]._amaterasu_upload_pacer is not sessions[1]._amaterasu_upload_pacer


@pytest.mark.parametrize("ending", ["failure", "cancellation"])
async def test_native_upload_releases_workers_and_budgets_after_abort(monkeypatch, ending):
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "100000")
    monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    started = asyncio.Event()
    release = asyncio.Event()
    client = SimpleNamespace(
        me=SimpleNamespace(is_bot=True, is_premium=False),
        save_file_semaphore=asyncio.Semaphore(1), loop=asyncio.get_running_loop(),
        executor=None, read_ahead_slots=asyncio.Semaphore(16),
        storage=SimpleNamespace(dc_id=AsyncMock(return_value=2)), rnd_id=lambda: 123,
    )

    async def send_part(_query, **_kwargs):
        started.set()
        if ending == "failure":
            raise ValueError("Upload rejected")
        await release.wait()
        return True

    sessions = [SimpleNamespace(client=client, invoke=send_part) for _ in range(8)]

    @asynccontextmanager
    async def media_pool(_dc_id, _size):
        async def ready():
            return _configure_wzgram_media_pool(sessions)

        yield asyncio.create_task(ready())

    client._media_pool = media_pool
    previous_tasks = asyncio.all_tasks()
    task = asyncio.create_task(save_file.SaveFile.save_file(client, BytesIO(b"x" * (12 * 1024 * 1024))))
    await asyncio.wait_for(started.wait(), timeout=1)
    if ending == "cancellation":
        task.cancel()
    try:
        done, _ = await asyncio.wait({task}, timeout=0.2)
        assert task in done, "Aborted upload left native workers waiting for acknowledgements"
        with pytest.raises(asyncio.CancelledError if ending == "cancellation" else ValueError):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    assert client.save_file_semaphore._value == 1
    assert client.read_ahead_slots._value == 16
    assert client._amaterasu_upload_pacer.in_flight._value == 16
    assert not (asyncio.all_tasks() - previous_tasks)


async def test_five_helpers_reuse_bounded_upload_slots_without_retaining_workers(monkeypatch):
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "100000")
    monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    clients = []
    counts = {}
    active = [0] * 5
    peaks = [0] * 5
    file_id = 0

    def next_id():
        nonlocal file_id
        file_id += 1
        return file_id

    for index in range(5):
        client = SimpleNamespace(
            me=SimpleNamespace(is_bot=True, is_premium=False),
            save_file_semaphore=asyncio.Semaphore(2),
            loop=asyncio.get_running_loop(), executor=None,
            read_ahead_slots=asyncio.Semaphore(16),
            storage=SimpleNamespace(dc_id=AsyncMock(return_value=2)), rnd_id=next_id,
        )

        async def send_part(query, index=index, **_kwargs):
            active[index] += 1
            peaks[index] = max(peaks[index], active[index])
            try:
                await asyncio.sleep(0)
                key = (index, query.file_id, query.file_part)
                counts[key] = counts.get(key, 0) + 1
                return True
            finally:
                active[index] -= 1

        sessions = [SimpleNamespace(client=client, invoke=send_part) for _ in range(8)]

        @asynccontextmanager
        async def media_pool(_dc_id, size, sessions=sessions):
            assert size == 8

            async def ready():
                return _configure_wzgram_media_pool(sessions)

            yield asyncio.create_task(ready())

        client._media_pool = media_pool
        clients.append(client)

    previous_tasks = asyncio.all_tasks()
    data = b"x" * (12 * 1024 * 1024)
    for _ in range(3):
        results = await asyncio.wait_for(asyncio.gather(*(
            save_file.SaveFile.save_file(client, BytesIO(data))
            for client in clients for _ in range(2)
        )), timeout=5)
        assert all(result.parts == 24 for result in results)
        assert active == [0] * 5
        assert all(client.save_file_semaphore._value == 2 for client in clients)
        assert all(client.read_ahead_slots._value == 16 for client in clients)
        assert all(client._amaterasu_upload_pacer.in_flight._value == 16 for client in clients)
        assert not (asyncio.all_tasks() - previous_tasks)

    assert len(counts) == 30 * 24
    assert set(counts.values()) == {1}
    assert all(1 < peak <= 16 for peak in peaks)
    assert len({id(client._amaterasu_upload_pacer) for client in clients}) == 5


@pytest.mark.parametrize("is_bot", [True, False])
def test_nonpremium_upload_rate_adapts_upward_and_backs_off_on_flood(monkeypatch, is_bot):
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "32")
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_USER", "32")
    pacer = _WzgramUploadPacer(SimpleNamespace(me=SimpleNamespace(is_bot=is_bot, is_premium=False)))

    for _ in range(100):
        pacer.bucket._last_up = 0
        pacer.bucket.on_success()

    assert 32 < pacer.bucket.rate <= 300
    before_flood = pacer.bucket.rate
    pacer.bucket.on_flood()
    assert pacer.bucket.rate < before_flood

    for _ in range(400):
        pacer.bucket._last_up = pacer.bucket._last_down = 0
        pacer.bucket.on_success()
    assert pacer.bucket.rate == 300


async def test_upload_pacer_fills_native_worker_window_without_serial_admission(monkeypatch):
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "32")
    monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    pacer = _WzgramUploadPacer(SimpleNamespace(me=SimpleNamespace(is_bot=True)))
    release = asyncio.Event()
    active = 0

    async def send_part(_query):
        nonlocal active
        active += 1
        try:
            await release.wait()
            return True
        finally:
            active -= 1

    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")
    tasks = [asyncio.create_task(pacer.invoke(send_part, part)) for _ in range(17)]
    try:
        await asyncio.sleep(0)
        assert active == 16
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.parametrize("pool_setting,expected", [(None, 16), ("2", 4), ("8", 16)])
async def test_bot_upload_requests_match_native_worker_concurrency(monkeypatch, pool_setting, expected):
    monkeypatch.setenv("WZGRAM_UPLOAD_RATE_BOT", "1000")
    if pool_setting is None:
        monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    else:
        monkeypatch.setenv("WZGRAM_UPLOAD_POOL_BOT", pool_setting)
    pacer = _WzgramUploadPacer(SimpleNamespace(me=SimpleNamespace(is_bot=True)))
    pacer.bucket.acquire = AsyncMock()
    release = asyncio.Event()
    active = 0
    peak = 0

    async def send_part(_query):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await release.wait()
            return True
        finally:
            active -= 1

    part = pyrogram.raw.functions.upload.SaveFilePart(file_id=123, file_part=0, bytes=b"part")
    tasks = [asyncio.create_task(pacer.invoke(send_part, part)) for _ in range(24)]
    try:
        await asyncio.sleep(0)
        assert active == expected
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert peak == expected


@pytest.mark.parametrize("pool_setting,expected", [(None, None), ("2", "2"), ("8", "8")])
def test_native_bot_upload_pool_default_preserves_explicit_settings(monkeypatch, pool_setting, expected):
    if pool_setting is None:
        monkeypatch.delenv("WZGRAM_UPLOAD_POOL_BOT", raising=False)
    else:
        monkeypatch.setenv("WZGRAM_UPLOAD_POOL_BOT", pool_setting)
    _configure_wzgram_upload_module(save_file)

    assert os.environ.get("WZGRAM_UPLOAD_POOL_BOT") == expected


async def test_wzgram_upload_queue_unblocks_when_every_consumer_has_failed():
    queue = _WzgramUploadQueue(maxsize=1)

    async def failed_consumer():
        await queue.get()
        raise TimeoutError("Request timed out")

    await queue.put("active part")
    consumer = asyncio.create_task(failed_consumer())
    try:
        await consumer
    except TimeoutError:
        pass
    else:
        raise AssertionError("The simulated media worker should fail")

    queue.put_nowait("orphaned part")
    await asyncio.wait_for(queue.put(None), timeout=1)
    assert queue.get_nowait() is None


async def test_wzgram_upload_queue_preserves_parts_while_a_consumer_is_alive():
    queue = _WzgramUploadQueue(maxsize=1)
    started = asyncio.Event()
    release = asyncio.Event()
    consumed = []

    async def live_consumer():
        consumed.append(await queue.get())
        started.set()
        await release.wait()
        consumed.append(await queue.get())
        consumed.append(await queue.get())

    await queue.put("active part")
    consumer = asyncio.create_task(live_consumer())
    await started.wait()
    await queue.put("queued part")
    shutdown = asyncio.create_task(queue.put(None))
    await asyncio.sleep(0)
    assert not shutdown.done()

    release.set()
    await asyncio.wait_for(shutdown, timeout=1)
    await asyncio.wait_for(consumer, timeout=1)
    assert consumed == ["active part", "queued part", None]
