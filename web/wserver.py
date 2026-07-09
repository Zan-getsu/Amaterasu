import mimetypes
import re
from asyncio import create_task, sleep
from contextlib import asynccontextmanager, suppress
from hashlib import sha256
from importlib import import_module
from logging import FileHandler, StreamHandler, basicConfig, getLogger, INFO, WARNING
from os import environ
from pathlib import Path
from re import compile as re_compile
from time import monotonic
from urllib.parse import quote, urlparse

from aioaria2 import Aria2HttpClient
from aiohttp.client_exceptions import ClientError
from aioqbt.client import create_client
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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
# PIN salt loaded from per-deployment secrets module (env var or .amaterasu_secrets).
# Backward-compat: if neither is set, falls back to legacy constant.
try:
    from bot.helper.ext_utils.secrets import PIN_SALT as _PIN_SALT
except Exception:  # pragma: no cover — import-time fallback
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
    from bot.core.config_manager import Config
    from bot.helper.ext_utils.db_handler import database
    from bot.core.tg_client import db_partition_id, TgClient
    
    Config.load_config()
    Config.load_env()
    await database.connect()
    
    if database.db is not None:
        bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
        PART = db_partition_id(bot_id)
        db_config = await database.db.settings.config.find_one({"_id": PART}, {"_id": 0})
        if not db_config:
            db_config = await database.db.settings.deployConfig.find_one({"_id": PART}, {"_id": 0})
        if db_config:
            Config.load_dict(db_config)
            Config.load_env()
            
    if Config.BOT_TOKEN:
        TgClient.bot = TgClient.tgClient(
            "Amaterasu-Web-Bot",
            bot_token=Config.BOT_TOKEN,
            no_updates=True,
        )
        await TgClient.bot.start()
        await TgClient.start_stream_clients()
            
    aria2 = Aria2HttpClient("http://localhost:6800/jsonrpc")
    qbittorrent = await create_client("http://localhost:8090/api/v2/")
    yield
    await aria2.close()
    await qbittorrent.close()
    if Config.BOT_TOKEN:
        await TgClient.stop()
    await database.disconnect()


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
    # Priority: AMATERASU_WEB_SECRET env var > Config.AMATERASU_WEB_SECRET
    # > Config.LOGIN_PASS > Config.BOT_TOKEN. Matches the priority in
    # bot.helper.ext_utils.secrets.get_web_secret so the bot process and
    # the gunicorn web process agree on the same secret.
    env_val = environ.get("AMATERASU_WEB_SECRET")
    if env_val and env_val.strip():
        return env_val.strip()
    config = _get_config()
    return (
        config.AMATERASU_WEB_SECRET
        or config.LOGIN_PASS
        or config.BOT_TOKEN
    )


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


@app.get("/healthz")
async def healthz():
    """Lightweight health check for k8s/LB probes.

    Returns 200 if the FastAPI app is up and the DB is reachable (if
    configured). Returns 503 if the DB is configured but unreachable.

    Phase 2.9 — includes engine health states in the response body.
    The response code is still 200/503 based on DB connectivity (so
    k8s probes don't flap on engine restarts), but the body includes
    `engines` with per-engine state and `unavailable_engines` count.
    """
    try:
        from bot.helper.ext_utils.db_handler import database
        from bot.core.config_manager import Config
        if Config.DATABASE_URL and database.db is None:
            return JSONResponse(
                {"status": "degraded", "reason": "database not connected"},
                status_code=503,
            )
    except Exception as e:
        # If the import itself fails, the bot is in a bad state but the
        # web server is up — return 200 with a warning so the probe
        # doesn't kill the pod before the bot can recover.
        return JSONResponse({"status": "degraded", "reason": str(e)[:200]})
    # Phase 2.9 — include engine health in the response body
    try:
        from bot.helper.ext_utils.engine_health import get_health_states, get_unavailable_count
        engines = get_health_states()
        unavailable = get_unavailable_count()
    except Exception:
        engines = {}
        unavailable = 0
    return JSONResponse({
        "status": "ok",
        "engines": engines,
        "unavailable_engines": unavailable,
    })


@app.get("/metrics")
async def metrics():
    """Prometheus-format metrics endpoint.

    Exposes: active tasks, uptime, CPU%, RAM%, DB connection state.
    No PII. Intended for scraping by Prometheus/Grafana.
    """
    from time import time as _time
    from psutil import cpu_percent, virtual_memory
    try:
        from bot import task_dict, bot_start_time
        active_tasks = len(task_dict)
        uptime_seconds = _time() - bot_start_time
    except Exception:
        active_tasks = 0
        uptime_seconds = 0
    try:
        from bot.helper.ext_utils.db_handler import database
        db_connected = 1 if getattr(database, "db", None) is not None else 0
    except Exception:
        db_connected = 0
    cpu = cpu_percent()
    ram = virtual_memory().percent
    lines = [
        "# HELP amaterasu_active_tasks Number of tasks currently in task_dict.",
        "# TYPE amaterasu_active_tasks gauge",
        f"amaterasu_active_tasks {active_tasks}",
        "# HELP amaterasu_uptime_seconds Uptime of the bot process in seconds.",
        "# TYPE amaterasu_uptime_seconds gauge",
        f"amaterasu_uptime_seconds {uptime_seconds:.0f}",
        "# HELP amaterasu_cpu_percent CPU usage percent (psutil).",
        "# TYPE amaterasu_cpu_percent gauge",
        f"amaterasu_cpu_percent {cpu}",
        "# HELP amaterasu_ram_percent RAM usage percent (psutil).",
        "# TYPE amaterasu_ram_percent gauge",
        f"amaterasu_ram_percent {ram}",
        "# HELP amaterasu_db_connected 1 if MongoDB is connected, 0 otherwise.",
        "# TYPE amaterasu_db_connected gauge",
        f"amaterasu_db_connected {db_connected}",
        "",
    ]
    return Response(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


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
    from bot.core.config_manager import Config

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
    doc_id = f"{bot_id}_{user_id}"
    profiles = await database.db.encode_profiles.find_one({"_id": doc_id})
    profiles = profiles or {}
    profiles.pop("_id", None)
    return JSONResponse(profiles)

@app.post("/api/profiles")
async def create_profile(request: Request):
    from bot.helper.ext_utils.db_handler import database
    from bot.core.config_manager import Config
    import uuid

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    data = await _read_profile_data(request)
    pid = uuid.uuid4().hex[:8]
    bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
    doc_id = f"{bot_id}_{user_id}"
    await database.db.encode_profiles.update_one(
        {"_id": doc_id},
        {"$set": {pid: data}},
        upsert=True,
    )
    return JSONResponse({"id": pid, "status": "created"})

@app.put("/api/profiles/{pid}")
async def update_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database
    from bot.core.config_manager import Config

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    data = await _read_profile_data(request)
    bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
    doc_id = f"{bot_id}_{user_id}"
    await database.db.encode_profiles.update_one(
        {"_id": doc_id},
        {"$set": {pid: data}},
        upsert=True,
    )
    return JSONResponse({"status": "updated"})

@app.delete("/api/profiles/{pid}")
async def delete_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database
    from bot.core.config_manager import Config

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
    doc_id = f"{bot_id}_{user_id}"
    await database.db.encode_profiles.update_one(
        {"_id": doc_id},
        {"$unset": {pid: ""}},
    )
    return JSONResponse({"status": "deleted"})

@app.post("/api/profiles/{pid}/default")
async def set_default_profile(pid: str, request: Request):
    from bot.helper.ext_utils.db_handler import database
    from bot.core.config_manager import Config

    user_id = _require_profile_user(request)
    _require_profile_database(database)
    pid = _validate_profile_id(pid)
    bot_id = Config.BOT_TOKEN.split(":", 1)[0] if Config.BOT_TOKEN else "0"
    doc_id = f"{bot_id}_{user_id}"
    profiles = await database.db.encode_profiles.find_one({"_id": doc_id})
    if not profiles or pid not in profiles:
        raise HTTPException(status_code=404, detail="Profile not found")
    update_dict = {}
    for k, v in profiles.items():
        if k == "_id":
            continue
        if isinstance(v, dict) and v.get("is_default"):
            update_dict[f"{k}.is_default"] = False
    if update_dict:
        await database.db.encode_profiles.update_one(
            {"_id": doc_id}, {"$set": update_dict}
        )
    await database.db.encode_profiles.update_one(
        {"_id": doc_id},
        {"$set": {f"{pid}.is_default": True}},
        upsert=True,
    )
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
    from bot.version import get_version

    response = templates.TemplateResponse(
        request, "landing.html", {"version": get_version()}
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ────────────────────────────────────────────────────────────────────
# Phase 1.3 — Web UI login password (LOGIN_PASS)
# ────────────────────────────────────────────────────────────────────
# When Config.LOGIN_PASS is set, all admin routes require a session_token
# cookie obtained via /login. Public routes (/, /healthz, /metrics,
# /stream/*, /dl/*, /watch/*, /login) are exempt. The session token is
# an HMAC signature of "amaterasu_session" with the web secret — stateless,
# no server-side session storage needed. Cookie expires in 7 days.

_LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Amaterasu — Login</title>
<style>
body { font-family: -apple-system, system-ui, sans-serif; background: #f5f6f7;
       display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }
.card { background: #fff; padding: 2rem; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        width: 100%; max-width: 360px; }
h1 { font-size: 1.5rem; margin: 0 0 1.5rem; color: #1d1f20; }
label { display: block; margin-bottom: 0.5rem; font-size: 0.9rem; color: #476675; }
input[type="password"] { width: 100%; padding: 0.6rem; border: 1px solid #c1cbd1;
                         border-radius: 4px; font-size: 1rem; box-sizing: border-box; }
button { width: 100%; padding: 0.7rem; background: #1c6d96; color: #fff; border: none;
         border-radius: 4px; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
button:hover { background: #155a7e; }
.error { color: #a0524a; font-size: 0.85rem; margin-top: 0.5rem; }
</style>
</head>
<body>
<div class="card">
<h1>Amaterasu Login</h1>
<form method="POST" action="/login">
<label for="password">Password</label>
<input type="password" id="password" name="password" autofocus required>
{error_html}
<button type="submit">Login</button>
</form>
</div>
</body>
</html>"""

# Admin routes that require login when LOGIN_PASS is set
_ADMIN_PATH_PREFIXES = ("/app/", "/api/profiles", "/qbit/", "/nzb/")
# Public routes that never require login
_PUBLIC_PATHS = frozenset({"/", "/api/status", "/healthz", "/metrics", "/login"})


def _make_session_cookie() -> str:
    """Create a signed session token. HMAC of 'amaterasu_session' with
    the web secret. Stateless — no server-side storage."""
    from hmac import new as hmac_new
    from hashlib import sha256
    from base64 import urlsafe_b64encode
    secret = _web_secret().encode("utf-8")
    mac = hmac_new(secret, b"amaterasu_session", sha256).digest()
    return urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _verify_session_cookie(token: str | None) -> bool:
    """Verify the session cookie against the expected HMAC."""
    if not token:
        return False
    from hmac import new as hmac_new, compare_digest
    from hashlib import sha256
    from base64 import urlsafe_b64encode
    expected = _make_session_cookie()
    return compare_digest(token, expected)


def _login_pass_configured() -> bool:
    """Check if LOGIN_PASS is set (non-empty). When not set, login is
    skipped entirely — all routes are public (v1.5.0 behavior)."""
    config = _get_config()
    return bool(getattr(config, "LOGIN_PASS", "") or "")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None):
    """Render the login form. Only meaningful when LOGIN_PASS is set."""
    if not _login_pass_configured():
        # If LOGIN_PASS is not set, redirect to home — no login needed
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)
    error_html = f'<p class="error">{error}</p>' if error else ""
    return HTMLResponse(_LOGIN_PAGE_HTML.replace("{error_html}", error_html))


@app.post("/login")
async def login_submit(request: Request):
    """Validate the password and set the session cookie."""
    if not _login_pass_configured():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302)
    form = await request.form()
    password = form.get("password", "")
    config = _get_config()
    from hmac import compare_digest
    if compare_digest(str(password), str(config.LOGIN_PASS)):
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            key="amaterasu_session",
            value=_make_session_cookie(),
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            max_age=7 * 24 * 3600,  # 7 days
            path="/",
        )
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/", status_code=302, headers={
            "set-cookie": response.headers.get("set-cookie", "")
        })
    return HTMLResponse(
        _LOGIN_PAGE_HTML.replace(
            "{error_html}", '<p class="error">Incorrect password.</p>'
        ),
        status_code=401,
    )


@app.middleware("http")
async def login_gate(request: Request, call_next):
    """Middleware that enforces LOGIN_PASS on admin routes.

    Public routes (/, /api/status, /healthz, /metrics, /stream/*, /dl/*, /watch/*,
    /login) are always allowed. Admin routes (/app/*, /api/profiles*,
    /qbit/*, /nzb/*) require a valid session cookie when LOGIN_PASS is
    set. When LOGIN_PASS is not set, all routes are public (v1.5.0).
    """
    path = request.url.path
    # Always allow public paths
    if path in _PUBLIC_PATHS or path.startswith(("/stream/", "/dl/", "/watch/")):
        return await call_next(request)
    # If LOGIN_PASS is not set, allow everything (v1.5.0 behavior)
    if not _login_pass_configured():
        return await call_next(request)
    # Check session cookie for admin routes
    if path.startswith(_ADMIN_PATH_PREFIXES):
        cookie = request.cookies.get("amaterasu_session")
        if not _verify_session_cookie(cookie):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=302)
    return await call_next(request)


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
    password = request.query_params.get("pass") or request.cookies.get("nzb_pass")
    if not password:
        raise HTTPException(status_code=403, detail="Missing password")
    return await protected_proxy("nzb", path, request, password)


@app.api_route("/qbit/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def qbittorrent_proxy(path: str = "", request: Request = None):
    password = request.query_params.get("pass") or request.cookies.get("qbit_pass")
    if not password:
        raise HTTPException(status_code=403, detail="Missing password")
    return await protected_proxy("qbit", path, request, password)


# FileToLink dynamic load-balanced streaming endpoints
CHUNK_SIZE = 1024 * 1024
MAX_CONCURRENT_PER_CLIENT = 8
STREAM_CLIENT_COOLDOWN_SECONDS = 45
FILETOLINK_CACHE_DIR = environ.get("FILETOLINK_CACHE_DIR", "/tmp/amaterasu-filetolink")
VALID_DISPOSITIONS = {"inline", "attachment"}
RANGE_REGEX = re.compile(r"^bytes=(?P<start>\d*)-(?P<end>\d*)$")
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, *",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition",
}
_filetolink_cache_locks = {}
_filetolink_cache_warm_tasks = set()
_stream_client_health = {}


def _resolve_cache_max_bytes() -> int:
    try:
        cache_max_mb = int(environ.get("FILETOLINK_CACHE_MAX_MB", "256"))
    except (TypeError, ValueError):
        cache_max_mb = 256
    return max(cache_max_mb, 0) * 1024 * 1024


def _resolve_cache_total_max_bytes() -> int:
    try:
        cache_total_max_mb = int(environ.get("FILETOLINK_CACHE_TOTAL_MAX_MB", "2048"))
    except (TypeError, ValueError):
        cache_total_max_mb = 2048
    return max(cache_total_max_mb, 0) * 1024 * 1024


FILETOLINK_CACHE_MAX_BYTES = _resolve_cache_max_bytes()
FILETOLINK_CACHE_TOTAL_MAX_BYTES = _resolve_cache_total_max_bytes()


def _release_stream_load(client_id: int) -> None:
    from bot.core.tg_client import TgClient

    TgClient.stream_loads[client_id] = max(
        TgClient.stream_loads.get(client_id, 1) - 1,
        0,
    )


def _stream_health(client_id: int) -> dict:
    return _stream_client_health.setdefault(
        client_id,
        {"failures": 0, "cooldown_until": 0.0, "last_error": ""},
    )


def _stream_client_available(client_id: int) -> bool:
    return monotonic() >= float(_stream_health(client_id).get("cooldown_until") or 0)


def _record_stream_success(client_id: int) -> None:
    health = _stream_health(client_id)
    health["failures"] = 0
    health["cooldown_until"] = 0.0
    health["last_error"] = ""


def _record_stream_failure(client_id: int, reason: str) -> None:
    health = _stream_health(client_id)
    failures = int(health.get("failures") or 0) + 1
    health["failures"] = failures
    health["last_error"] = str(reason)[:160]
    if failures >= 2:
        health["cooldown_until"] = monotonic() + STREAM_CLIENT_COOLDOWN_SECONDS


def _stream_client_choices() -> list[tuple[int, any]]:
    from bot.core.tg_client import TgClient

    if not TgClient.stream_clients:
        return [(0, TgClient.bot)]

    for client_id in TgClient.stream_clients:
        TgClient.stream_loads.setdefault(client_id, 0)

    def client_rank(item):
        client_id, _ = item
        load = TgClient.stream_loads.get(client_id, 0)
        unavailable = not _stream_client_available(client_id)
        return (unavailable, load >= MAX_CONCURRENT_PER_CLIENT, load, client_id)

    return sorted(TgClient.stream_clients.items(), key=client_rank)


def _acquire_stream_client(client_id: int) -> None:
    from bot.core.tg_client import TgClient

    TgClient.stream_loads[client_id] = TgClient.stream_loads.get(client_id, 0) + 1


def select_optimal_client() -> tuple[int, any]:
    return _stream_client_choices()[0]

def get_media(message):
    # Phase 2.12 — delegate to canonical implementation in tg_utils.py
    from bot.helper.telegram_helper.tg_utils import get_media as _get_media
    return _get_media(message)


def get_media_type(message):
    # Phase 2.12 — delegate to canonical implementation in tg_utils.py
    from bot.helper.telegram_helper.tg_utils import get_media_type as _get_media_type
    return _get_media_type(message)

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


async def get_message_with_stream_client(chat_id: int, message_id: int) -> tuple[int, any, any]:
    last_error = None
    for client_id, client in _stream_client_choices():
        _acquire_stream_client(client_id)
        try:
            message = await get_message(client, chat_id, message_id)
            _record_stream_success(client_id)
            return client_id, client, message
        except HTTPException as e:
            last_error = e
            _record_stream_failure(client_id, e.detail)
            _release_stream_load(client_id)
            LOGGER.warning(
                f"FileToLink stream client {client_id} cannot fetch "
                f"{chat_id}/{message_id}: {e.detail}"
            )

    if last_error:
        raise last_error
    raise HTTPException(status_code=503, detail="No stream client is available")


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


def _file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _normalize_mime_type(filename: str, mime_type: str | None) -> str:
    mime = (mime_type or "").strip().lower()
    guessed = mimetypes.guess_type(filename)[0]
    if not mime or mime == "application/octet-stream":
        return guessed or mime or "application/octet-stream"
    return mime


def _absolute_public_url(request: Request, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    config_base = getattr(_get_config(), "BASE_URL", "") or ""
    base_url = config_base.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base_url}{path if path.startswith('/') else '/' + path}"


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
    if mime.startswith("text/") or mime in {
        "application/json",
        "application/xml",
        "application/x-subrip",
        "text/vtt",
    }:
        return "text"

    ext = _file_extension(filename)
    if ext in ["mp4", "mkv", "webm", "avi", "mov", "flv", "wmv", "m4v"]:
        return "video"
    if ext in ["mp3", "ogg", "wav", "flac", "m4a", "aac"]:
        return "audio"
    if ext in ["jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"]:
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext in ["txt", "log", "md", "nfo", "srt", "vtt", "json", "xml", "csv", "tsv"]:
        return "text"
    if ext in ["doc", "docx", "xls", "xlsx", "ppt", "pptx"]:
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


def _cache_path_for_media(chat_id, message_id: int, unique_id: str, filename: str) -> Path:
    cache_key = sha256(
        f"{chat_id}:{message_id}:{unique_id}:{filename}".encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()
    ext = ""
    if "." in filename:
        suffix = filename.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{1,12}", suffix):
            ext = f".{suffix}"
    return Path(FILETOLINK_CACHE_DIR) / f"{cache_key}{ext}"


def _existing_cached_media(
    chat_id,
    message_id: int,
    unique_id: str,
    filename: str,
    file_size: int,
) -> Path | None:
    if file_size <= 0:
        return None

    cache_path = _cache_path_for_media(chat_id, message_id, unique_id, filename)
    try:
        if cache_path.exists() and cache_path.stat().st_size == file_size:
            with suppress(OSError):
                cache_path.touch()
            return cache_path
        if cache_path.exists():
            with suppress(FileNotFoundError):
                cache_path.unlink()
    except OSError:
        return None
    return None


def _prune_filetolink_cache(required_bytes: int = 0) -> None:
    if FILETOLINK_CACHE_TOTAL_MAX_BYTES <= 0:
        return

    cache_dir = Path(FILETOLINK_CACHE_DIR)
    if not cache_dir.exists():
        return

    entries = []
    total_size = 0
    try:
        iterator = cache_dir.iterdir()
    except OSError:
        return

    for path in iterator:
        try:
            if not path.is_file() or path.name.endswith(".part"):
                continue
            stat = path.stat()
        except OSError:
            continue
        total_size += stat.st_size
        entries.append((stat.st_mtime, path, stat.st_size))

    target_size = max(FILETOLINK_CACHE_TOTAL_MAX_BYTES - max(required_bytes, 0), 0)
    if total_size <= target_size:
        return

    for _, path, size in sorted(entries):
        with suppress(OSError):
            path.unlink()
            total_size -= size
        if total_size <= target_size:
            break


async def _get_cached_media(
    preferred_client_id: int,
    preferred_client,
    message,
    chat_id,
    message_id: int,
    unique_id: str,
    filename: str,
    file_size: int,
) -> Path | None:
    if file_size <= 0 or file_size > FILETOLINK_CACHE_MAX_BYTES:
        return None
    if FILETOLINK_CACHE_TOTAL_MAX_BYTES and file_size > FILETOLINK_CACHE_TOTAL_MAX_BYTES:
        return None

    import asyncio
    from pyrogram.errors import FloodWait
    from bot.core.tg_client import TgClient

    if cached_path := _existing_cached_media(
        chat_id,
        message_id,
        unique_id,
        filename,
        file_size,
    ):
        return cached_path

    cache_path = _cache_path_for_media(chat_id, message_id, unique_id, filename)

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        LOGGER.warning(f"FileToLink cache disabled; cannot create cache dir: {e}")
        return None
    lock_key = cache_path.stem
    lock = _filetolink_cache_locks.setdefault(lock_key, asyncio.Lock())

    async with lock:
        if cached_path := _existing_cached_media(
            chat_id,
            message_id,
            unique_id,
            filename,
            file_size,
        ):
            return cached_path

        _prune_filetolink_cache(file_size)

        temp_path = cache_path.with_suffix(f"{cache_path.suffix}.part")
        with suppress(FileNotFoundError):
            temp_path.unlink()

        client_choices = [(preferred_client_id, preferred_client)]
        client_choices.extend(
            (cid, client)
            for cid, client in TgClient.stream_clients.items()
            if cid != preferred_client_id
        )

        for cache_client_id, cache_client in client_choices:
            extra_load = cache_client_id != preferred_client_id
            downloaded_path = temp_path
            if extra_load:
                TgClient.stream_loads[cache_client_id] = (
                    TgClient.stream_loads.get(cache_client_id, 0) + 1
                )
            try:
                cache_message = message
                if cache_client_id != preferred_client_id:
                    cache_message = await get_message(cache_client, chat_id, message_id)
                downloaded = await cache_client.download_media(
                    cache_message,
                    file_name=str(temp_path),
                )
                downloaded_path = Path(downloaded) if downloaded else temp_path
                if not downloaded_path.exists():
                    raise RuntimeError("download_media returned no file")
                downloaded_size = downloaded_path.stat().st_size
                if downloaded_size <= 0:
                    raise RuntimeError("downloaded file is empty")
                if downloaded_size != file_size:
                    raise RuntimeError(
                        f"downloaded file is incomplete ({downloaded_size}/{file_size})"
                    )
                downloaded_path.replace(cache_path)
                LOGGER.info(
                    f"FileToLink cache ready: {filename} | client={cache_client_id} "
                    f"| size={cache_path.stat().st_size}"
                )
                return cache_path
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception as e:
                LOGGER.warning(
                    f"FileToLink cache failed for {filename} with client="
                    f"{cache_client_id}: {e}"
                )
                with suppress(FileNotFoundError):
                    temp_path.unlink()
                if downloaded_path != temp_path:
                    with suppress(FileNotFoundError):
                        downloaded_path.unlink()
            finally:
                if extra_load:
                    TgClient.stream_loads[cache_client_id] = max(
                        TgClient.stream_loads.get(cache_client_id, 1) - 1,
                        0,
                    )

    return None


def _schedule_cache_warm(
    preferred_client_id: int,
    preferred_client,
    message,
    chat_id,
    message_id: int,
    unique_id: str,
    filename: str,
    file_size: int,
) -> None:
    if file_size <= 0 or file_size > FILETOLINK_CACHE_MAX_BYTES:
        return
    if FILETOLINK_CACHE_TOTAL_MAX_BYTES and file_size > FILETOLINK_CACHE_TOTAL_MAX_BYTES:
        return
    if _existing_cached_media(chat_id, message_id, unique_id, filename, file_size):
        return

    cache_key = _cache_path_for_media(chat_id, message_id, unique_id, filename).stem
    if cache_key in _filetolink_cache_warm_tasks:
        return
    _filetolink_cache_warm_tasks.add(cache_key)

    async def warm_cache():
        _acquire_stream_client(preferred_client_id)
        try:
            await _get_cached_media(
                preferred_client_id,
                preferred_client,
                message,
                chat_id,
                message_id,
                unique_id,
                filename,
                file_size,
            )
        except Exception as e:
            LOGGER.warning(f"FileToLink background cache warm failed for {filename}: {e}")
        finally:
            _release_stream_load(preferred_client_id)
            _filetolink_cache_warm_tasks.discard(cache_key)

    create_task(warm_cache())


@app.options("/watch/{path:path}")
@app.options("/stream/{path:path}")
@app.options("/dl/{path:path}")
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

    client_id, client, message = await get_message_with_stream_client(chat_id, message_id)

    try:
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
        mime_type = _normalize_mime_type(filename, getattr(media, "mime_type", None))
        from bot.helper.ext_utils.status_utils import get_readable_file_size
        readable_size = get_readable_file_size(file_size)
            
        if _route_stream_token_matches(secure_hash, chat_id, message_id):
            stream_url = f"/stream/{secure_hash}?disposition=inline"
            download_url = f"/dl/{secure_hash}"
        else:
            stream_url = f"/stream/{chat_id}/{message_id}/{quote(filename, safe='')}?hash={secure_hash}&disposition=inline"
            download_url = f"/dl/{chat_id}/{message_id}/{quote(filename, safe='')}?hash={secure_hash}"
        
        file_type = _classify_file_type(filename, mime_type)
        absolute_file_url = _absolute_public_url(request, stream_url)
        absolute_download_url = _absolute_public_url(request, download_url)
        doc_preview_url = (
            f"https://docs.google.com/gview?url={quote(absolute_file_url, safe='')}&embedded=true"
            if file_type == "doc"
            else ""
        )
        LOGGER.info(f"Watch page: {filename} | client={client_id} | type={file_type} | size={readable_size}")
        subtitles = await _find_companion_subtitles(client, chat_id, message_id) if file_type == "video" else []

        return templates.TemplateResponse(request, "player.html", {
            "file_name": filename,
            "file_url": stream_url,
            "absolute_file_url": absolute_file_url,
            "download_url": download_url,
            "absolute_download_url": absolute_download_url,
            "doc_preview_url": doc_preview_url,
            "file_size": readable_size,
            "file_type": file_type,
            "file_extension": _file_extension(filename) or "file",
            "mime_type": mime_type,
            "subtitles": subtitles,
        })
    finally:
        _release_stream_load(client_id)


@app.api_route("/stream/{token}", methods=["GET", "HEAD"])
async def stream_media_token(token: str, request: Request):
    chat_id, message_id = _decode_stream_route_token(token)
    return await stream_media(str(chat_id), message_id, request, filename=token)


@app.api_route("/dl/{token}", methods=["GET", "HEAD"])
async def download_media_token(token: str, request: Request):
    chat_id, message_id = _decode_stream_route_token(token)
    return await stream_media(str(chat_id), message_id, request, filename=token)


@app.api_route("/stream/{chat_id}/{message_id}", methods=["GET", "HEAD"])
@app.api_route("/stream/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
@app.api_route("/dl/{chat_id}/{message_id}", methods=["GET", "HEAD"])
@app.api_route("/dl/{chat_id}/{message_id}/{filename}", methods=["GET", "HEAD"])
async def stream_media(chat_id: str, message_id: int, request: Request, filename: str = None):
    try:
        chat_id = int(chat_id)
    except ValueError:
        pass
    from fastapi.responses import StreamingResponse

    client_id, client, message = await get_message_with_stream_client(chat_id, message_id)

    try:
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
        mime_type = _normalize_mime_type(filename, mime_type)
        
        range_header = request.headers.get("Range")
        start, end, ranged_response = _parse_range_header(range_header, file_size)
            
        content_length = end - start + 1
        
        if request.url.path.startswith("/dl/"):
            disposition = "attachment"
        else:
            disposition = request.query_params.get("disposition", "attachment").strip().lower()
        if disposition not in VALID_DISPOSITIONS:
            disposition = "attachment"

        from bot.helper.ext_utils.status_utils import get_readable_file_size
        readable_size = get_readable_file_size(file_size)
        mode = "Download" if disposition == "attachment" else "Stream"
        LOGGER.info(f"{mode}: {filename} | client={client_id} | size={readable_size} | range={'bytes ' + str(start) + '-' + str(end) if ranged_response else 'full'}")

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
            response = Response(
                status_code=206 if ranged_response else 200,
                headers=headers,
            )
            _release_stream_load(client_id)
            return response

        cached_path = _existing_cached_media(
            chat_id,
            message_id,
            unique_id,
            filename,
            file_size,
        )
        if cached_path:
            file_headers = {
                key: value
                for key, value in headers.items()
                if key.lower()
                not in {
                    "accept-ranges",
                    "content-disposition",
                    "content-length",
                    "content-range",
                    "content-type",
                }
            }
            response = FileResponse(
                cached_path,
                media_type=mime_type,
                filename=filename,
                content_disposition_type=disposition,
                headers=file_headers,
            )
            _release_stream_load(client_id)
            return response
            
        async def stream_generator():
            try:
                bytes_sent = 0
                
                import asyncio
                from pyrogram.errors import FloodWait
                
                started_stream = False
                retries_left = 3

                while bytes_sent < content_length:
                    absolute_pos = start + bytes_sent
                    bytes_to_skip = absolute_pos % CHUNK_SIZE
                    chunk_offset = absolute_pos // CHUNK_SIZE
                    remaining_total = content_length - bytes_sent
                    chunk_limit = (
                        (remaining_total + bytes_to_skip + CHUNK_SIZE - 1)
                        // CHUNK_SIZE
                    ) + 1

                    try:
                        media_generator = client.stream_media(
                            message, offset=chunk_offset, limit=chunk_limit
                        )

                        async for chunk in media_generator:
                            started_stream = True
                            retries_left = 3
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
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except TimeoutError as e:
                        if retries_left <= 0:
                            _record_stream_failure(client_id, f"stream timeout: {e}")
                            LOGGER.warning(
                                f"Telegram stream timed out for {filename} after "
                                f"{bytes_sent}/{content_length} bytes: {e}"
                            )
                            return
                        retries_left -= 1
                        await asyncio.sleep(2)
                    except Exception as e:
                        if e.__class__.__name__ == "TimeoutError":
                            if retries_left <= 0:
                                _record_stream_failure(client_id, f"stream timeout: {e}")
                                LOGGER.warning(
                                    f"Telegram stream timed out for {filename} after "
                                    f"{bytes_sent}/{content_length} bytes: {e}"
                                )
                                return
                            retries_left -= 1
                            await asyncio.sleep(2)
                            continue
                        if started_stream:
                            _record_stream_failure(client_id, f"stream interrupted: {e}")
                            LOGGER.warning(
                                f"Telegram stream interrupted for {filename} after "
                                f"{bytes_sent}/{content_length} bytes: {e}"
                            )
                            return
                        _record_stream_failure(client_id, f"stream failed: {e}")
                        raise HTTPException(status_code=404, detail="Failed to stream media") from e
                if bytes_sent >= content_length:
                    _record_stream_success(client_id)
                    if not range_header:
                        _schedule_cache_warm(
                            client_id,
                            client,
                            message,
                            chat_id,
                            message_id,
                            unique_id,
                            filename,
                            file_size,
                        )
            finally:
                _release_stream_load(client_id)
                
        # Do not send Content-Length for live Telegram streams. If Telegram
        # times out mid-transfer, chunked streaming can end cleanly instead
        # of tripping h11's "Too little data for declared Content-Length".
        return StreamingResponse(
            stream_generator(),
            status_code=206 if ranged_response else 200,
            headers=headers
        )
        
    except Exception as e:
        _release_stream_load(client_id)
        raise e


@app.exception_handler(Exception)
async def unexpected_error(_, exc):
    LOGGER.error(f"Unhandled web error: {exc}")
    return JSONResponse({"detail": "Internal server error"}, status_code=500)
