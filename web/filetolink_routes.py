"""Private library and immutable playlist ZIP endpoints."""

import asyncio
import re
from contextlib import aclosing
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Request

from web.media_library import MediaLibrary
from web.security import make_route_token, verify_route_token, verify_signed_token

router = APIRouter()
_prepare_slots = asyncio.Semaphore(2)


def library_access(request, secret):
    try:
        user = int(request.query_params.get("user_id", ""))
    except ValueError as exc:
        raise HTTPException(403, "Open a fresh private link with /link library.") from exc
    if not verify_signed_token(request.query_params.get("token"), secret, "media-library", user):
        raise HTTPException(403, "This library link expired. Use /link library in the bot.")
    return user


@router.get("/library")
async def media_library(request: Request):
    from bot.helper.ext_utils.db_handler import database
    from web import wserver as server

    library_access(request, server._web_secret())
    try:
        library = MediaLibrary(
            database.filetolink_collection("library"), database.filetolink_collection("scans")
        )
        query = request.query_params.get("q", "").strip()[:100]
        try:
            page = max(1, min(100000, int(request.query_params.get("page", "1"))))
        except ValueError:
            page = 1
        data = await library.page(query, page)
    except Exception as exc:
        raise HTTPException(
            503, "The media library database is unavailable. Try again shortly."
        ) from exc
    for item in data["items"]:
        token = make_route_token(
            server._web_secret(), "stream", item["channel_id"], item["message_id"]
        )
        item.update(
            watch_url=f"/watch/{token}",
            download_url=f"/dl/{token}",
            size_label=server._readable_bytes(item["size"]),
        )
    auth = dict(
        user_id=request.query_params["user_id"], token=request.query_params["token"], q=query
    )
    response = server.templates.TemplateResponse(
        request,
        "library.html",
        {
            **data,
            "query": query,
            "user_id": auth["user_id"],
            "token": auth["token"],
            "previous": "/library?" + urlencode({**auth, "page": max(1, data["page"] - 1)}),
            "next": "/library?" + urlencode({**auth, "page": data["page"] + 1}),
            "totals": server.filetolink_totals.snapshot(),
        },
    )
    return server._no_store(response)


async def _playlist(token):
    from bot.helper.ext_utils.db_handler import database
    from web import wserver as server

    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        raise HTTPException(404, "Playlist does not exist")
    playlist = await database.get_filetolink_playlist(token)
    if not playlist:
        raise HTTPException(404, "Playlist does not exist")
    if not playlist.get("items") or any(
        verify_route_token(item.get("token"), server._web_secret(), "stream") is None
        for item in playlist["items"]
    ):
        raise HTTPException(
            403, "Playlist access is no longer valid. Generate a new playlist in the bot."
        )
    return playlist


async def _archive_source(item):
    from web import wserver as server

    client_id, client, message = await server.get_message_with_stream_client(
        item["chat_id"], item["message_id"]
    )
    try:
        media = server.get_media(message)
        if (
            getattr(media, "file_unique_id", "") != item["unique_id"]
            or getattr(media, "file_size", 0) != item["size"]
        ):
            raise OSError("A selected Telegram file changed. Prepare the playlist again.")
        try:
            from bot.helper.telegram_helper.tg_stream import AdaptiveTelegramStream, build_profile

            engine = (
                await AdaptiveTelegramStream(
                    chat_id=item["chat_id"],
                    message_id=item["message_id"],
                    clients={client_id: client},
                    primary_client_id=client_id,
                    primary_message=message,
                    profile=build_profile(
                        "bulk",
                        concurrency=server._transfer_prefetch_depth(client_id),
                        prefetch=server.FILETOLINK_PREFETCH_CHUNKS,
                    ),
                    on_failure=server._record_stream_failure,
                    edge_cache=server.edge_cache,
                ).open()
                if server.FILETOLINK_ADAPTIVE_STREAMING
                else None
            )
        except Exception:
            engine = None
        source = (
            engine.iter_range(0, item["size"] - 1)
            if engine
            else server._iter_telegram_range(
                client_id, client, message, 0, item["size"] - 1, item["size"]
            )
        )
        async with aclosing(source):
            async for chunk in source:
                yield chunk
    finally:
        server._release_stream_load(client_id)


@router.post("/playlist/{token}/zip")
async def prepare_playlist_zip(token: str, request: Request):
    from web import wserver as server

    if request.headers.get("x-amaterasu-action") != "archive":
        raise HTTPException(403, "Start ZIP preparation from the playlist page.")
    playlist = await _playlist(token)
    try:
        async with asyncio.timeout(25), _prepare_slots:
            files = []
            for item in (playlist.get("items") or [])[:100]:
                chat, ident = server._decode_stream_route_token(item.get("token", ""))
                client_id, _, message = await server.get_message_with_stream_client(chat, ident)
                try:
                    media = server.get_media(message)
                    unique_id = getattr(media, "file_unique_id", "")
                    if not unique_id:
                        raise ValueError(
                            "A playlist file is unavailable. Use its individual download to check it."
                        )
                    files.append(
                        dict(
                            chat_id=chat,
                            message_id=ident,
                            unique_id=unique_id,
                            size=int(getattr(media, "file_size", 0)),
                            name=str(item.get("name") or "Media"),
                        )
                    )
                finally:
                    server._release_stream_load(client_id)
            key = await server.playlist_archives.start(token, files, _archive_source)
    except TimeoutError as exc:
        raise HTTPException(503, "Checking the playlist timed out. Try again shortly.") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(413, str(exc)) from exc
    return server._no_store(
        server.JSONResponse(
            dict(
                status_url=f"/playlist/{token}/zip/{key}/status",
                download_url=f"/playlist/{token}/zip/{key}",
            )
        )
    )


@router.get("/playlist/{token}/zip/{key}/status")
async def playlist_zip_status(token: str, key: str):
    from web import wserver as server

    await _playlist(token)
    try:
        state = server.playlist_archives.status(key)
    except ValueError as exc:
        raise HTTPException(404, "ZIP does not exist") from exc
    if state.get("playlist") != token:
        raise HTTPException(
            410, "The ZIP expired or preparation failed. Prepare it again from the playlist."
        )
    return server._no_store(server.JSONResponse(state))


@router.api_route("/playlist/{token}/zip/{key}", methods=["GET", "HEAD"])
async def download_playlist_zip(token: str, key: str, request: Request):
    from web import wserver as server

    playlist = await _playlist(token)
    try:
        state = server.playlist_archives.status(key)
    except ValueError as exc:
        raise HTTPException(404, "ZIP does not exist") from exc
    if state.get("playlist") != token or state["state"] != "ready":
        raise HTTPException(
            410, "This ZIP is not ready or has expired. Prepare it again from the playlist."
        )
    etag = f'"{state["version"]}"'
    range_header = request.headers.get("range")
    if request.headers.get("if-range") not in (None, etag):
        range_header = None
    start, end, ranged = server._parse_range_header(range_header, state["bytes"])
    length = end - start + 1
    name = (
        re.sub(r'[\x00-\x1f\x7f/\\:<>"|?*]', "_", str(playlist.get("name") or "Playlist"))[
            :120
        ].rstrip(" .")
        or "Playlist"
    )
    headers = {
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name + ".zip", safe=""),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, no-store",
    }
    if ranged:
        headers["Content-Range"] = f"bytes {start}-{end}/{state['bytes']}"
    if request.method == "HEAD":
        return server.Response(
            status_code=206 if ranged else 200, headers=headers, media_type="application/zip"
        )
    tracking = server._transfer_accounting(
        request, state["version"], "zip", key, start, length, state["bytes"], "attachment"
    )
    tracking["kind"] = "zip"
    source = server._iter_cached_range(server.playlist_archives.path(key), start, length)
    return server._FileToLinkStreamingResponse(
        source,
        status_code=206 if ranged else 200,
        media_type="application/zip",
        headers=headers,
        transfer=tracking,
    )
