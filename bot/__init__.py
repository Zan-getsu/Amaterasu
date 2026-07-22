# ruff: noqa: E402

import sys

if sys.platform != "win32":
    from uvloop import install

    install()
else:
    import asyncio

    if not hasattr(asyncio, "uvloop"):
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

from asyncio import new_event_loop, set_event_loop

bot_loop = new_event_loop()
set_event_loop(bot_loop)

from asyncio import Lock
from logging import (
    CRITICAL,
    ERROR,
    Filter,
    INFO,
    WARNING,
    StreamHandler,
    basicConfig,
    getLogger,
    Formatter,
)
from logging.handlers import RotatingFileHandler
from json import dumps as json_dumps
from os import cpu_count
from time import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .core.config_manager import Config
from sabnzbdapi import SabnzbdClient

getLogger("niquests").setLevel(WARNING)
getLogger("pyrogram").setLevel(ERROR)
getLogger("pyrogram.methods.advanced.save_file").setLevel(CRITICAL)
getLogger("apscheduler").setLevel(ERROR)
getLogger("pymongo").setLevel(WARNING)
getLogger("aiohttp").setLevel(WARNING)


bot_start_time = time()


class _NonEmptyErrorFilter(Filter):
    def filter(self, record):
        if record.levelno >= ERROR and not record.getMessage().strip():
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                record.msg = f"{record.name}: {type(exc).__name__}: {exc!r}"
            elif record.msg:
                record.msg = f"{record.name}: {type(record.msg).__name__}: {record.msg!r}"
            else:
                record.msg = f"{record.name}: empty error log"
            record.args = ()
        return True


class _JsonFormatter(Formatter):
    """Phase 6.4 — JSON log formatter for structured logging.

    Outputs each log record as a JSON line: {"ts": "...", "level":
    "...", "logger": "...", "msg": "..."}. Easier for log aggregation
    tools (ELK, Loki, Datadog) to parse than the default text format.
    """

    def format(self, record):
        log_entry = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            log_entry["exception"] = f"{type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        return json_dumps(log_entry, ensure_ascii=False)


# Phase 6.4 — choose formatter based on Config.LOG_FORMAT
_log_format = getattr(Config, "LOG_FORMAT", "text").lower()
if _log_format == "json":
    _log_formatter = _JsonFormatter(datefmt="%d-%b-%y %I:%M:%S %p")
else:
    _log_formatter = Formatter(
        fmt="[%(asctime)s] [%(levelname)s] - %(message)s",
        datefmt="%d-%b-%y %I:%M:%S %p",
    )

basicConfig(
    handlers=[
        RotatingFileHandler(
            "log.txt", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        ),
        StreamHandler(),
    ],
    level=INFO,
)
# Apply the chosen formatter to both handlers
for _handler in getLogger().handlers:
    _handler.setFormatter(_log_formatter)
    _handler.addFilter(_NonEmptyErrorFilter())

LOGGER = getLogger(__name__)
try:
    # Docker may expose a CPU count that includes CPUs outside this
    # container's affinity mask. taskset must only receive allowed CPU IDs.
    from os import sched_getaffinity

    cpu_ids = sorted(sched_getaffinity(0))
except (ImportError, AttributeError, OSError):
    cpu_ids = list(range(cpu_count() or 1))

cpu_no = len(cpu_ids) or 1
threads = max(1, cpu_no // 2)
cores = ",".join(str(cpu) for cpu in cpu_ids[:threads])

if cpu_no <= 1 or cpu_no == 2:
    service_cores = ""
else:
    service_cores = ",".join(str(cpu) for cpu in cpu_ids[threads:])

bot_cache = {}
DOWNLOAD_DIR = "/usr/src/app/downloads/"
intervals = {"status": {}, "qb": "", "jd": "", "nzb": "", "stopAll": False}
qb_torrents = {}
jd_downloads = {}
nzb_jobs = {}
user_data = {}
aria2_options = {}
qbit_options = {}
nzb_options = {}
queued_dl = {}
queued_up = {}
status_dict = {}
task_dict = {}
rss_dict = {}
shortener_dict = {}
categories_dict = {}
list_drives_dict = {}
var_list = [
    "BOT_TOKEN",
    "TELEGRAM_API",
    "TELEGRAM_HASH",
    "OWNER_ID",
    "DATABASE_URL",
    "BASE_URL",
    "PORT",
    "CLOUDFLARE_TUNNEL_ENABLED",
    "CLOUDFLARE_TUNNEL_TOKEN",
    "CLOUDFLARE_TUNNEL_TARGET",
    "CLOUDFLARE_TUNNEL_METRICS",
    "CLOUDFLARE_TUNNEL_AUTO_URL",
    "CLOUDFLARE_TUNNEL_AUTO_FQDN",
    "UPSTREAM_REPO",
    "UPSTREAM_BRANCH",
    "UPDATE_PKGS",
]
auth_chats = {}
excluded_extensions = ["aria2", "!qB"]
drives_names = []
drives_ids = []
index_urls = []
sudo_users = []
non_queued_dl = set()
non_queued_up = set()
multi_tags = set()
task_dict_lock = Lock()
queue_dict_lock = Lock()
qb_listener_lock = Lock()
nzb_listener_lock = Lock()
jd_listener_lock = Lock()
same_directory_lock = Lock()

def _sabnzbd_key():
    from bot.helper.ext_utils.bot_utils import derive_service_password

    return derive_service_password(
        (Config.BOT_TOKEN or "").split(":", 1)[0] or "0",
        "sabnzbd",
    )


def _update_sabnzbd_ini(api_key):
    """Patch SABnzbd.ini with its derived credentials and API URL base.

    Returns True on success (or no-op when already patched), False on
    failure. Caller should refuse to start SABnzbd if this returns
    False — otherwise the service runs with a default or placeholder
    credential.

    Phase 0.3: When Config.SKIP_SABNZBD_INI_CHECK is True, the patcher
    logs a WARNING and returns True even if it cannot replace known-bad
    markers. This is an escape hatch for operators who manage SABnzbd.ini
    manually or migrate from a custom config. The default (False) keeps
    the strict safety behavior — refuse to start on default creds.
    """
    from re import compile as _re, MULTILINE

    # Phase 0.3 — bypass check. Read Config lazily to avoid import cycle.
    skip_check = getattr(Config, "SKIP_SABNZBD_INI_CHECK", False)
    if skip_check:
        LOGGER.warning(
            "SKIP_SABNZBD_INI_CHECK is set; skipping SABnzbd.ini validation. "
            "SABnzbd will start with whatever credentials are in the ini file. "
            "Only use this if you manage SABnzbd.ini manually."
        )
        # Still attempt the substitution best-effort, but never fail.
        try:
            with open("configs/sabnzbd/SABnzbd.ini", "r+") as f:
                content = f.read()
                pat_key = _re(r"^api_key\s*=.*$", MULTILINE)
                pat_pwd = _re(r'^password\s*=.*$', MULTILINE)
                pat_url_base = _re(r"^url_base\s*=.*$", MULTILINE)
                new = pat_key.sub(f"api_key = {api_key}", content)
                new = pat_pwd.sub(f"password = {api_key}", new)
                new = pat_url_base.sub("url_base = /sabnzbd", new)
                if new != content:
                    f.seek(0)
                    f.truncate()
                    f.write(new)
                    LOGGER.info("SABnzbd.ini updated (skip-check mode)")
        except Exception as e:
            LOGGER.warning(f"SABnzbd.ini update skipped (skip-check mode): {e}")
        return True

    pat_key = _re(r"^api_key\s*=.*$", MULTILINE)
    pat_pwd = _re(r'^password\s*=.*$', MULTILINE)
    pat_url_base = _re(r"^url_base\s*=.*$", MULTILINE)
    # Known-bad credentials that must NEVER be left in the ini at boot:
    _BAD_MARKERS = ("sabpassword", "REPLACED_AT_BOOT_BY_AMATERASU", "CHANGEME")
    try:
        with open("configs/sabnzbd/SABnzbd.ini", "r+") as f:
            content = f.read()
            new = content
            new = pat_key.sub(f"api_key = {api_key}", new)
            new = pat_pwd.sub(f"password = {api_key}", new)
            # sabnzbdapi always uses /sabnzbd/api. Older MongoDB-backed
            # configuration can retain an empty url_base and redirect that
            # endpoint to HTML instead of returning JSON.
            new = pat_url_base.sub("url_base = /sabnzbd", new)
            if new == content:
                # No substitution happened. Either (a) the file was
                # already patched with this exact key (idempotent — OK),
                # or (b) the regex didn't match and we're about to ship
                # a default/placeholder credential. Distinguish by
                # checking for known-bad markers.
                for marker in _BAD_MARKERS:
                    if marker in content:
                        LOGGER.error(
                            f"SABnzbd.ini still contains the marker '{marker}' "
                            "but the regex pattern didn't match — refusing to "
                            "start SABnzbd. Delete configs/sabnzbd/SABnzbd.ini "
                            "and redeploy to regenerate from the template, or "
                            "set SKIP_SABNZBD_INI_CHECK=True to bypass (not "
                            "recommended)."
                        )
                        return False
                return True
            f.seek(0)
            f.truncate()
            f.write(new)
            LOGGER.info("SABnzbd.ini Updated with derived api_key")
            return True
    except FileNotFoundError:
        LOGGER.error(
            "configs/sabnzbd/SABnzbd.ini not found. Refusing to start SABnzbd "
            "with default credentials. Restore the file from the repo, or set "
            "SKIP_SABNZBD_INI_CHECK=True to bypass (not recommended)."
        )
        return False
    except Exception as e:
        LOGGER.error(
            f"SABnzbd.ini patch failed: {e}. Refusing to start SABnzbd with "
            "potentially default credentials. Set SKIP_SABNZBD_INI_CHECK=True "
            "to bypass (not recommended)."
        )
        return False


if not Config.WEB_ACCESS_PASSWORD:
    from secrets import token_hex
    Config.WEB_ACCESS_PASSWORD = token_hex(32)

_sabnzbd_api_key = _sabnzbd_key()

sabnzbd_client = SabnzbdClient(
    host="http://localhost",
    api_key=_sabnzbd_api_key,
    port="8070",
)

scheduler = AsyncIOScheduler(event_loop=bot_loop)
