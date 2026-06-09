from sys import exit
from hashlib import sha256
from importlib import import_module
from logging import (
    FileHandler,
    StreamHandler,
    INFO,
    basicConfig,
    error as log_error,
    info as log_info,
    getLogger,
    ERROR,
)
from os import path, remove, environ
from shutil import rmtree
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from re import compile as re_compile
from subprocess import run as srun, call as scall

getLogger("pymongo").setLevel(ERROR)


def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)

_DB_PARTITION_SALT = b"wzmlx_v3_db_partition_salt"
_ALLOWED_UPSTREAM = re_compile(
    r"^https://("
    r"github\.com/[\w.-]+/[\w.-]+/?|"
    r"raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/?|"
    r"git\.nbmirror\.qzz\.io/[\w.-]+/[\w.-]+/?"
    r")$"
)
_BRANCH_RE = re_compile(r"^[\w./-]+$")

var_list = [
    "BOT_TOKEN",
    "TELEGRAM_API",
    "TELEGRAM_HASH",
    "OWNER_ID",
    "DATABASE_URL",
    "BASE_URL",
    "UPSTREAM_REPO",
    "UPSTREAM_BRANCH",
    "UPDATE_PKGS",
]

if path.exists("log.txt"):
    with open("log.txt", "r+") as f:
        f.truncate(0)

if path.exists("rlog.txt"):
    remove("rlog.txt")

basicConfig(
    format="[%(asctime)s] [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[FileHandler("log.txt"), StreamHandler()],
    level=INFO,
)
try:
    settings = import_module("config")
    config_file = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in vars(settings).items()
        if not key.startswith("__")
    }
except ModuleNotFoundError:
    log_info("Config.py file is not Added! Checking ENVs..")
    config_file = {}

env_updates = {
    key: value.strip() if isinstance(value, str) else value
    for key, value in environ.items()
    if key in var_list
}
if env_updates:
    log_info("Config data is updated with ENVs!")
    config_file.update(env_updates)

BOT_TOKEN = config_file.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    log_error("BOT_TOKEN variable is missing! Exiting now")
    exit(1)

BOT_ID = BOT_TOKEN.split(":", 1)[0]
_DB_PART = "p_" + sha256(_DB_PARTITION_SALT + str(BOT_ID).encode("utf-8")).hexdigest()[:24]

if DATABASE_URL := config_file.get("DATABASE_URL", "").strip():
    try:
        conn = MongoClient(DATABASE_URL, server_api=ServerApi("1"))
        db = conn.amaterasu
        old_config = db.settings.deployConfig.find_one({"_id": BOT_ID}, {"_id": 0})
        config_dict = db.settings.config.find_one({"_id": BOT_ID})
        if (
            old_config is not None and old_config == config_file or old_config is None
        ) and config_dict is not None:
            config_file["UPSTREAM_REPO"] = config_dict["UPSTREAM_REPO"]
            config_file["UPSTREAM_BRANCH"] = config_dict.get("UPSTREAM_BRANCH", "main")
            config_file["UPDATE_PKGS"] = config_dict.get("UPDATE_PKGS", "True")
        conn.close()
    except Exception as e:
        log_error(f"Database ERROR: {e}")

UPSTREAM_REPO = config_file.get("UPSTREAM_REPO", "").strip() or "https://github.com/its-niloy/Amaterasu"
UPSTREAM_BRANCH = config_file.get("UPSTREAM_BRANCH", "").strip() or "main"

if UPSTREAM_REPO and not _ALLOWED_UPSTREAM.match(UPSTREAM_REPO):
    log_error(
        "UPSTREAM_REPO rejected (must be github.com, raw.githubusercontent.com, "
        f"or git.nbmirror.qzz.io): {UPSTREAM_REPO}"
    )
    exit(1)

if not _BRANCH_RE.match(UPSTREAM_BRANCH):
    log_error(f"UPSTREAM_BRANCH rejected (invalid characters): {UPSTREAM_BRANCH}")
    exit(1)

if UPSTREAM_REPO:
    if path.exists(".git"):
        rmtree(".git", ignore_errors=True)

    commands = [
        ["git", "init", "-q"],
        ["git", "config", "--global", "user.email", "AmaterasuBot@users.noreply.github.com"],
        ["git", "config", "--global", "user.name", "Amaterasu"],
        ["git", "add", "."],
        ["git", "commit", "-sm", "update", "-q"],
        ["git", "remote", "add", "origin", UPSTREAM_REPO],
        ["git", "fetch", "origin", "-q"],
        ["git", "reset", "--hard", f"origin/{UPSTREAM_BRANCH}", "-q"],
    ]
    update_code = 0
    for command in commands:
        update = srun(command)
        update_code = update.returncode
        if update_code != 0:
            break

    if update_code == 0:
        log_info("Successfully updated with Latest Updates !")
    else:
        log_error("Something went Wrong ! Recheck your details or Ask Support !")
    log_info(f"UPSTREAM_REPO: {UPSTREAM_REPO} | UPSTREAM_BRANCH: {UPSTREAM_BRANCH}")


UPDATE_PKGS = config_file.get("UPDATE_PKGS", "True")
if as_bool(UPDATE_PKGS):
    scall(["uv", "pip", "install", "--system", "-U", "-r", "requirements.txt"])
    log_info("Successfully Updated all the Packages !")
