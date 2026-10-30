import ast
import asyncio
import copy
import io
import re
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import httpx
import pytest
from anyio import CancelScope
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

from web.filetolink_activity import TransferTotals
from web.filetolink_cache import EdgeCache
from web.media_library import MediaLibrary, channel_target
from web.playlist_archive import PlaylistArchives
from web.security import make_route_token, make_signed_token, verify_route_token

ROOT = Path(__file__).resolve().parents[1]


def server_definitions(names, namespace):
    tree = ast.parse((ROOT / "web/wserver.py").read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if getattr(n, "name", None) in names]
    exec(compile(ast.Module(nodes, type_ignores=[]), "wserver.py", "exec"), namespace)
    return namespace


@pytest.mark.asyncio
async def test_edges_are_atomic_bounded_and_versioned(tmp_path):
    cache = EdgeCache(tmp_path, 1024**2, lambda needed: None)
    await cache.put("media1", 20 * 1024**2, 0, 4, b"head")
    assert await cache.get("media1", 20 * 1024**2, 0, 4) == b"head"
    assert await cache.get("media2", 20 * 1024**2, 0, 4) is None
    assert await cache.get("media1", 21 * 1024**2, 0, 4) is None
    await cache.put("media1", 20 * 1024**2, 8 * 1024**2, 4, b"mid!")
    assert await cache.get("media1", 20 * 1024**2, 8 * 1024**2, 4) is None
    await asyncio.gather(*(cache.put("media1", 20 * 1024**2, 0, 4, b"head") for _ in range(8)))
    assert await cache.get("media1", 20 * 1024**2, 0, 4) == b"head"
    assert not list(tmp_path.glob("*.part"))
    cache.path("media1", 20 * 1024**2, 0, 4).write_bytes(b"bad")
    assert await cache.get("media1", 20 * 1024**2, 0, 4) is None
    await cache.put("tail", 10, 8, 4, b"xy")
    assert await cache.get("tail", 10, 8, 4) == b"xy"


@pytest.mark.asyncio
async def test_totals_merge_partial_ranges_exclude_playback_and_survive_uncertain_write():
    tracker = TransferTotals()

    async def source(data):
        yield data
        await asyncio.Event().wait()

    for start, data in [(0, b"ab"), (2, b"cd"), (0, b"ab"), (4, b"ef")]:
        stream = tracker.track(
            source(data), 6 - start, key=("file", "client"), start=start, size=6, kind="single"
        )
        await anext(stream)
        await stream.aclose()
    assert tracker.values["downloads"] == 1
    assert tracker.active == 0

    async def playback():
        yield b"abcdef"

    async for _ in tracker.track(playback(), 6, key="playback"):
        pass
    assert tracker.values["downloads"] == 1
    saved = {}

    async def save(query, update, **kwargs):
        saved.update(copy.deepcopy(update["$set"]))
        if not saved.get("_retried"):
            saved["_retried"] = True
            raise TimeoutError()

    collection = SimpleNamespace(find_one=AsyncMock(return_value={}), update_one=save)
    await tracker.flush(collection)
    assert tracker.state == "unavailable"
    # Retrying writes the same absolute checkpoint, never an increment twice.
    collection.update_one = AsyncMock(
        side_effect=lambda q, u, **k: saved.update(copy.deepcopy(u["$set"]))
    )
    await tracker.flush(collection)
    restored = TransferTotals()
    collection.find_one.return_value = saved
    await restored.flush(collection)
    assert restored.values == tracker.values
    assert restored.coverage == {}
    collection.find_one.side_effect = OSError("offline")
    collection.update_one.reset_mock()
    await TransferTotals().flush(collection)
    collection.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_zip_deduplicates_checks_sources_and_survives_restart(tmp_path):
    calls = []

    async def read(item):
        calls.append(item["name"])
        yield b"ab"
        yield b"cd"

    files = [dict(name="বাংলা/episode.mkv", size=4, unique_id="one")]
    cache = PlaylistArchives(tmp_path, 1024**2, lambda: 0, lambda n: None)
    key = await cache.start("playlist", files, read)
    assert await cache.start("playlist", files, read) == key
    await cache.jobs[key]["task"]
    state = cache.status(key)
    assert state["state"] == "ready"
    payload = cache.path(key).read_bytes()
    with ZipFile(io.BytesIO(payload)) as archive:
        assert archive.testzip() is None
        assert archive.read(archive.namelist()[0]) == b"abcd"
        assert "/" not in archive.namelist()[0]
    restarted = PlaylistArchives(tmp_path, 1024**2, lambda: len(payload), lambda n: None)
    assert restarted.status(key)["version"] == state["version"]
    assert await restarted.start("playlist", files, read) == key
    assert len(calls) == 1

    async def broken(item):
        yield b"a"

    for n in range(4):
        bad = await cache.start(str(n), files, broken)
        await cache.jobs[bad]["task"]
        assert cache.status(bad)["state"] == "missing"
        assert cache.reserved == 0
        assert not cache.path(bad).exists()
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.asyncio
async def test_zip_limits_and_shutdown_release_reservations(tmp_path):
    started = asyncio.Event()

    async def blocked(item):
        started.set()
        await asyncio.Event().wait()
        yield b"1234"

    cache = PlaylistArchives(tmp_path, 1024**2, lambda: 0, lambda n: None)
    files = [dict(name="x", size=4)]
    await cache.start("one", files, blocked)
    await started.wait()
    await cache.start("two", files, blocked)
    with pytest.raises(ValueError, match="Two ZIPs"):
        await cache.start("three", files, blocked)
    await cache.close()
    assert cache.reserved == 0
    assert not list(tmp_path.glob("*.part"))
    with pytest.raises(ValueError, match="budget"):
        await cache.start("huge", [dict(name="x", size=2 * 1024**2)], blocked)


@pytest.mark.asyncio
async def test_zip_stalled_source_fails_without_holding_capacity(tmp_path):
    async def stalled(item):
        yield b"a"
        await asyncio.Event().wait()

    cache = PlaylistArchives(tmp_path, 1024**2, lambda: 0, lambda n: None)
    cache.READ_TIMEOUT = 0.01
    key = await cache.start("stalled", [dict(name="x", size=4)], stalled)
    await asyncio.wait_for(cache.jobs[key]["task"], 1)
    assert cache.status(key)["state"] == "missing"
    assert cache.reserved == 0
    assert not list(tmp_path.glob("*.part"))


def test_shared_cache_budget_keeps_unexpired_archives_and_counts_reservations(tmp_path):
    (tmp_path / "archives").mkdir()
    archive = tmp_path / "archives" / "valid.zip"
    archive.write_bytes(b"12345678")
    media = tmp_path / "cached.mp4"
    media.write_bytes(b"12345678")
    ns = server_definitions(
        {"_prune_filetolink_cache"},
        dict(
            FILETOLINK_CACHE_TOTAL_MAX_BYTES=16,
            FILETOLINK_CACHE_DIR=str(tmp_path),
            Path=Path,
            suppress=__import__("contextlib").suppress,
            playlist_archives=SimpleNamespace(reserved=4),
            _filetolink_cache_reservations={},
        ),
    )
    with pytest.raises(OSError, match="reserved"):
        ns["_prune_filetolink_cache"](10)
    assert archive.read_bytes() == b"12345678"
    assert not media.exists()
    ns["playlist_archives"].reserved = 16
    with pytest.raises(OSError, match="reserved"):
        ns["_prune_filetolink_cache"](1)


@pytest.mark.asyncio
async def test_scan_checkpoints_resume_without_duplicates_and_keeps_channels_separate():
    files = {}
    state = {}

    async def update(query, change, **kwargs):
        files[(query["channel_id"], query["message_id"])] = change["$set"]

    async def checkpoint(query, change, **kwargs):
        state.update(last=change["$max"]["last"])

    stop = asyncio.Event()
    messages = [SimpleNamespace(id=n, empty=False) for n in range(1, 4)]
    client = SimpleNamespace(
        get_messages=AsyncMock(
            side_effect=lambda c, message_ids: [m for m in messages if m.id in message_ids]
        )
    )
    scans = SimpleNamespace(
        find_one=AsyncMock(side_effect=lambda q: dict(state)), update_one=checkpoint
    )
    library = MediaLibrary(SimpleNamespace(update_one=update), scans)

    def describe(message):
        if message.id == 2:
            stop.set()
        return dict(name=f"file{message.id}", size=4)

    last, _ = await library.scan(client, -1001, 3, stop, describe, AsyncMock())
    assert last == 2 and state["last"] == 2
    stop.clear()
    await library.scan(client, -1001, 3, stop, lambda m: dict(name="last", size=4), AsyncMock())
    assert state["last"] == 3 and len(files) == 3
    assert client.get_messages.call_args.kwargs["message_ids"] == [3]
    assert all(key[0] == -1001 for key in files)
    assert channel_target("https://t.me/c/123456/500") == (-100123456, 500)
    with pytest.raises(ValueError):
        channel_target("https://evil.test/channel/500")


@pytest.mark.asyncio
async def test_library_command_rejects_non_admin_before_any_scan():
    tree = ast.parse((ROOT / "bot/modules/filetolink_library.py").read_text())
    command = next(n for n in tree.body if getattr(n, "name", None) == "library_command")
    sent = AsyncMock()
    namespace = dict(
        _scan=None,
        ChatType=SimpleNamespace(PRIVATE="private"),
        CustomFilters=SimpleNamespace(sudo=AsyncMock(return_value=False)),
        send_message=sent,
    )
    exec(compile(ast.Module([command], type_ignores=[]), "library_command", "exec"), namespace)
    await namespace["library_command"](
        None, SimpleNamespace(chat=SimpleNamespace(type="private")), ["/link", "index"]
    )
    assert "owner and sudo" in sent.call_args.args[1]


@pytest.mark.asyncio
async def test_real_zip_routes_head_ranges_restart_expiry_and_access(tmp_path, monkeypatch):
    import web
    from web import filetolink_routes as routes

    tracker = TransferTotals()
    ns = server_definitions(
        {
            "_parse_range_header",
            "_iter_cached_range",
            "_FileToLinkStreamingResponse",
            "_transfer_accounting",
            "_no_store",
        },
        dict(
            HTTPException=HTTPException,
            RANGE_REGEX=re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$"),
            CHUNK_SIZE=1024**2,
            StreamingResponse=StreamingResponse,
            Response=Response,
            Request=object,
            CancelScope=CancelScope,
            Path=Path,
            sha256=__import__("hashlib").sha256,
            filetolink_totals=tracker,
        ),
    )
    cache = PlaylistArchives(
        tmp_path,
        1024**2,
        lambda: sum(p.stat().st_size for p in tmp_path.glob("*.zip")),
        lambda n: None,
    )
    token = "playlist123"
    media_token = make_route_token("secret", "stream", -1001, 1)
    playlist = dict(name="বাংলা episodes", items=[dict(token=media_token, name="one.bin")])
    db = ModuleType("bot.helper.ext_utils.db_handler")
    db.database = SimpleNamespace(
        get_filetolink_playlist=AsyncMock(side_effect=lambda t: playlist if t == token else None)
    )
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.db_handler", db)
    server = SimpleNamespace(
        **ns,
        JSONResponse=JSONResponse,
        playlist_archives=cache,
        _web_secret=lambda: "secret",
        _decode_stream_route_token=lambda t: verify_route_token(t, "secret", "stream"),
        get_message_with_stream_client=AsyncMock(return_value=(1, object(), object())),
        get_media=lambda m: SimpleNamespace(file_unique_id="uid", file_size=4),
        _release_stream_load=lambda i: None,
    )
    monkeypatch.setitem(sys.modules, "web.wserver", server)
    monkeypatch.setattr(web, "wserver", server, raising=False)

    async def read(item):
        yield b"abcd"

    monkeypatch.setattr(routes, "_archive_source", read)
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        assert (await client.post(f"/playlist/{token}/zip")).status_code == 403
        response = await client.post(
            f"/playlist/{token}/zip", headers={"X-Amaterasu-Action": "archive"}
        )
        assert response.status_code == 200, response.text
        urls = response.json()
        key = urls["download_url"].split("/")[-1]
        await cache.jobs[key]["task"]
        assert (await client.get(urls["status_url"])).json()["state"] == "ready"
        head = await client.head(urls["download_url"])
        assert head.status_code == 200 and int(head.headers["content-length"]) > 4
        assert tracker.values["bytes"] == 0
        full = await client.get(urls["download_url"])
        data = full.content
        assert tracker.values["zip_downloads"] == 1
        with ZipFile(io.BytesIO(data)) as archive:
            assert archive.read("001-one.bin") == b"abcd"
        cache2 = PlaylistArchives(tmp_path, 1024**2, lambda: len(data), lambda n: None)
        server.playlist_archives = cache2
        for value, expected in [
            ("bytes=2-8", data[2:9]),
            ("bytes=-22", data[-22:]),
            ("bytes=17-", data[17:]),
        ]:
            ranged = await client.get(
                urls["download_url"], headers={"Range": value, "If-Range": head.headers["etag"]}
            )
            assert ranged.status_code == 206 and ranged.content == expected
        mismatched = await client.get(
            urls["download_url"], headers={"Range": "bytes=1-2", "If-Range": '"old"'}
        )
        assert mismatched.status_code == 200 and mismatched.content == data
        server._web_secret = lambda: "rotated-secret"
        assert (await client.get(urls["download_url"])).status_code == 403
        server._web_secret = lambda: "secret"
        assert (
            await client.get(urls["download_url"], headers={"Range": "bytes=0-1,3-4"})
        ).status_code == 400
        assert (
            await client.get(urls["download_url"].replace(token, "another123"))
        ).status_code == 404
        meta = cache.path(key).with_suffix(".json")
        metadata = __import__("json").loads(meta.read_text())
        metadata["expires"] = time.time() - 1
        meta.write_text(__import__("json").dumps(metadata))
        assert (await client.get(urls["download_url"])).status_code == 410
    await cache.close()


def test_library_capabilities_are_separate_and_expire():
    from starlette.requests import Request

    from web.filetolink_routes import library_access

    token = make_signed_token("secret", "media-library", 42, ttl=3600)

    def request(token):
        return Request(
            dict(type="http", query_string=f"user_id=42&token={token}".encode(), headers=[])
        )

    assert library_access(request(token), "secret") == 42
    for wrong in [
        token + "x",
        make_signed_token("secret", "encode-profile", 42, ttl=3600),
        make_signed_token("secret", "media-library", 42, ttl=-5),
    ]:
        with pytest.raises(HTTPException):
            library_access(request(wrong), "secret")
