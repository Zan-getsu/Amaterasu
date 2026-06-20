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
from pathlib import Path
from shutil import rmtree
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi
from subprocess import run as srun, PIPE
from sys import exit
from re import compile as re_compile

getLogger("pymongo").setLevel(ERROR)

_LOGGER = getLogger("update")

def as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _load_db_partition_salt():
    """Load the DB partition salt WITHOUT triggering bot/__init__.py.

    update.py runs as the very first thing in start.sh, before the bot
    is booted. Importing bot.helper.ext_utils.secrets via the normal
    import chain triggers bot/__init__.py which installs uvloop, creates
    an event loop, imports Config, etc. — heavy and may fail if deps
    aren't installed yet. We load the secrets module directly via
    importlib instead, which only triggers stdlib imports.
    """
    # Env var takes priority
    env_val = environ.get("AMATERASU_DB_PARTITION_SALT")
    if env_val and env_val.strip():
        try:
            return bytes.fromhex(env_val.strip())
        except ValueError:
            return env_val.strip().encode("utf-8")
    # Read from .amaterasu_secrets file if it exists
    secrets_file = Path(".amaterasu_secrets")
    if secrets_file.exists():
        try:
            for line in secrets_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("DB_PARTITION_SALT="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        try:
                            return bytes.fromhex(val)
                        except ValueError:
                            return val.encode("utf-8")
        except OSError:
            pass
    # Legacy fallback (preserves existing deployments' partition names)
    return b"wzmlx_v3_db_partition_salt"


_DB_PARTITION_SALT = _load_db_partition_salt()

# Default allowlist — operators can override via UPSTREAM_ALLOWLIST env var
# or config.py to add their own fork URL. Comma-separated regex patterns.
_DEFAULT_UPSTREAM_PATTERNS = (
    r"^https://github\.com/[\w.-]+/[\w.-]+/?$",
    r"^https://raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/?$",
    r"^https://git\.nbmirror\.qzz\.io/[\w.-]+/[\w.-]+/?$",
)


def _load_upstream_allowlist():
    """Load the UPSTREAM_ALLOWLIST from env or config.py.

    Returns a list of compiled regex patterns. Priority:
      1. UPSTREAM_ALLOWLIST env var (comma-separated regex patterns)
      2. config.py UPSTREAM_ALLOWLIST (comma-separated regex patterns)
      3. Default 3 patterns (github.com, raw.githubusercontent.com, git.nbmirror.qzz.io)

    This allows operators to add their own fork URL for auto-update
    without modifying the source code.
    """
    from re import compile as _re_compile

    # Try env var first
    raw = environ.get("UPSTREAM_ALLOWLIST", "").strip()
    if not raw:
        # Try config.py
        try:
            settings = import_module("config")
            raw = getattr(settings, "UPSTREAM_ALLOWLIST", "").strip()
        except (ModuleNotFoundError, AttributeError):
            raw = ""

    if raw:
        # Operator provided custom allowlist. Split on comma, strip each
        # pattern, compile each as a regex. Skip empty patterns.
        patterns = [p.strip() for p in raw.split(",") if p.strip()]
        if patterns:
            compiled = []
            for p in patterns:
                try:
                    compiled.append(_re_compile(p))
                except Exception as e:
                    _LOGGER.warning(
                        f"UPSTREAM_ALLOWLIST pattern '{p}' is invalid regex "
                        f"and will be skipped: {e}"
                    )
            if compiled:
                return compiled
            _LOGGER.warning(
                "UPSTREAM_ALLOWLIST set but no valid patterns parsed; "
                "falling back to default allowlist."
            )

    # Default — compile the 3 standard patterns
    return [_re_compile(p) for p in _DEFAULT_UPSTREAM_PATTERNS]


_ALLOWLIST_PATTERNS = _load_upstream_allowlist()
_BRANCH_RE = re_compile(r"^[\w./-]+$")

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
        db = conn.amaterasu
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
            config_file[key] = value
        _LOGGER.info("Config imported from MongoDB")
    else:
        _LOGGER.warning("No saved config found in MongoDB, using defaults")


def _run_update(upstream_repo, upstream_branch, version):
    if not upstream_repo:
        _LOGGER.info("No UPSTREAM_REPO set, skipping git update")
        return

    # Check against the configurable allowlist (Phase 0.2). Operators can
    # add their own fork URL via UPSTREAM_ALLOWLIST env var or config.py.
    allowed = any(p.match(upstream_repo) for p in _ALLOWLIST_PATTERNS)
    if not allowed:
        _LOGGER.error(
            "UPSTREAM_REPO rejected (not in UPSTREAM_ALLOWLIST): "
            f"{upstream_repo}\n"
            "To allow this URL, set UPSTREAM_ALLOWLIST in your env or "
            "config.py as a comma-separated list of regex patterns. "
            "Example: UPSTREAM_ALLOWLIST=\"^https://github\\.com/yourname/Amaterasu/?$\""
        )
        exit(1)

    if path.exists(".git"):
        rmtree(".git", ignore_errors=True)

    commands = [
        ["git", "init", "-q"],
        ["git", "config", "--global", "user.email", "AmaterasuBot@users.noreply.github.com"],
        ["git", "config", "--global", "user.name", "Amaterasu"],
        ["git", "add", "."],
        ["git", "commit", "-sm", "update", "-q"],
        ["git", "remote", "add", "origin", upstream_repo],
        ["git", "fetch", "origin", "-q"],
        ["git", "reset", "--hard", f"origin/{upstream_branch}", "-q"],
    ]
    update_code = 0
    for command in commands:
        update = srun(command, stdout=PIPE, stderr=PIPE, text=True)
        update_code = update.returncode
        if update_code != 0:
            _LOGGER.error(f"Command '{' '.join(command)}' failed with error:\n{update.stderr}")
            break

    display_repo = "/".join(upstream_repo.split("/")[-2:])
    if update_code == 0:
        _LOGGER.info("Successfully updated with Latest Updates !")
    else:
        _LOGGER.error("Something went Wrong! Recheck your details or Ask Support!")
    _LOGGER.info(f"UPSTREAM_REPO: {display_repo} | UPSTREAM_BRANCH: {upstream_branch} | VERSION: {version}")

def _update_packages(update_pkgs):
    if as_bool(update_pkgs):
        _LOGGER.info("Updating Packages...")
        pkg_update = srun(["uv", "pip", "install", "--system", "-U", "-r", "requirements.txt"], stdout=PIPE, stderr=PIPE, text=True)
        if pkg_update.returncode == 0:
            _LOGGER.info("Successfully Updated all the Packages !")
        else:
            _LOGGER.error(f"Failed to update packages: {pkg_update.stderr}")


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

    # Re-apply env vars AFTER MongoDB fetch so they always win.
    # This allows operators to override MongoDB-stored config via
    # docker run -e KEY=VALUE without editing MongoDB.
    env_overrides = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in environ.items()
        if key in _VAR_LIST
    }
    if env_overrides:
        config_file.update(env_overrides)
        _LOGGER.info("Config env vars re-applied over MongoDB (operator override)")

    upstream_repo = config_file.get("UPSTREAM_REPO", "").strip()
    upstream_branch = config_file.get("UPSTREAM_BRANCH", "").strip() or "main"

    _run_update(upstream_repo, upstream_branch, version)

    update_pkgs = config_file.get("UPDATE_PKGS", "True")
    _update_packages(update_pkgs)


if __name__ == "__main__":
    main()
