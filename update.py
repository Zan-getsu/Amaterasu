from asyncio import run
from hashlib import sha256
from importlib import import_module
from logging import (
    ERROR,
    INFO,
    FileHandler,
    StreamHandler,
    basicConfig,
    getLogger,
)
from os import environ, path, remove
from pathlib import Path
from re import compile as re_compile
from subprocess import run as srun
from sys import exit

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError
from pymongo.server_api import ServerApi

from git_runtime import git_command

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
    r"^https://git\.nbmirror\.qzz\.io(?:/[\w.-]+/[\w.-]+)?/?$",
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
    "AUTO_UPDATE",
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


async def _fetch_db_config(database_url, db_part, collection="config"):
    conn = AsyncMongoClient(database_url, server_api=ServerApi("1"))
    try:
        db = conn.amaterasu
        return await db.settings[collection].find_one({"_id": db_part}, {"_id": 0})
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
    if db_config is None:
        _LOGGER.warning("No saved config found in MongoDB, using defaults")
        return

    old_config = run(_fetch_db_config(database_url, db_part, collection="deployConfig"))
    env_keys = {k: config_file[k] for k in _VAR_LIST if k in environ}

    if old_config is not None and old_config != config_file:
        merged = dict(config_file)
        for k, v in db_config.items():
            if k in old_config and config_file.get(k) is not None:
                if old_config.get(k) == config_file.get(k):
                    merged[k] = v
            elif k not in merged or merged[k] is None:
                merged[k] = v
        config_file.clear()
        config_file.update(merged)
        _LOGGER.info("Config: config.py changed, takes priority over MongoDB")
    else:
        merged = dict(config_file)
        if db_config:
            merged.update(db_config)
        config_file.clear()
        config_file.update(merged)
        _LOGGER.info(
            "Config imported from MongoDB"
            if old_config is not None
            else "Config: first deploy, config.py fills gaps from MongoDB"
        )
    config_file.update(env_keys)


def _run_git(*args):
    """Run Git as the working directory's numeric owner."""
    return srun(git_command(*args), capture_output=True, text=True)


def _git_error(action, result):
    detail = (result.stderr or result.stdout or "unknown Git error").strip()
    _LOGGER.error("Auto-update could not %s: %s", action, detail)


def _working_tree_changes():
    status = _run_git("status", "--porcelain=v1", "--untracked-files=normal")
    if status.returncode != 0:
        _git_error("inspect the working tree", status)
        return None
    return status.stdout.strip()


def _run_update(upstream_repo, upstream_branch, version):
    if not upstream_repo:
        _LOGGER.info("No UPSTREAM_REPO set, skipping git update")
        return False

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
        return False

    if not _BRANCH_RE.fullmatch(upstream_branch) or any(
        marker in upstream_branch for marker in ("..", "//", "@{")
    ):
        _LOGGER.error("Invalid UPSTREAM_BRANCH %r; auto-update skipped", upstream_branch)
        return False

    repository = _run_git("rev-parse", "--is-inside-work-tree")
    if repository.returncode != 0 or repository.stdout.strip() != "true":
        _LOGGER.warning(
            "AUTO_UPDATE=true, but the application directory is not a Git working tree; "
            "leaving application files unchanged"
        )
        return False

    current_branch = _run_git("symbolic-ref", "--quiet", "--short", "HEAD")
    if current_branch.returncode != 0:
        _LOGGER.warning("Auto-update skipped because Git HEAD is detached")
        return False
    if current_branch.stdout.strip() != upstream_branch:
        _LOGGER.warning(
            "Auto-update skipped: current branch is %s, configured branch is %s",
            current_branch.stdout.strip(),
            upstream_branch,
        )
        return False

    changes = _working_tree_changes()
    if changes is None:
        return False
    if changes:
        _LOGGER.warning(
            "Auto-update skipped: the Git working tree has local changes. "
            "Commit, stash, or discard them explicitly before updating.\n%s",
            changes,
        )
        return False

    update_ref = f"refs/remotes/amaterasu-update/{upstream_branch}"
    fetch = _run_git(
        "fetch",
        "--quiet",
        "--no-tags",
        upstream_repo,
        f"+refs/heads/{upstream_branch}:{update_ref}",
    )
    if fetch.returncode != 0:
        _git_error("fetch the configured upstream", fetch)
        return False

    # A file can change while the network fetch is in progress. Protect that
    # race by checking the tree again immediately before applying anything.
    changes = _working_tree_changes()
    if changes is None:
        return False
    if changes:
        _LOGGER.warning(
            "Auto-update stopped after fetch because local changes appeared. "
            "No update was applied.\n%s",
            changes,
        )
        return False

    local_head = _run_git("rev-parse", "HEAD")
    remote_head = _run_git("rev-parse", update_ref)
    if local_head.returncode != 0 or remote_head.returncode != 0:
        _git_error(
            "resolve update revisions",
            local_head if local_head.returncode != 0 else remote_head,
        )
        return False
    if local_head.stdout.strip() == remote_head.stdout.strip():
        _LOGGER.info("Already running the latest configured revision")
        return True

    counts = _run_git("rev-list", "--left-right", "--count", f"HEAD...{update_ref}")
    if counts.returncode != 0:
        _git_error("compare local and upstream revisions", counts)
        return False
    try:
        ahead, behind = (int(value) for value in counts.stdout.split())
    except (TypeError, ValueError):
        _git_error("compare local and upstream revisions", counts)
        return False

    if ahead:
        if behind:
            reason = "the local and upstream branches have diverged"
        else:
            reason = "the local branch contains commits not present upstream"
        _LOGGER.warning("Auto-update skipped: %s; no files were changed", reason)
        return False
    if not behind:
        _LOGGER.info("Already running the latest configured revision")
        return True

    merge = _run_git("merge", "--ff-only", "--no-edit", update_ref)
    if merge.returncode != 0:
        _git_error("fast-forward the working tree", merge)
        return False

    display_repo = "/".join(upstream_repo.split("/")[-2:])
    _LOGGER.info("Successfully fast-forwarded to the latest configured revision")
    _LOGGER.info(f"UPSTREAM_REPO: {display_repo} | UPSTREAM_BRANCH: {upstream_branch} | VERSION: {version}")
    return True

def _update_packages(update_pkgs):
    if as_bool(update_pkgs):
        _LOGGER.info("Updating Packages...")
        pkg_update = srun(
            ["uv", "pip", "install", "--system", "-U", "-r", "requirements.txt"],
            capture_output=True,
            text=True,
        )
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

    auto_update = config_file.get("AUTO_UPDATE", False)
    if as_bool(auto_update):
        _run_update(upstream_repo, upstream_branch, version)
    else:
        _LOGGER.info(
            "Automatic Git updates are disabled (AUTO_UPDATE=false); "
            "the working tree will not be modified"
        )

    update_pkgs = config_file.get("UPDATE_PKGS", False)
    _update_packages(update_pkgs)


if __name__ == "__main__":
    main()
