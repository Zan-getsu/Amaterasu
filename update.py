from asyncio import run
from hashlib import sha256
from importlib import import_module
from logging import (
    FileHandler,
    StreamHandler,
    INFO,
    basicConfig,
    getLogger,
    ERROR,
)
from os import path, remove, environ
<<<<<<< HEAD
from shutil import rmtree
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from re import compile as re_compile
from subprocess import run as srun, call as scall, PIPE

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
=======
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi
from subprocess import run as srun, call as scall
from sys import exit

getLogger("pymongo").setLevel(ERROR)

_LOGGER = getLogger("update")
>>>>>>> 8af04aa (feat: add Mega upload/clone support, Drive Categories, and infrastructure improvements)

_DB_PARTITION_SALT = b"wzmlx_v3_db_partition_salt"
_VAR_LIST = [
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

def _get_version():
    try:
        version = import_module("bot.version")
        return version.get_version()
    except Exception:
        return "unknown"


def _setup_logging():
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


def _load_config():
    try:
        settings = import_module("config")
        config_file = {
            key: value.strip() if isinstance(value, str) else value
            for key, value in vars(settings).items()
            if not key.startswith("__")
        }
    except ModuleNotFoundError:
        _LOGGER.info("Config.py file is not Added! Checking ENVs..")
        config_file = {}

    env_updates = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in environ.items()
        if key in _VAR_LIST
    }
    if env_updates:
        _LOGGER.info("Config data is updated with ENVs!")
        config_file.update(env_updates)
    return config_file


def _db_partition_id(bot_id):
    raw = sha256(_DB_PARTITION_SALT + str(bot_id).encode("utf-8")).hexdigest()
    return f"p_{raw[:24]}"


async def _fetch_db_config(database_url, db_part):
    conn = AsyncMongoClient(database_url, server_api=ServerApi("1"))
    try:
<<<<<<< HEAD
        conn = MongoClient(DATABASE_URL, server_api=ServerApi("1"))
        db = conn.amaterasu
        old_config = db.settings.deployConfig.find_one({"_id": _DB_PART}, {"_id": 0})
        config_dict = db.settings.config.find_one({"_id": _DB_PART})
        if old_config is None:
            old_config = db.settings.deployConfig.find_one(
                {"_id": BOT_ID}, {"_id": 0}
            )
        if config_dict is None:
            config_dict = db.settings.config.find_one({"_id": BOT_ID})
        if (
            old_config is not None and old_config == config_file or old_config is None
        ) and config_dict is not None:
            config_file["UPSTREAM_REPO"] = config_dict.get(
                "UPSTREAM_REPO", config_file.get("UPSTREAM_REPO", "")
            )
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
=======
        db = conn.wzmlx
        return await db.settings.config.find_one({"_id": db_part}, {"_id": 0})
    except PyMongoError as e:
        _LOGGER.error(f"Database ERROR: {e}")
        return None
    finally:
        await conn.close()


def _fetch_config_from_db(config_file, db_part):
    database_url = config_file.get("DATABASE_URL", "").strip()
    if not database_url:
        return
    db_config = run(_fetch_db_config(database_url, db_part))
    if db_config is not None:
        for key, value in db_config.items():
            if key not in config_file or config_file[key] is None:
                config_file[key] = value
        _LOGGER.info("Config imported from MongoDB")
    else:
        _LOGGER.warning("No saved config found in MongoDB, using defaults")
>>>>>>> 8af04aa (feat: add Mega upload/clone support, Drive Categories, and infrastructure improvements)


def _run_update(upstream_repo, upstream_branch, version):
    if not upstream_repo:
        _LOGGER.info("No UPSTREAM_REPO set, skipping git update")
        return

    if path.exists(".git"):
        rmtree(".git", ignore_errors=True)

<<<<<<< HEAD
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
        update = srun(command, stdout=PIPE, stderr=PIPE, text=True)
        update_code = update.returncode
        if update_code != 0:
            log_error(f"Command '{' '.join(command)}' failed with error:\n{update.stderr}")
            break

    if update_code == 0:
        log_info("Successfully updated with Latest Updates !")
=======
    result = srun(
        [
            "bash",
            "-c",
            f"git init -q"
            f" && git config --global user.email 105407900+SilentDemonSD@users.noreply.github.com"
            f" && git config --global user.name SilentDemonSD"
            f" && git add ."
            f" && git commit -sm update -q"
            f" && git remote add origin {upstream_repo}"
            f" && git fetch origin -q"
            f" && git reset --hard origin/{upstream_branch} -q",
        ],
    )

    display_repo = "/".join(upstream_repo.split("/")[-2:])
    if result.returncode == 0:
        _LOGGER.info("Successfully updated with Latest Updates!")
>>>>>>> 8af04aa (feat: add Mega upload/clone support, Drive Categories, and infrastructure improvements)
    else:
        _LOGGER.error("Something went Wrong! Recheck your details or Ask Support!")
    _LOGGER.info(f"UPSTREAM_REPO: {display_repo} | UPSTREAM_BRANCH: {upstream_branch} | VERSION: {version}")


<<<<<<< HEAD
UPDATE_PKGS = config_file.get("UPDATE_PKGS", "True")
if as_bool(UPDATE_PKGS):
    log_info("Updating Packages...")
    pkg_update = srun(["uv", "pip", "install", "--system", "-U", "-r", "requirements.txt"], stdout=PIPE, stderr=PIPE, text=True)
    if pkg_update.returncode == 0:
        log_info("Successfully Updated all the Packages !")
    else:
        log_error(f"Failed to update packages: {pkg_update.stderr}")
=======
def _update_packages(update_pkgs):
    if (isinstance(update_pkgs, str) and update_pkgs.lower() == "true") or update_pkgs:
        scall("uv pip install -U -r requirements.txt", shell=True)
        _LOGGER.info("Successfully Updated all the Packages!")


def main():
    _setup_logging()
    config_file = _load_config()
    version = _get_version()

    bot_token = config_file.get("BOT_TOKEN", "")
    if not bot_token:
        _LOGGER.error("BOT_TOKEN variable is missing! Exiting now")
        exit(1)

    bot_id = bot_token.split(":", 1)[0]
    db_part = _db_partition_id(bot_id)

    _fetch_config_from_db(config_file, db_part)

    upstream_repo = config_file.get("UPSTREAM_REPO", "").strip()
    upstream_branch = config_file.get("UPSTREAM_BRANCH", "").strip() or "wzv3"

    _run_update(upstream_repo, upstream_branch, version)

    update_pkgs = config_file.get("UPDATE_PKGS", "True")
    _update_packages(update_pkgs)


if __name__ == "__main__":
    main()
>>>>>>> 8af04aa (feat: add Mega upload/clone support, Drive Categories, and infrastructure improvements)
