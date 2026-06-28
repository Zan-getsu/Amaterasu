from asyncio import (
    CancelledError,
    create_subprocess_exec,
    create_subprocess_shell,
    run_coroutine_threadsafe,
    sleep,
)
from asyncio.subprocess import PIPE
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from hashlib import sha256
from hmac import new as hmac_new
from os import path as ospath
from re import compile as re_compile
from secrets import token_bytes
from urllib.parse import unquote, urlparse

from aiofiles import open as aiopen
from aiofiles.os import mkdir
from aiofiles.os import path as aiopath
from httpx import AsyncClient, Limits
from pyrogram.enums import ButtonStyle
from pyrogram.handlers import MessageHandler

from ... import LOGGER, bot_loop, user_data
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker
from web.security import make_short_token
from .db_handler import database
from .help_messages import (
    CLONE_HELP_DICT,
    MIRROR_HELP_DICT,
    YT_HELP_DICT,
)
from .secrets import PIN_SALT as _PIN_SALT
from .secrets import SERVICE_PWD_SALT as _SERVICE_PWD_SALT
from .telegraph_helper import telegraph

DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Salts are now loaded from env vars or .amaterasu_secrets file (per-deployment).
# See bot/helper/ext_utils/secrets.py for migration / rotation instructions.
_PIN_LEN = 4
_PIN_RATE_LIMIT = 5
_PIN_RATE_WINDOW = 60

_cached_secret_bytes = None


def get_web_secret():
    from .secrets import get_web_secret as _gws
    return _gws() or Config.AMATERASU_WEB_SECRET or Config.LOGIN_PASS or Config.BOT_TOKEN


def _shared_secret():
    global _cached_secret_bytes
    secret = Config.WEB_ACCESS_PASSWORD or Config.AMATERASU_WEB_SECRET
    if not secret:
        if _cached_secret_bytes is None:
            _cached_secret_bytes = token_bytes(32)
        return _cached_secret_bytes
    return secret.encode("utf-8") if isinstance(secret, str) else secret


def derive_service_password(bot_id, service):
    if not bot_id:
        bot_id = "0"
    secret = _shared_secret()
    digest = hmac_new(
        _SERVICE_PWD_SALT,
        f"{bot_id}:{service}".encode("utf-8"),
        sha256,
    )
    digest.update(secret)
    raw = digest.hexdigest()
    return raw[:20] + raw[-4:]


def _resolve_bot_id():
    token = Config.BOT_TOKEN
    if not isinstance(token, str) or not token.strip():
        return "0"
    token = token.strip()
    return (token.split(":", 1)[0] or "0").strip()


def derive_pin(gid, bot_id):
    if not gid:
        return None
    if not bot_id:
        bot_id = "0"
    sig = hmac_new(
        _PIN_SALT,
        f"{gid}|{bot_id}".encode("utf-8"),
        sha256,
    ).hexdigest()
    digits = "".join(c for c in sig if c.isdigit())[:_PIN_LEN]
    if len(digits) < _PIN_LEN:
        digits = (digits + sig).ljust(_PIN_LEN, "0")[:_PIN_LEN]
    return digits


def verify_pin(gid, pin, bot_id):
    if not gid or not pin:
        return False
    if not pin.isdigit() or len(pin) != _PIN_LEN:
        return False
    expected = derive_pin(gid, bot_id)
    if not expected:
        return False
    return hmac_new(_PIN_SALT, expected.encode(), sha256).hexdigest() == hmac_new(
        _PIN_SALT, pin.encode(), sha256
    ).hexdigest()

COMMAND_USAGE = {}

# Thread pool for sync_to_async offload (ffmpeg, mega, yt-dlp subprocess calls).
# Previously max_workers=1000 which reserved ~8GB of virtual memory for thread
# stacks and added scheduler overhead. min(32, cpu+4) is the Python 3.8+ default
# for concurrent.futures.ThreadPoolExecutor — tuned for I/O-bound work.
import os as _os
_THREAD_WORKERS = min(32, (_os.cpu_count() or 1) + 4)
THREAD_POOL = ThreadPoolExecutor(
    max_workers=_THREAD_WORKERS, thread_name_prefix="amaterasu-worker"
)


def _log_background_exception(task):
    try:
        exc = task.exception()
    except CancelledError:
        return
    except Exception as error:
        LOGGER.error(f"Failed to read background task result: {error}")
        return
    if exc:
        LOGGER.error(
            f"Background task failed: {task.get_name()}",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def create_tracked_task(coro):
    task = bot_loop.create_task(coro)
    task.add_done_callback(_log_background_exception)
    return task


class SetInterval:
    def __init__(self, interval, action, *args, **kwargs):
        self.interval = interval
        self.action = action
        self.task = bot_loop.create_task(self._set_interval(*args, **kwargs))

    async def _set_interval(self, *args, **kwargs):
        while True:
            await sleep(self.interval)
            await self.action(*args, **kwargs)

    def cancel(self):
        self.task.cancel()


def _build_command_usage(help_dict, command_key):
    buttons = ButtonMaker()
    cmd_list = list(help_dict.keys())[1:]
    cmd_pages = [cmd_list[i : i + 10] for i in range(0, len(cmd_list), 10)]
    temp_store = []

    for i, page in enumerate(cmd_pages):
        for name in page:
            buttons.data_button(name, f"help {command_key} {name} {i}")
        if len(cmd_pages) > 1:
            if i > 0:
                buttons.data_button("⫷", f"help pre {command_key} {i - 1}")
            if i < len(cmd_pages) - 1:
                buttons.data_button("⫸", f"help nex {command_key} {i + 1}")
        buttons.data_button("✕ CLOSE", "help close", "footer", style=ButtonStyle.DANGER)
        temp_store.append(buttons.build_menu(2))
        buttons.reset()

    COMMAND_USAGE[command_key] = [help_dict["main"], *temp_store]


def create_help_buttons():
    _build_command_usage(MIRROR_HELP_DICT, "mirror")
    _build_command_usage(YT_HELP_DICT, "yt")
    _build_command_usage(CLONE_HELP_DICT, "clone")


def compare_versions(v1, v2):
    def parse_version(version):
        if not version:
            return None
        try:
            return [
                int(part)
                for part in str(version).strip().split("-")[0].lstrip("vV").split(".")
            ]
        except ValueError:
            return None

    v1, v2 = (parse_version(version) for version in (v1, v2))
    if v1 is None or v2 is None:
        return "Latest version unavailable"
    return (
        "New Version Update is Available! Check Now!"
        if v1 < v2
        else (
            "More Updated! Kindly Contribute in Official"
            if v1 > v2
            else "Already up to date with latest version"
        )
    )


def bt_selection_buttons(id_):
    gid = id_[:12] if len(id_) > 25 else id_
    token = make_short_token(get_web_secret(), "torrent-select", id_)
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button(
            "Select Files",
            f"{Config.BASE_URL}/app/files?gid={id_}",
            style=ButtonStyle.PRIMARY,
        )
        buttons.data_button("Pincode", f"sel pin {gid} {token}")
    else:
        buttons.url_button(
            "Select Files",
            f"{Config.BASE_URL}/app/files?gid={id_}&pin={token}",
            style=ButtonStyle.PRIMARY,
        )
    buttons.data_button("Done Selecting", f"sel done {gid} {id_}")
    buttons.data_button("✕ CANCEL", f"sel cancel {gid}", style=ButtonStyle.DANGER)
    return buttons.build_menu(2)


async def get_telegraph_list(telegraph_content):
    path = [
        (
            await telegraph.create_page(
                title="Mirror-Leech-Bot Drive Search", content=content
            )
        )["path"]
        for content in telegraph_content
    ]
    if len(path) > 1:
        await telegraph.edit_telegraph(path, telegraph_content)
    buttons = ButtonMaker()
    buttons.url_button("🔎 VIEW", f"https://telegra.ph/{path[0]}")
    return buttons.build_menu(1)


def handleIndex(index, lst):
    if not lst:
        return 0
    return index % len(lst)


def arg_parser(items, arg_base):
    if not items:
        return

    arg_start = -1
    i = 0
    total = len(items)

    bool_arg_set = {
        "-b",
        "-e",
        "-z",
        "-s",
        "-j",
        "-d",
        "-sv",
        "-ss",
        "-f",
        "-fd",
        "-fu",
        "-sync",
        "-hl",
        "-doc",
        "-med",
        "-ut",
        "-bt",
        "-yt",
        "-yf",
        "-ytdlp-fallback",
        "-en",
        # Phase 4.1/4.3 — boolean flags using --word syntax
        "--stream",
        "--c2c",
    }
    if Config.DISABLE_BULK and "-b" in items:
        arg_base["-b"] = False

    if Config.DISABLE_MULTI and "-i" in items:
        arg_base["-i"] = 0

    if Config.DISABLE_SEED and "-d" in items:
        arg_base["-d"] = False

    while i < total:
        part = items[i]

        if part in arg_base:
            if arg_start == -1:
                arg_start = i

            if (
                i + 1 == total
                and part in bool_arg_set
                or part
                in [
                    "-s",
                    "-j",
                    "-f",
                    "-fd",
                    "-fu",
                    "-sync",
                    "-hl",
                    "-doc",
                    "-med",
                    "-ut",
                    "-bt",
                    "-yt",
                    "-yf",
                    "-ytdlp-fallback",
                ]
            ):
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(i + 1, total):
                    if items[j] in arg_base:
                        if (part == "-c" and items[j] == "-c") or (part == "-gc" and items[j] == "-gc"):
                            sub_list.append(items[j])
                            continue
                        if part in bool_arg_set and not sub_list:
                            arg_base[part] = True
                            break
                        if not sub_list:
                            break
                        check = " ".join(sub_list).strip()
                        if check.startswith("[") and check.endswith("]"):
                            break
                        elif not check.startswith("["):
                            break
                    sub_list.append(items[j])
                if sub_list:
                    value = " ".join(sub_list)
                    if part == "-ff" and not value.strip().startswith("["):
                        arg_base[part].add(value)
                    else:
                        arg_base[part] = value
                    i += len(sub_list)

        i += 1

    if "link" in arg_base:
        link_items = items[:arg_start] if arg_start != -1 else items
        if link_items:
            arg_base["link"] = " ".join(link_items)


def get_size_bytes(size):
    size = size.lower()
    if "k" in size:
        size = int(float(size.split("k")[0]) * 1024)
    elif "m" in size:
        size = int(float(size.split("m")[0]) * 1048576)
    elif "g" in size:
        size = int(float(size.split("g")[0]) * 1073741824)
    elif "t" in size:
        size = int(float(size.split("t")[0]) * 1099511627776)
    else:
        size = 0
    return size


def get_filename_from_headers(headers, url=""):
    content_disposition = headers.get("Content-Disposition", "")
    filename = ""
    for part in content_disposition.split(";"):
        key, sep, value = part.strip().partition("=")
        if not sep:
            continue
        key = key.lower()
        value = value.strip().strip("\"'")
        if key == "filename*":
            value = value.split("''", 1)[-1]
            filename = unquote(value)
            break
        if key == "filename" and not filename:
            filename = unquote(value)

    if not filename and url:
        filename = unquote(urlparse(url).path.rsplit("/", 1)[-1])

    filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return filename or ""


async def get_content_info(url):
    headers = {"User-Agent": DEFAULT_BROWSER_USER_AGENT}
    try:
        # TLS verification is ON by default. If you genuinely need to bypass
        # for an internal host with a self-signed cert, add the host to
        # Config.INSECURE_HOSTS (a list) and we'll disable verify only for
        # that host.
        from urllib.parse import urlparse as _urlparse

        parsed = _urlparse(url)
        insecure_hosts = getattr(Config, "INSECURE_HOSTS", None) or []
        verify = parsed.hostname not in insecure_hosts
        async with AsyncClient(
            verify=verify, follow_redirects=True, timeout=30.0
        ) as client:
            async with client.stream("GET", url, headers=headers) as response:
                return (
                    response.headers.get("Content-Type"),
                    get_filename_from_headers(response.headers, str(response.url)),
                )
    except Exception:
        return None, ""


async def get_content_type(url):
    content_type, _ = await get_content_info(url)
    return content_type


async def get_content_filename(url):
    _, filename = await get_content_info(url)
    return filename


def update_user_ldata(id_, key, value):
    user_data.setdefault(id_, {})
    user_data[id_][key] = value


def fetch_drive_cat(user_id, force=False):
    user_dict = user_data.get(user_id, {})
    if (Config.DRIVE_CATEGORY_MODE and user_dict.get("drive_cat_mode", False)) or force:
        return user_dict.get("DRIVE_CAT", {})
    return {}


async def cmd_exec(cmd, shell=False):
    if shell:
        proc = await create_subprocess_shell(cmd, stdout=PIPE, stderr=PIPE)
    else:
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await proc.communicate()
    try:
        stdout = stdout.decode().strip()
    except Exception:
        stdout = "Unable to decode the response!"
    try:
        stderr = stderr.decode().strip()
    except Exception:
        stderr = "Unable to decode the error!"
    return stdout, stderr, proc.returncode


def new_task(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return create_tracked_task(func(*args, **kwargs))

    return wrapper


async def sync_to_async(func, *args, wait=True, **kwargs):
    pfunc = partial(func, *args, **kwargs)
    future = bot_loop.run_in_executor(THREAD_POOL, pfunc)
    return await future if wait else future


def async_to_sync(func, *args, wait=True, **kwargs):
    future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
    return future.result() if wait else future


def loop_thread(func):
    @wraps(func)
    def wrapper(*args, wait=False, **kwargs):
        future = run_coroutine_threadsafe(func(*args, **kwargs), bot_loop)
        return future.result() if wait else future

    return wrapper


def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


async def download_image_url(url):
    path = "Images/"
    if not await aiopath.isdir(path):
        await mkdir(path)
    image_name = url.split("/")[-1].split("?")[0]
    des_dir = ospath.join(path, image_name)
    try:
        async with AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            resp = await client.get(url, timeout=15)
            if resp.status_code == 200:
                async with aiopen(des_dir, "wb") as f:
                    await f.write(resp.content)
                return des_dir
        LOGGER.error(f"Failed to download image from {url}: status {resp.status_code}")
    except Exception as e:
        LOGGER.error(f"Failed to download image from {url}: {e}")
    return None


async def _fetch_wallpaperflare(client, query, page, seen):
    base_url = "https://www.wallpaperflare.com/search"
    img_pattern = re_compile(r'data-src="(https://c4\.wallpaperflare\.com/wallpaper[^"]+)"')
    url = f"{base_url}?wallpaper={query}&width=1280&height=720&page={page}"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            return []
        return [m for m in img_pattern.findall(resp.text) if m not in seen]
    except Exception as e:
        LOGGER.warning(f"WallpaperFlare fetch failed [{query} p{page}]: {e}")
        return []


async def _fetch_peapix(client, country, seen):
    url = f"https://peapix.com/bing/feed?country={country}"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            LOGGER.warning(f"Peapix fetch failed: status {resp.status_code}")
            return []
        data = resp.json()
        return [item["fullUrl"] for item in data if "fullUrl" in item and item["fullUrl"] not in seen]
    except Exception as e:
        LOGGER.warning(f"Peapix fetch failed: {e}")
        return []


async def _fetch_wallhaven(client, query, page, seen):
    url = f"https://wallhaven.cc/api/v1/search?q={query}&categories=111&purity=100&sorting=relevance&page={page}"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15)
        if resp.status_code != 200:
            LOGGER.warning(f"Wallhaven fetch failed [{query} p{page}]: status {resp.status_code}")
            return []
        data = resp.json()
        return [item["path"] for item in data.get("data", []) if "path" in item and item["path"] not in seen]
    except Exception as e:
        LOGGER.warning(f"Wallhaven fetch failed [{query} p{page}]: {e}")
        return []


async def search_images():
    if not Config.USE_IMAGES:
        return

    LOGGER.info("IMG_SEARCH: Starting background image fetch...")
    sources = Config.IMG_SOURCES if isinstance(Config.IMG_SOURCES, list) else ["wallpaperflare"]
    query_list = []
    if Config.IMG_SEARCH:
        query_list = [
            q.strip().replace(" ", "+")
            for q in Config.IMG_SEARCH.replace("'", "").replace('"', "").split(",")
            if q.strip()
        ]

    if not query_list:
        if "peapix" not in sources:
            return

    total_pages = max(Config.IMG_PAGE or 1, 1)
    seen = set(Config.IMAGES) if isinstance(Config.IMAGES, list) else set()
    new_images = []

    try:
        async with AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            limits=Limits(max_connections=5),
        ) as client:
            if "wallpaperflare" in sources:
                for query in query_list:
                    for page in range(1, total_pages + 1):
                        results = await _fetch_wallpaperflare(client, query, page, seen)
                        for url in results:
                            if url not in seen:
                                seen.add(url)
                                new_images.append(url)

            if "peapix" in sources:
                results = await _fetch_peapix(client, "us", seen)
                for url in results:
                    if url not in seen:
                        seen.add(url)
                        new_images.append(url)

            if "wallhaven" in sources:
                for query in query_list:
                    for page in range(1, total_pages + 1):
                        results = await _fetch_wallhaven(client, query, page, seen)
                        for url in results:
                            if url not in seen:
                                seen.add(url)
                                new_images.append(url)
    except Exception as e:
        LOGGER.error(f"search_images error: {e}")
        return

    if new_images:
        if not isinstance(Config.IMAGES, list):
            Config.IMAGES = []
        Config.IMAGES.extend(new_images)
        Config.STATUS_LIMIT = 2
        LOGGER.info(f"IMG_SEARCH: fetched {len(new_images)} new images (total: {len(Config.IMAGES)})")
        if Config.DATABASE_URL:
            await database.update_config(
                {"IMAGES": Config.IMAGES, "STATUS_LIMIT": Config.STATUS_LIMIT}
            )


def _find_command_filters(flt):
    if hasattr(flt, "commands"):
        yield flt
    for attr in ("base", "other"):
        if child := getattr(flt, attr, None):
            yield from _find_command_filters(child)


def _build_command_map():
    from ...core.tg_client import TgClient

    mapping = {}
    for group in TgClient.bot.dispatcher.groups.values():
        for handler in group:
            if not isinstance(handler, MessageHandler):
                continue
            if handler.filters is None:
                continue
            for cmd_filter in _find_command_filters(handler.filters):
                for cmd in cmd_filter.commands:
                    mapping[cmd] = handler.callback
    return mapping


def resolve_command(command_str):
    cmd_name = command_str.strip().lstrip("/").split(maxsplit=1)[0]
    mapping = _build_command_map()
    handler = mapping.get(cmd_name)
    suffix = str(Config.CMD_SUFFIX or "")
    if handler is None and suffix:
        handler = mapping.get(f"{cmd_name}{suffix}")
    if handler is None:
        LOGGER.warning(f"Unknown command '{cmd_name}' (from '{command_str}')")
    return handler
