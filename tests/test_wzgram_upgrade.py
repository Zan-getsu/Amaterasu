import asyncio
import gc
import warnings
from pathlib import Path
from types import SimpleNamespace

import pyrogram
import warpcrypto
from pyrogram import Client
from pyrogram.crypto import aes
from pyrogram.dispatcher import Dispatcher
from pyrogram.methods.advanced import save_file

from bot.core.tg_client import (
    WZGRAM_MEDIA_RESET_COOLDOWN,
    WZGRAM_MEDIA_RESTART_ATTEMPTS,
    WZGRAM_UPLOAD_PART_ATTEMPTS,
    WzgramClient,
    _configure_wzgram_media_pool,
    _WzgramAsyncioProxy,
    _WzgramUploadQueue,
    is_wzgram_media_session_failure,
)

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_WZGRAM_VERSION = "3.0.33"


def test_wzgram_runtime_and_accelerator_are_current():
    assert pyrogram.__version__ == EXPECTED_WZGRAM_VERSION
    assert getattr(aes, "warpcrypto", None) is warpcrypto
    assert hasattr(Client, "_get_media_session_pool")
    assert save_file.MAX_RETRIES == WZGRAM_UPLOAD_PART_ATTEMPTS
    assert isinstance(save_file.asyncio, _WzgramAsyncioProxy)


def test_wzgram_version_is_consistent_across_deployment_files():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    cli_requirements = (
        ROOT / "gen_scripts" / "config" / "requirements-cli.txt"
    ).read_text(encoding="utf-8")
    session_generator = (
        ROOT / "gen_scripts" / "gen_pyro_session" / "script.py"
    ).read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in requirements
    assert "warpcrypto>=2.0.6" in requirements
    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in cli_requirements
    assert "warpcrypto>=2.0.6" in cli_requirements
    assert f"wzgram[fast]=={EXPECTED_WZGRAM_VERSION}" in session_generator
    assert f"pyrogram.__version__ == '{EXPECTED_WZGRAM_VERSION}'" in dockerfile
    assert f"WZGram {EXPECTED_WZGRAM_VERSION} (`pyrogram` API)" in readme


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
    finally:
        client.loop.close()


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
