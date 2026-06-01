from asyncio import (
    create_subprocess_exec,
    create_subprocess_shell,
    run_coroutine_threadsafe,
    sleep,
)
from pyrogram.enums import ButtonStyle
from asyncio.subprocess import PIPE
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from urllib.parse import unquote, urlparse

from httpx import AsyncClient

from ... import bot_loop, user_data
from ...core.config_manager import Config
from ..telegram_helper.button_build import ButtonMaker
from web.security import make_short_token
from .help_messages import (
    CLONE_HELP_DICT,
    MIRROR_HELP_DICT,
    YT_HELP_DICT,
)
from .telegraph_helper import telegraph

COMMAND_USAGE = {}

THREAD_POOL = ThreadPoolExecutor(max_workers=500)
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


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
    v1, v2 = (list(map(int, v.split("-")[0].lstrip("v").split("."))) for v in (v1, v2))
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
    pin = make_short_token(Config.BOT_TOKEN, "torrent-select", id_)
    buttons = ButtonMaker()
    if Config.WEB_PINCODE:
        buttons.url_button("Select Files", f"{Config.BASE_URL}/app/files?gid={id_}", style=ButtonStyle.PRIMARY)
        buttons.data_button("Pincode", f"sel pin {gid} {pin}")
    else:
        buttons.url_button(
            "Select Files", f"{Config.BASE_URL}/app/files?gid={id_}&pin={pin}",
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
        "-en",
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
                ]
            ):
                arg_base[part] = True
            else:
                sub_list = []
                for j in range(i + 1, total):
                    if items[j] in arg_base:
                        if part == "-c" and items[j] == "-c":
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
        async with AsyncClient(verify=False, follow_redirects=True) as client:
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
        task = bot_loop.create_task(func(*args, **kwargs))
        return task

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
