from asyncio import sleep
import re
from importlib import import_module
from os import environ
from re import compile as re_compile
from urllib.parse import quote, urlparse
from contextlib import asynccontextmanager, suppress
from logging import INFO, WARNING, FileHandler, StreamHandler, basicConfig, getLogger

from aioaria2 import Aria2HttpClient
from aiohttp.client_exceptions import ClientError
from aioqbt.client import create_client
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sabnzbdapi import SabnzbdClient
from aioqbt.exc import AQError

from web.nodes import extract_file_ids, make_tree
from web.security import make_route_token, verify_route_token, verify_short_token, verify_signed_token
from aiohttp import ClientSession

getLogger("httpx").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)
getLogger("uvicorn").setLevel(WARNING)
getLogger("uvicorn.access").setLevel(WARNING)

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)

_SAFE_PATH = re_compile(r"^[A-Za-z0-9_./-]+$")
_SAFE_GID = re_compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_PIN = re_compile(r"^\d{4}$")
_SAFE_PROFILE_ID = re_compile(r"^[A-Za-z0-9_-]{1,64}$")
_PIN_SALT = b"wzmlx_v3_pin_salt"
_PIN_LEN = 4
_PIN_RATE_LIMIT = 5
_PIN_RATE_WINDOW = 60
_pin_attempts: dict = {}

def _load_config():
    try:
        cfg = import_module("config")
    except ModuleNotFoundError:
        cfg = None
    bot_token = environ.get("BOT_TOKEN", "") or (getattr(cfg, "BOT_TOKEN", "") if cfg else "")
    access_pwd = environ.get("WEB_ACCESS_PASSWORD", "") or (
        getattr(cfg, "WEB_ACCESS_PASSWORD", "") if cfg else ""
    )
    return bot_token, access_pwd


def _resolve_bot_id(token):
    if not token or not isinstance(token, str):
        return "0"
    token = token.strip()
    if not token:
        return "0"
    return (token.split(":", 1)[0] or "0").strip()


_BOT_TOKEN, _ACCESS_PASSWORD = _load_config()
_BOT_ID = _resolve_bot_id(_BOT_TOKEN)


def _service_pwd(service):
    from bot.helper.ext_utils.bot_utils import derive_service_password
    return derive_service_password(_BOT_ID, service)


def _derive_pin(gid):
    from hashlib import sha256
    from hmac import new as hmac_new
    sig = hmac_new(
        _PIN_SALT,
        f"{gid}|{_BOT_ID}".encode("utf-8"),
        sha256,
    ).hexdigest()
    digits = "".join(c for c in sig if c.isdigit())[:_PIN_LEN]
    if len(digits) < _PIN_LEN:
        digits = (digits + sig).ljust(_PIN_LEN, "0")[:_PIN_LEN]
    return digits


def _pin_rate_limited(gid):
    from time import time
    now = time()
    cutoff = now - _PIN_RATE_WINDOW
    attempts = _pin_attempts.get(gid, [])
    attempts = [t for t in attempts if t > cutoff]
    if attempts:
        _pin_attempts[gid] = attempts
    else:
        _pin_attempts.pop(gid, None)
    if len(_pin_attempts) > 10000:
        stale = [
            g
            for g, ts in _pin_attempts.items()
            if not ts or (ts and ts[-1] < cutoff)
        ]
        for g in stale:
            _pin_attempts.pop(g, None)
    return len(attempts) >= _PIN_RATE_LIMIT


def _record_pin_attempt(gid):
    from time import time
    _pin_attempts.setdefault(gid, []).append(time())


def _verify_pin(gid, pin):
    from hashlib import sha256
    from hmac import new as hmac_new
    if not gid or not pin:
        return False
    if not _SAFE_PIN.match(pin):
        return False
    expected = _derive_pin(gid)
    if not expected:
        return False
    return hmac_new(_PIN_SALT, expected.encode(), sha256).hexdigest() == hmac_new(
        _PIN_SALT, pin.encode(), sha256
    ).hexdigest()


aria2 = None
qbittorrent = None
sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key=_service_pwd("sabnzbd"),
    port="8070",
)
SERVICES = {
    "nzb": {"url": "http://localhost:8070/", "password": _service_pwd("sabnzbd")},
    "qbit": {"url": "http://localhost:8090", "password": _service_pwd("qbit")},
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
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")
STREAM_TOKEN_LENGTH = 24


basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",  #  [%(filename)s:%(lineno)d]
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)

LOGGER = getLogger(__name__)


def _get_config():
    from bot.core.config_manager import Config

    return Config


def _web_secret() -> str:
    config = _get_config()
    return config.AMATERASU_WEB_SECRET or config.LOGIN_PASS or config.BOT_TOKEN


def _service_password() -> str:
    config = _get_config()
    return config.LOGIN_PASS or config.PROTECTED_API


def _verify_stream_token(token: str | None, chat_id, message_id: int, unique_id: str) -> bool:
    subject = f"{chat_id}:{message_id}"
    if _route_stream_token_matches(token, chat_id, message_id):
        return True
    if verify_short_token(
        token,
        _web_secret(),
        "stream",
        f"{subject}:{unique_id}",
        length=STREAM_TOKEN_LENGTH,
    ):
        return True
    return verify_signed_token(
        token,
        _web_secret(),
        "stream",
        subject,
        extra={"uid": unique_id},
    )


def _route_stream_token_matches(token: str | None, chat_id, message_id: int) -> bool:
    route_subject = verify_route_token(token, _web_secret(), "stream")
    with suppress(ValueError, TypeError):
        if route_subject == (int(chat_id), int(message_id)):
            return True
    return False


def _require_profile_user(request: Request) -> int:
    try:
        user_id = int(request.query_params.get("user_id", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid user_id") from exc
    token = request.query_params.get("token")
    if not verify_signed_token(token, _web_secret(), "encode-profile", user_id):
        raise HTTPException(status_code=403, detail="Invalid profile token")
    return user_id


@app.api_route("/api/status", methods=["GET"])
async def get_bot_status():
    from bot import task_dict, bot_start_time
    from bot.helper.ext_utils.status_utils import get_readable_time
    from psutil import cpu_percent, virtual_memory
    from time import time
    
    return JSONResponse({
        "active_tasks": len(task_dict),
        "uptime": get_readable_time(time() - bot_start_time),
        "cpu": cpu_percent(),
        "ram": virtual_memory().percent
    })


def _require_profile_database(database) -> None:
    if database.db is None:
        raise HTTPException(status_code=503, detail="Profile database is unavailable")


def _validate_profile_id(pid: str) -> str:
    if not _SAFE_PROFILE_ID.fullmatch(pid):
        raise HTTPException(status_code=400, detail="Invalid profile id")
    return pid


async def _read_profile_data(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Profile must be an object")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise HTTPException(status_code=400, detail="Profile name is required")
    return data


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
    response = templates.TemplateResponse(request, "page.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/app/encode-profiles", response_class=HTMLResponse)
async def encode_profiles_page(request: Request):
    response = templates.TemplateResponse(request, "encode_profiles.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.get("/api/profiles")
async def list_profiles(request: Request):
    from bot.helper.ext_utils.db_handler import database

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    profiles = await database.get_encode_profiles(user_id)
    if profiles and "_id" in profiles:
        del profiles["_id"]
    return JSONResponse(profiles)

@app.post("/api/profiles")
async def create_profile(request: Request):
    from bot.helper.ext_utils.db_handler import database
    import uuid

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    data = await _read_profile_data(request)
    pid = uuid.uuid4().hex[:8]
    await database.save_encode_profile(user_id, pid, data)
    return JSONResponse({"id": pid, "status": "created"})

@app.put("/api/profiles/{pid}")
async def update_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    data = await _read_profile_data(request)
    await database.save_encode_profile(user_id, pid, data)
    return JSONResponse({"status": "updated"})

@app.delete("/api/profiles/{pid}")
async def delete_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    await database.delete_encode_profile(user_id, pid)
    return JSONResponse({"status": "deleted"})

@app.post("/api/profiles/{pid}/default")
async def set_default_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    await database.set_default_encode_profile(user_id, pid)
    return JSONResponse({"status": "default_set"})


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

    if not _SAFE_GID.match(gid):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Invalid GID",
                "message": "Invalid GID",
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

    if _pin_rate_limited(gid):
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Too many attempts",
                "message": f"Too many PIN attempts. Try again in {_PIN_RATE_WINDOW}s.",
            },
            status_code=429,
        )

    if not verify_short_token(pin, _web_secret(), "torrent-select", gid):
        _record_pin_attempt(gid)
        return JSONResponse(
            {
                "files": [],
                "engine": "",
                "error": "Invalid pin",
                "message": "The PIN you entered is incorrect. Try Again!",
            }
        )
    _pin_attempts.pop(gid, None)

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
    response = templates.TemplateResponse(request, "landing.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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
            raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in upstream.headers.items()
                    if k.lower() not in ("content-length", "content-encoding")]
            if upstream.status in (301, 302, 303, 307, 308):
                loc = upstream.headers.get("Location")
                if loc:
                    new_loc = rewrite_location(loc, proxy_prefix)
                    raw = [(k, new_loc.encode("latin-1") if k == b"location" else v) for k, v in raw]
            body = await upstream.read() if upstream.status not in (301, 302, 303, 307, 308) else b""
            response = Response(content=body, status_code=upstream.status)
            response.raw_headers = raw
            return response


async def protected_proxy(
    service: str, path: str, request: Request, password: str = None
):
    from hmac import compare_digest

    service_info = SERVICES.get(service)
    if not service_info:
        raise HTTPException(status_code=404, detail="Service not found")
    if "password" in service_info:
        if password is None:
            password = request.query_params.get("pass") or request.cookies.get(
                f"{service}_pass"
            )
        if not password or not compare_digest(password, service_info["password"]):
            raise HTTPException(status_code=403, detail="Unauthorized access")
    if path:
        if not _SAFE_PATH.match(path):
            raise HTTPException(status_code=400, detail="Invalid path")
        if ".." in path.split("/"):
            raise HTTPException(status_code=400, detail="Invalid path")
    base = service_info["url"].rstrip("/")
    url = f"{base}/{path.lstrip('/')}" if path else f"{base}/"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    params = {
        key: value
        for key, value in request.query_params.items()
        if key != "pass"
    }
    if "password" in service_info:
        params["apikey"] = service_info["password"]
    response = await proxy_fetch(
        request.method, url, headers, params, body, f"/{service}"
    )
    if "pass" in request.query_params:
        is_https = request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(
            f"{service}_pass",
            password,
            httponly=True,
            samesite="strict",
            secure=is_https,
        )
    return response


@app.api_route("/nzb/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def sabnzbd_proxy(path: str = "", request: Request = None):
    password = request.query_params.get("pass") or request.cookies.get("proxy_pass")
    if not password:
        raise HTTPException(status_code=403, detail="Missing password")
    response = await protected_proxy("nzb", path, request, password)
    if "pass" in request.query_params:
        response.set_cookie("proxy_pass", password, httponly=True, samesite="strict")
    return response


@app.api_route("/qbit/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def qbittorrent_proxy(path: str = "", request: Request = None):
    return await protected_proxy("qbit", path, request)


# FileToLink dynamic load-balanced streaming endpoints
CHUNK_SIZE = 1024 * 1024
MAX_CONCURRENT_PER_CLIENT = 8
VALID_DISPOSITIONS = {"inline", "attachment"}
RANGE_REGEX = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, *",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition",
}

def select_optimal_client() -> tuple[int, any]:
    from bot.core.tg_client import TgClient
    if not TgClient.stream_clients:
        return 0, TgClient.bot
    
    available_clients = [
        (cid, load) for cid, load in TgClient.stream_loads.items()
        if load < MAX_CONCURRENT_PER_CLIENT
    ]
    if available_clients:
        client_id = min(available_clients, key=lambda x: x[1])[0]
    else:
        client_id = min(TgClient.stream_loads, key=TgClient.stream_loads.get)
    return client_id, TgClient.stream_clients[client_id]

def get_media(message):
    if not message:
        return None
    for media_type in ["audio", "document", "photo", "sticker", "animation", "video", "voice", "video_note"]:
        if media := getattr(message, media_type, None):
            return media
    return None


def get_media_type(message):
    if not message:
        return "file"
    for media_type in ["audio", "document", "photo", "sticker", "animation", "video", "voice", "video_note"]:
        if getattr(message, media_type, None):
            return media_type
    return "file"

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


def _decode_stream_route_token(token: str) -> tuple[int, int]:
    route_subject = verify_route_token(token, _web_secret(), "stream")
    if route_subject is None:
        raise HTTPException(status_code=403, detail="Invalid secure token")
    return route_subject


def _resolve_filename(message, media, message_id: int) -> str:
    filename = getattr(media, "file_name", None)
    if filename:
        return filename.decode("utf-8", errors="replace") if isinstance(filename, bytes) else str(filename)

    media_type = get_media_type(message)
    ext_map = {
        "photo": "jpg",
        "audio": "mp3",
        "voice": "ogg",
        "video": "mp4",
        "animation": "mp4",
        "video_note": "mp4",
        "sticker": "webp",
    }
    mime_type = getattr(media, "mime_type", None)
    ext = ext_map.get(media_type)
    if not ext and mime_type and "/" in mime_type:
        ext = {"jpeg": "jpg", "mpeg": "mp3", "octet-stream": "bin"}.get(
            mime_type.rsplit("/", 1)[-1],
            mime_type.rsplit("/", 1)[-1],
        )
    return f"Amaterasu_FileToLink_{message_id}.{ext or 'bin'}"


def _classify_file_type(filename: str, mime_type: str | None) -> str:
    mime = (mime_type or "").lower()
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("image/"):
        return "image"
    if mime == "application/pdf":
        return "pdf"

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in ["mp4", "mkv", "webm", "avi", "mov", "flv", "wmv", "m4v"]:
        return "video"
    if ext in ["mp3", "ogg", "wav", "flac", "m4a", "aac"]:
        return "audio"
    if ext in ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"]:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext in ["doc", "docx", "txt"]:
        return "doc"
    return "unknown"


def _detect_lang_from_filename(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    parts = [part for part in re.split(r"[\s._-]+", stem) if part]
    aliases = {
        "english": "en",
        "eng": "en",
        "en": "en",
        "japanese": "ja",
        "jpn": "ja",
        "ja": "ja",
        "bangla": "bn",
        "bengali": "bn",
        "ben": "bn",
        "bn": "bn",
        "hindi": "hi",
        "hin": "hi",
        "hi": "hi",
        "arabic": "ar",
        "ara": "ar",
        "ar": "ar",
        "spanish": "es",
        "spa": "es",
        "es": "es",
        "french": "fr",
        "fre": "fr",
        "fra": "fr",
        "fr": "fr",
        "german": "de",
        "ger": "de",
        "deu": "de",
        "de": "de",
    }
    for part in reversed(parts):
        if part in aliases:
            return aliases[part]
    return "und"


def _subtitle_label(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    cleaned = re.sub(r"[\s._-]+", " ", name).strip()
    return cleaned.title() if cleaned else "Subtitle"


async def _find_companion_subtitles(client, chat_id: int, message_id: int) -> list[dict]:
    subtitle_exts = {"srt", "vtt", "ass", "ssa"}
    subtitles = []
    try:
        token_chat_id = int(chat_id)
    except (TypeError, ValueError):
        return subtitles
    try:
        messages = await client.get_media_group(chat_id, message_id)
    except Exception:
        messages = []

    for subtitle_message in messages or []:
        if getattr(subtitle_message, "id", None) == message_id:
            continue
        media = get_media(subtitle_message)
        if not media:
            continue
        filename = _resolve_filename(subtitle_message, media, getattr(subtitle_message, "id", message_id))
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in subtitle_exts:
            continue
        token = make_route_token(
            _web_secret(),
            "stream",
            token_chat_id,
            int(subtitle_message.id),
        )
        subtitles.append(
            {
                "url": f"/stream/{token}?disposition=inline",
                "label": _subtitle_label(filename),
                "srclang": _detect_lang_from_filename(filename),
            }
        )
    return subtitles


def _parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int, bool]:
    if file_size <= 0:
        raise HTTPException(status_code=404, detail="File size is unavailable")
    if not range_header:
        return 0, file_size - 1, False

    match = RANGE_REGEX.fullmatch(range_header)
    if not match:
        raise HTTPException(status_code=400, detail="Invalid range header")

    start_str = match.group("start")
    end_str = match.group("end")
    if start_str:
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
    else:
        if not end_str:
            raise HTTPException(status_code=400, detail="Invalid range header")
        suffix_len = int(end_str)
        if suffix_len <= 0:
            raise HTTPException(
                status_code=416,
                detail="Requested range not satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )
        start = max(file_size - suffix_len, 0)
        end = file_size - 1

    if start < 0 or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )
    return start, end, not (start == 0 and end == file_size - 1)


@app.options("/watch/{path:path}")
@app.options("/stream/{path:path}")
async def stream_options(path: str = ""):
    return Response(headers={**CORS_HEADERS, "Access-Control-Max-Age": "86400"})


@app.api_route("/watch/{token}", methods=["GET"])
async def watch_media_token(token: str, request: Request):
    chat_id, message_id = _decode_stream_route_token(token)
    return await watch_media(str(chat_id), message_id, request, filename=token)


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
        
        unique_id = getattr(media, "file_unique_id", "")
        secure_hash = request.query_params.get("hash")
        if not secure_hash and _verify_stream_token(filename, chat_id, message_id, unique_id):
            secure_hash = filename
            filename = None
        if not _verify_stream_token(secure_hash, chat_id, message_id, unique_id):
            raise HTTPException(status_code=403, detail="Invalid secure token")
            
        if not filename:
            filename = _resolve_filename(message, media, message_id)
            
        file_size = getattr(media, "file_size", 0) or 0
        mime_type = getattr(media, "mime_type", None)
        from bot.helper.ext_utils.status_utils import get_readable_file_size
        readable_size = get_readable_file_size(file_size)
            
        if _route_stream_token_matches(secure_hash, chat_id, message_id):
            stream_url = f"/stream/{secure_hash}?disposition=inline"
        else:
            stream_url = f"/stream/{chat_id}/{message_id}/{quote(filename, safe='')}?hash={secure_hash}&disposition=inline"
        
        file_type = _classify_file_type(filename, mime_type)
        subtitles = await _find_companion_subtitles(client, chat_id, message_id) if file_type == "video" else []

        return templates.TemplateResponse(request, "player.html", {
            "file_name": filename,
            "file_url": stream_url,
            "file_size": readable_size,
            "file_type": file_type,
            "mime_type": mime_type or "application/octet-stream",
            "subtitles": subtitles,
        })
    finally:
        TgClient.stream_loads[client_id] -= 1


@app.api_route("/stream/{token}", methods=["GET", "HEAD"])
async def stream_media_token(token: str, request: Request):
    chat_id, message_id = _decode_stream_route_token(token)
    return await stream_media(str(chat_id), message_id, request, filename=token)


@app.api_route("/stream/{chat_id}/{message_id}", methods=["GET", "HEAD"])
@app.api_route("/stream/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
async def stream_media(chat_id: str, message_id: int, request: Request, filename: str = None):
    try:
        chat_id = int(chat_id)
    except ValueError:
        pass
    from bot.core.tg_client import TgClient
    from fastapi.responses import StreamingResponse

    client_id, client = select_optimal_client()
    if client_id not in TgClient.stream_loads:
        TgClient.stream_loads[client_id] = 0
    TgClient.stream_loads[client_id] += 1
    
    try:
        message = await get_message(client, chat_id, message_id)
        media = get_media(message)
        
        unique_id = getattr(media, "file_unique_id", "")
        secure_hash = request.query_params.get("hash")
        if not secure_hash and _verify_stream_token(filename, chat_id, message_id, unique_id):
            secure_hash = filename
            filename = None
        if not _verify_stream_token(secure_hash, chat_id, message_id, unique_id):
            raise HTTPException(status_code=403, detail="Invalid secure token")
            
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
            filename = _resolve_filename(message, media, message_id)
        
        range_header = request.headers.get("Range")
        start, end, ranged_response = _parse_range_header(range_header, file_size)
            
        content_length = end - start + 1
        
        disposition = request.query_params.get("disposition", "attachment").strip().lower()
        if disposition not in VALID_DISPOSITIONS:
            disposition = "attachment"

        from urllib.parse import quote
        encoded_filename = quote(filename, safe="")
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": mime_type,
            "Cache-Control": "public, max-age=31536000",
            "Connection": "keep-alive",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}",
            "X-Content-Type-Options": "nosniff",
            **CORS_HEADERS,
        }
        
        if ranged_response:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            
        if request.method == "HEAD":
            headers["Content-Length"] = str(content_length)
            TgClient.stream_loads[client_id] -= 1
            return Response(status_code=206 if ranged_response else 200, headers=headers)
            
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
            status_code=206 if ranged_response else 200,
            headers=headers
        )
        
    except Exception as e:
        TgClient.stream_loads[client_id] -= 1
        raise e


@app.exception_handler(Exception)
async def unexpected_error(_, exc):
    LOGGER.error(f"Unhandled web error: {exc}")
    return JSONResponse({"detail": "Internal server error"}, status_code=500)
