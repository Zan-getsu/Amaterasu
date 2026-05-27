from asyncio import sleep
import re
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from logging import INFO, WARNING, FileHandler, StreamHandler, basicConfig, getLogger

from aioaria2 import Aria2HttpClient
from aiohttp.client_exceptions import ClientError
from aioqbt.client import create_client
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sabnzbdapi import SabnzbdClient
from aioaria2 import Aria2HttpClient
from aioqbt.client import create_client
from aiohttp.client_exceptions import ClientError
from aioqbt.exc import AQError

from web.nodes import extract_file_ids, make_tree
from aiohttp import ClientSession

getLogger("httpx").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)

aria2 = None
qbittorrent = None
sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key="admin",
    port="8070",
)
SERVICES = {
    "nzb": {"url": "http://localhost:8070/"},
    "qbit": {"url": "http://localhost:8090", "password": "admin"},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global aria2, qbittorrent
    aria2 = Aria2HttpClient("http://localhost:6800/jsonrpc")
    qbittorrent = await create_client("http://localhost:8090/api/v2/")
    yield
    await aria2.close()
    await qbittorrent.close()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="web/templates")


basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",  #  [%(filename)s:%(lineno)d]
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)


async def re_verify(paused, resumed, hash_id):
    k = 0
    while True:
        res = await qbittorrent.torrents.files(hash_id)
        verify = True
        for i in res:
            if i.index in paused and i.priority != 0:
                verify = False
                break
            if i.index in resumed and i.priority == 0:
                verify = False
                break
        if verify:
            break
        LOGGER.info("Reverification Failed! Correcting stuff...")
        await sleep(0.5)
        if paused:
            try:
                await qbittorrent.torrents.file_prio(
                    hash=hash_id, id=paused, priority=0
                )
            except (ClientError, TimeoutError, Exception, AQError) as e:
                LOGGER.error(f"{e} Errored in reverification paused!")
        if resumed:
            try:
                await qbittorrent.torrents.file_prio(
                    hash=hash_id, id=resumed, priority=1
                )
            except (ClientError, TimeoutError, Exception, AQError) as e:
                LOGGER.error(f"{e} Errored in reverification resumed!")
        k += 1
        if k > 5:
            return False
    LOGGER.info(f"Verified! Hash: {hash_id}")
    return True


@app.get("/app/files", response_class=HTMLResponse)
async def files(request: Request):
    return templates.TemplateResponse(request, "page.html")


@app.api_route(
    "/app/files/torrent", methods=["GET", "POST"], response_class=HTMLResponse
)
async def handle_torrent(request: Request):
    params = request.query_params

    if not (gid := params.get("gid")):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "GID is missing",
                "message": "GID not specified",
            }
        )

    if not (pin := params.get("pin")):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Pin is missing",
                "message": "PIN not specified",
            }
        )

    code = "".join([nbr for nbr in gid if nbr.isdigit()][:4])
    if code != pin:
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Invalid pin",
                "message": "The PIN you entered is incorrect",
            }
        )

    if request.method == "POST":
        if not (mode := params.get("mode")):
            return JSONResponse(
                {
                    "files": [],
                    "engine": "",
                    "error": "Mode is not specified",
                    "message": "Mode is not specified",
                }
            )
        data = await request.json()
        if mode == "rename":
            if len(gid) > 20:
                await handle_rename(gid, data)
                content = {
                    "files": [],
                    "engine": "",
                    "error": "",
                    "message": "Rename successfully.",
                }
            else:
                content = {
                    "files": [],
                    "engine": "",
                    "error": "Rename failed.",
                    "message": "Cannot rename aria2c torrent file",
                }
        else:
            selected_files, unselected_files = extract_file_ids(data)
            if gid.startswith("SABnzbd_nzo"):
                await set_sabnzbd(gid, unselected_files)
            elif len(gid) > 20:
                await set_qbittorrent(gid, selected_files, unselected_files)
            else:
                selected_files = ",".join(selected_files)
                await set_aria2(gid, selected_files)
            content = {
                "files": [],
                "engine": "",
                "error": "",
                "message": "Your selection has been submitted successfully.",
            }
    else:
        try:
            if gid.startswith("SABnzbd_nzo"):
                res = await sabnzbd_client.get_files(gid)
                content = make_tree(res, "sabnzbd")
            elif len(gid) > 20:
                res = await qbittorrent.torrents.files(gid)
                content = make_tree(res, "qbittorrent")
            else:
                res = await aria2.getFiles(gid)
                op = await aria2.getOption(gid)
                fpath = f"{op['dir']}/"
                content = make_tree(res, "aria2", fpath)
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(str(e))
            content = {
                "files": [],
                "engine": "",
                "error": "Error getting files",
                "message": str(e),
            }
    return JSONResponse(content)


async def handle_rename(gid, data):
    try:
        _type = data["type"]
        del data["type"]
        if _type == "file":
            await qbittorrent.torrents.rename_file(hash=gid, **data)
        else:
            await qbittorrent.torrents.rename_folder(hash=gid, **data)
    except (ClientError, TimeoutError, Exception, AQError) as e:
        LOGGER.error(f"{e} Errored in renaming")


async def set_sabnzbd(gid, unselected_files):
    await sabnzbd_client.remove_file(gid, unselected_files)
    LOGGER.info(f"Verified! nzo_id: {gid}")


async def set_qbittorrent(gid, selected_files, unselected_files):
    if unselected_files:
        try:
            await qbittorrent.torrents.file_prio(
                hash=gid, id=unselected_files, priority=0
            )
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(f"{e} Errored in paused")
    if selected_files:
        try:
            await qbittorrent.torrents.file_prio(
                hash=gid, id=selected_files, priority=1
            )
        except (ClientError, TimeoutError, Exception, AQError) as e:
            LOGGER.error(f"{e} Errored in resumed")
    await sleep(0.5)
    if not await re_verify(unselected_files, selected_files, gid):
        LOGGER.error(f"Verification Failed! Hash: {gid}")


async def set_aria2(gid, selected_files):
    res = await aria2.changeOption(gid, {"select-file": selected_files})
    if res == "OK":
        LOGGER.info(f"Verified! Gid: {gid}")
    else:
        LOGGER.info(f"Verification Failed! Report! Gid: {gid}")


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request):
    return templates.TemplateResponse(request, "landing.html")


def rewrite_location(location: str, proxy_prefix: str) -> str:
    parsed = urlparse(location)
    if not parsed.netloc:
        return proxy_prefix + location
    if parsed.hostname in ["localhost", "127.0.0.1"]:
        return proxy_prefix + parsed.path
    return location


async def proxy_fetch(
    method: str, url: str, headers: dict, params: dict, body: bytes, proxy_prefix: str
):
    async with ClientSession(auto_decompress=True) as session:
        async with session.request(
            method,
            url,
            headers=headers,
            params=params,
            data=body,
            allow_redirects=False,
        ) as upstream:
            if upstream.status in (301, 302, 303, 307, 308) and upstream.headers.get(
                "Location"
            ):
                loc = upstream.headers["Location"]
                new_loc = rewrite_location(loc, proxy_prefix)
                return HTMLResponse(
                    status_code=upstream.status, headers={"Location": new_loc}
                )
            content = await upstream.read()
            media_type = upstream.headers.get("Content-Type", "text/html")
            resp_headers = {
                k: v
                for k, v in upstream.headers.items()
                if k.lower() not in ["content-length", "content-encoding"]
            }
            return HTMLResponse(
                content=content,
                status_code=upstream.status,
                headers=resp_headers,
                media_type=media_type,
            )


async def protected_proxy(
    service: str, path: str, request: Request, password: str = None
):
    service_info = SERVICES.get(service)
    if not service_info:
        raise HTTPException(status_code=404, detail="Service not found")
    if "password" in service_info and password != service_info["password"]:
        raise HTTPException(status_code=403, detail="Unauthorized access")
    base = service_info["url"]
    url = f"{base}/{path}" if path else base
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    return await proxy_fetch(
        request.method, url, headers, dict(request.query_params), body, f"/{service}"
    )


@app.api_route("/nzb/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def sabnzbd_proxy(path: str = "", request: Request = None):
    return await protected_proxy("nzb", path, request)


@app.api_route("/qbit/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def qbittorrent_proxy(path: str = "", request: Request = None):
    password = request.query_params.get("pass") or request.cookies.get("qbit_pass")
    if not password:
        raise HTTPException(status_code=403, detail="Missing password")
    response = await protected_proxy("qbit", path, request, password)
    if "pass" in request.query_params:
        response.set_cookie("qbit_pass", password)
    return response


# FileToLink dynamic load-balanced streaming endpoints
CHUNK_SIZE = 1024 * 1024
RANGE_REGEX = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")

def select_optimal_client() -> tuple[int, any]:
    from bot.core.tg_client import TgClient
    if not TgClient.stream_clients:
        return 0, TgClient.bot
    
    available_clients = [
        (cid, load) for cid, load in TgClient.stream_loads.items()
        if load < 8
    ]
    if available_clients:
        client_id = min(available_clients, key=lambda x: x[1])[0]
    else:
        client_id = min(TgClient.stream_loads, key=TgClient.stream_loads.get)
    return client_id, TgClient.stream_clients[client_id]

def get_media(message):
    if not message:
        return None
    for media_type in ["document", "video", "audio", "photo", "voice", "animation", "video_note", "sticker"]:
        if media := getattr(message, media_type, None):
            return media
    return None

async def get_message(client, chat_id: int, message_id: int) -> any:
    import asyncio
    from pyrogram.errors import FloodWait
    while True:
        try:
            message = await client.get_messages(chat_id, message_id)
            break
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception as e:
            from bot import LOGGER
            LOGGER.error(f"Failed to fetch message {message_id} from {chat_id}: {e}")
            raise HTTPException(status_code=404, detail="Media message not found") from e
    if not message or not get_media(message):
        raise HTTPException(status_code=404, detail="Message does not contain media")
    return message

@app.api_route("/watch/{chat_id}/{message_id}", methods=["GET"])
@app.api_route("/watch/{chat_id}/{message_id}/{filename}", methods=["GET"])
async def watch_media(chat_id: str, message_id: int, request: Request, filename: str = None):
    try:
        chat_id = int(chat_id)
    except ValueError:
        pass
    from bot.core.tg_client import TgClient

    client_id, client = select_optimal_client()
    if client_id not in TgClient.stream_loads:
        TgClient.stream_loads[client_id] = 0
    TgClient.stream_loads[client_id] += 1
    
    try:
        message = await get_message(client, chat_id, message_id)
        media = get_media(message)
        
        provided_hash = request.query_params.get("hash")
        if not provided_hash:
            raise HTTPException(status_code=403, detail="Missing secure hash")
        unique_id = getattr(media, "file_unique_id", "")
        secure_hash = unique_id[:6] if len(unique_id) >= 6 else unique_id
        if provided_hash != secure_hash:
            raise HTTPException(status_code=403, detail="Invalid secure hash")
            
        if not filename:
            filename = getattr(media, "file_name", None) or f"Stream_{message_id}.bin"
            
        file_size = getattr(media, "file_size", 0) or 0
        from bot.helper.ext_utils.status_utils import get_readable_file_size
        readable_size = get_readable_file_size(file_size)
            
        from urllib.parse import quote
        stream_url = f"/stream/{chat_id}/{message_id}/{quote(filename)}?hash={secure_hash}"
        
        return templates.TemplateResponse(request, "player.html", {
            "file_name": filename,
            "file_url": stream_url,
            "file_size": readable_size
        })
    finally:
        TgClient.stream_loads[client_id] -= 1

@app.api_route("/stream/{chat_id}/{message_id}", methods=["GET", "HEAD"])
@app.api_route("/stream/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
async def stream_media(chat_id: str, message_id: int, request: Request, filename: str = None):
    try:
        chat_id = int(chat_id)
    except ValueError:
        pass
    from bot.core.tg_client import TgClient
    from fastapi.responses import StreamingResponse, Response

    client_id, client = select_optimal_client()
    if client_id not in TgClient.stream_loads:
        TgClient.stream_loads[client_id] = 0
    TgClient.stream_loads[client_id] += 1
    
    try:
        message = await get_message(client, chat_id, message_id)
        media = get_media(message)
        
        provided_hash = request.query_params.get("hash")
        if not provided_hash:
            raise HTTPException(status_code=403, detail="Missing secure hash")
        unique_id = getattr(media, "file_unique_id", "")
        secure_hash = unique_id[:6] if len(unique_id) >= 6 else unique_id
        if provided_hash != secure_hash:
            raise HTTPException(status_code=403, detail="Invalid secure hash")
            
        file_size = getattr(media, "file_size", 0) or 0
        mime_type = getattr(media, "mime_type", None)
        if not mime_type:
            media_type = type(media).__name__.lower()
            mime_map = {
                "photo": "image/jpeg",
                "voice": "audio/ogg",
                "video_note": "video/mp4",
                "sticker": "image/webp",
            }
            mime_type = mime_map.get(media_type, "application/octet-stream")
        
        if not filename:
            filename = getattr(media, "file_name", None) or f"Stream_{message_id}.bin"
        
        range_header = request.headers.get("Range")
        start, end = 0, file_size - 1
        
        if range_header:
            match = RANGE_REGEX.match(range_header)
            if match:
                start_str = match.group("start")
                end_str = match.group("end")
                start = int(start_str) if start_str else 0
                end = int(end_str) if end_str else file_size - 1
                
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Requested range not satisfiable")
            
        content_length = end - start + 1
        
        disposition = request.query_params.get("disposition", "inline")
        if disposition not in ["inline", "attachment"]:
            disposition = "inline"

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": mime_type,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type, *",
            "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition",
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        }
        
        if range_header:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            
        if request.method == "HEAD":
            headers["Content-Length"] = str(content_length)
            TgClient.stream_loads[client_id] -= 1
            return Response(status_code=206 if range_header else 200, headers=headers)
            
        async def stream_generator():
            try:
                bytes_sent = 0
                bytes_to_skip = start % CHUNK_SIZE
                chunk_offset = start // CHUNK_SIZE
                chunk_limit = ((content_length + CHUNK_SIZE - 1) // CHUNK_SIZE) + 1
                
                import asyncio
                from pyrogram.errors import FloodWait
                
                started_stream = False
                media_generator = None
                while True:
                    try:
                        media_generator = client.stream_media(
                            message, offset=chunk_offset, limit=chunk_limit
                        )
                        break
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except Exception as e:
                        if started_stream:
                            raise
                        raise HTTPException(status_code=404, detail="Failed to stream media") from e
                
                async for chunk in media_generator:
                    started_stream = True
                    if bytes_to_skip > 0:
                        if len(chunk) <= bytes_to_skip:
                            bytes_to_skip -= len(chunk)
                            continue
                        chunk = chunk[bytes_to_skip:]
                        bytes_to_skip = 0
                        
                    remaining = content_length - bytes_sent
                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]
                        
                    if chunk:
                        yield chunk
                        bytes_sent += len(chunk)
                        
                    if bytes_sent >= content_length:
                        break
            finally:
                TgClient.stream_loads[client_id] -= 1
                
        headers["Content-Length"] = str(content_length)
        return StreamingResponse(
            stream_generator(),
            status_code=206 if range_header else 200,
            headers=headers
        )
        
    except Exception as e:
        TgClient.stream_loads[client_id] -= 1
        raise e


@app.exception_handler(Exception)
async def page_not_found(_, exc):
    return HTMLResponse(
        f"<h1>404: Task not found! Mostly wrong input. <br><br>Error: {exc}</h1>",
        status_code=404,
    )
