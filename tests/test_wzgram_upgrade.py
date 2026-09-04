import ast
import asyncio
import gc
import warnings
from importlib import import_module
from importlib.metadata import version as package_version
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pyrogram
import warpcrypto
from pyrogram import Client
from pyrogram.crypto import aes
from pyrogram.dispatcher import Dispatcher
from pyrogram.handlers import (
    ConnectHandler,
    DisconnectHandler,
    StartHandler,
    StopHandler,
)
from pyrogram.methods.advanced import save_file

from bot.core.tg_client import (
    WZGRAM_MEDIA_RESET_COOLDOWN,
    WZGRAM_MEDIA_RESTART_ATTEMPTS,
    WZGRAM_UPLOAD_PART_ATTEMPTS,
    WzgramClient,
    _configure_wzgram_media_pool,
    _configure_wzgram_upload_module,
    _WzgramAsyncioProxy,
    _WzgramUploadQueue,
    is_wzgram_media_session_failure,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WZGRAM_VERSION = "3.1.0"
EXPECTED_WARPCRYPTO_VERSION = "2.0.7"


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
    assert manager._conn.options["serverSelectionTimeoutMS"] == 5000
    assert manager._conn.options["connectTimeoutMS"] == 5000


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
