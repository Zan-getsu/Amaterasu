from ast import literal_eval
from importlib import import_module
from json import loads as json_loads
from json import JSONDecodeError
from os import getenv
from shutil import which
from typing import Optional, Type


def _try_parse_collection(value: str, kind: Type):
    """Parse a string into a list or dict, preferring JSON.

    Returns None if parsing fails (caller falls back to default or
    comma-split). Tries JSON first (safe, standard), then literal_eval
    (backward compat with existing deployments using Python-literal
    syntax). literal_eval is safe-ish (it rejects names and calls),
    but JSON is preferred because it can't trigger __import__ tricks.
    """
    value = value.strip()
    if not value:
        return None
    # JSON first
    try:
        parsed = json_loads(value)
        if isinstance(parsed, kind):
            return parsed
    except (JSONDecodeError, ValueError):
        pass
    # Backward compat: Python-literal syntax (e.g. "['a', 'b']" or
    # "{'key': 'val'}"). literal_eval is safe — it only accepts literals.
    try:
        parsed = literal_eval(value)
        if isinstance(parsed, kind):
            return parsed
    except (ValueError, SyntaxError):
        pass
    return None


class Config:
    _LEGACY_URL_VARS = {
        "FQDN",
        "HAS_SSL",
        "NO_PORT",
        "BASE_URL_PORT",
        "CLOUDFLARE_TUNNEL_AUTO_FQDN",
    }

    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    AUTO_PROVISION_STREAM_BOTS = False
    BASE_URL = ""
    BOT_TOKEN = ""
    HELPER_TOKENS = ""
    HELPER_STRINGS = ""
    HELPER_BOT_PROXIES = ""
    HELPER_USER_PROXIES = ""
    # 0 = unlimited. Default 10 prevents a single user from starving the
    # bot by queuing 1000 downloads. Set to 0 to restore old behavior.
    BOT_MAX_TASKS = 10
    BOT_PM = False
    CMD_SUFFIX = ""
    COLORED_BTNS = True
    DEFAULT_LANG = "en"
    DATABASE_URL = ""
    DEFAULT_UPLOAD = "rc"
    DELETE_LINKS = False
    DEBRID_LINK_API = ""
    DISABLE_TORRENTS = False
    DISABLE_LEECH = False
    DISABLE_BULK = False
    DISABLE_MULTI = False
    DISABLE_SEED = False
    DISABLE_FF_MODE = False
    DISABLE_MEGA = False
    DISABLE_JD = False
    DISABLE_NZB = False
    DISABLE_RSS = False
    DISABLE_SEARCH = False
    DISABLE_YTDLP = False
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    FILELION_API = ""
    MEDIA_STORE = True
    FORCE_SUB_IDS = ""
    GOFILE_API = ""
    GOFILE_FOLDER_ID = ""
    GOFILE_AUTO_CREATE_FOLDER = False
    PIXELDRAIN_KEY = ""
    PROTECTED_API = ""
    BUZZHEAVIER_API = ""
    DEVUPLOADS_KEY = ""
    DEVUPLOADS_FOLDER = ""
    VIKINGFILE_HASH = ""
    VIKINGFILE_FOLDER = ""
    GDRIVE_ID = ""
    GD_DESP = "Uploaded with Amaterasu"
    AUTHOR_NAME = "Ńiłøÿ Bhowmick"
    AUTHOR_URL = "https://t.me/itsniloybhowmick"
    INSTADL_API = ""
    IMDB_TEMPLATE = ""
    # JioDrive (Indian cloud storage) bypass token.
    # Default empty: scraper raises a clear error if invoked without a token.
    JIODRIVE_TOKEN = ""
    IMAGES = []
    IMG_SEARCH = ""
    IMG_PAGE = 1
    USE_IMAGES = False
    INCOMPLETE_TASK_NOTIFIER = False
    IMG_SOURCES = ["wallpaperflare"]
    INC_TASK_RESUME = False
    INCOMPLETE_TASK_TTL = 86400
    INDEX_URL = ""
    IS_TEAM_DRIVE = False
    JD_EMAIL = ""
    JD_PASS = ""
    MEGA_EMAIL = ""
    MEGA_PASSWORD = ""
    DISABLE_MEGA = False
    DIRECT_LIMIT = 0
    MEGA_LIMIT = 0
    TORRENT_LIMIT = 0
    GD_DL_LIMIT = 0
    RC_DL_LIMIT = 0
    CLONE_LIMIT = 0
    JD_LIMIT = 0
    NZB_LIMIT = 0
    YTDLP_LIMIT = 0
    PLAYLIST_LIMIT = 0
    LEECH_LIMIT = 0
    EXTRACT_LIMIT = 0
    ARCHIVE_LIMIT = 0
    STORAGE_LIMIT = 0
    LEECH_DUMP_CHAT = ""
    LINKS_LOG_ID = ""
    MIRROR_LOG_ID = ""
    LEECH_PREFIX = ""
    LEECH_CAPTION = ""
    LEECH_SUFFIX = ""
    LEECH_FONT = ""
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    USE_HYPER = True
    HYPER_THREADS = 0
    HYPER_PIPELINE = 4
    HYPER_CHUNK = 512 * 1024
    CPU_LIMIT = 20
    THROTTLE_SERVICES = "auto"
    HYDRA_IP = ""
    HYDRA_API_KEY = ""
    NAME_SWAP = ""
    OWNER_ID = 0
    QUEUE_ALL = 0
    QUEUE_DOWNLOAD = 0
    QUEUE_UPLOAD = 0
    RCLONE_FLAGS = ""
    RCLONE_PATH = ""
    RCLONE_SERVE_URL = ""
    SHOW_CLOUD_LINK = True
    RCLONE_SERVE_USER = ""
    RCLONE_SERVE_PASS = ""
    RCLONE_SERVE_PORT = 8081
    RSS_CHAT = ""
    RSS_DELAY = 600
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = []
    SET_COMMANDS = True
    PROGRESS_BAR = "█:░"
    STATUS_LIMIT = 10
    STATUS_UPDATE_INTERVAL = 15
    STOP_DUPLICATE = False
    STREAMWISH_API = ""
    SUDO_USERS = ""
    TELEGRAM_API = 0
    TELEGRAM_HASH = ""
    TG_PROXY = None
    THUMBNAIL_LAYOUT = ""
    VERIFY_TIMEOUT = 0
    LOGIN_PASS = ""
    TORRENT_TIMEOUT = 0
    TIMEZONE = "Asia/Dhaka"
    # 0 = unlimited. Default 3 concurrent tasks per user for fairness.
    USER_MAX_TASKS = 3
    USER_TIME_INTERVAL = 0
    UPLOAD_PATHS = {}
    DRIVE_CATEGORY_MODE = False
    DRIVE_CATEGORY_SA = ""
    UPSTREAM_REPO = "https://github.com/Zan-getsu/Amaterasu"
    UPSTREAM_BRANCH = "main"
    UPDATE_PKGS = False  # default off — pin and update explicitly to avoid surprises
    USENET_SERVERS = []
    USER_SESSION_STRING = ""
    TRANSMISSION_MODE = "both"
    USE_SERVICE_ACCOUNTS = False
    WEB_ACCESS_PASSWORD = ""
    WEB_PINCODE = True
    AMATERASU_WEB_SECRET = ""
    YT_DLP_OPTIONS = {}
    YT_DESP = "Uploaded with Amaterasu"
    YT_TAGS = ["telegram", "bot", "youtube"]
    YT_CATEGORY_ID = 22
    YT_PRIVACY_STATUS = "unlisted"
    DEFAULT_ENCODE_PRESET = {}
    DISABLE_ENCODE = False

    # Phase 3.1 — FFmpeg hardware acceleration.
    # 'auto' (default): probe for NVENC → QSV → VAAPI → VideoToolbox at
    #   startup, use the first available, fall back to libx264 (software).
    # 'nvenc': force NVIDIA NVENC (fail back to libx264 if unavailable).
    # 'qsv': force Intel Quick Sync Video.
    # 'vaapi': force VAAPI (AMD/Intel Linux).
    # 'none': always use libx264 software encoding (slowest but most
    #   compatible — use if hardware drivers are flaky).
    FFMPEG_HW_ACCEL = "auto"

    # Phase 3.5 — upload queue parallelism. Number of parallel uploads
    # per bot. Default 3 — balances throughput with Telegram rate limits.
    # Increase to 5-8 for premium bots with high FloodWait tolerance.
    UPLOAD_PARALLELISM = 3

    # Phase 3.7 — yt-dlp playlist parallelism. Number of playlist items
    # to download concurrently. Default 3, max 6 (higher risks source
    # site rate limits). Each item's progress shows as "Item N/Total".
    PLAYLIST_PARALLELISM = 3

    # Phase 4.4 — automatic subtitle download. When True, after a video
    # file is downloaded, search OpenSubtitles for subtitles in
    # SUBTITLE_LANGS and download the top match per language. Saved as
    # filename.lang.srt alongside the video. Requires OPENSUBTITLES_API
    # to be set. If API is unreachable or no results, the task continues
    # without subtitles (never fails the task).
    AUTO_SUBTITLES = False
    SUBTITLE_LANGS = "en"
    OPENSUBTITLES_API = ""

    # Phase 4.5/4.6/4.7 — additional rclone upload remotes. When set,
    # these appear as upload destination options in the existing rclone
    # upload flow. No new code — just config registration + README docs.
    # Each value is the rclone remote name (e.g., 'myb2' for a B2 remote
    # configured via `rclone config`).
    RCLONE_SFTP_REMOTE = ""
    RCLONE_WEBDAV_REMOTE = ""
    RCLONE_B2_REMOTE = ""
    RCLONE_ONEDRIVE_REMOTE = ""
    RCLONE_DROPBOX_REMOTE = ""

    # Phase 4.8 — Telegram Premium bot detection. Set automatically at
    # startup by TgClient.start_bot() via client.get_me().is_premium.
    # When True, telegram_uploader uses 4 GB split size (vs 2 GB standard).
    # Operators should NOT set this manually — it's auto-detected.
    IS_PREMIUM_BOT = False

    # Phase 5.5 — per-user quota system. 0 = unlimited (default).
    # Owner can set global defaults here, and override per-user via
    # the /userlist owner panel. Quota is checked in pre_task_check
    # before starting a download. Resets lazily (daily = 24h, monthly
    # = 30 days) — no cron needed.
    USER_DAILY_QUOTA_GB = 0
    USER_MONTHLY_QUOTA_GB = 0

    # Phase 6.4 — structured logging format. 'text' (default) uses the
    # human-readable format "[timestamp] [LEVEL] - message". 'json'
    # outputs each log line as JSON: {"ts": "...", "level": "...",
    # "logger": "...", "msg": "...", "extra": {...}}. JSON format is
    # easier for log aggregation (ELK, Loki, Datadog).
    LOG_FORMAT = "text"

    # Security: dangerous commands (RCE) — disabled by default.
    # Set ENABLE_SHELL_COMMAND=1 to re-enable /shell (owner-only).
    # Set ENABLE_EXEC_COMMAND=1 to re-enable /exec and /aexec (owner-only).
    ENABLE_SHELL_COMMAND = False
    ENABLE_EXEC_COMMAND = False

    # Hosts for which TLS verification is skipped (e.g. internal mirrors
    # with self-signed certs). Empty by default — all outbound HTTPS
    # requests verify the server certificate.
    INSECURE_HOSTS = []

    MULTI_TOKENS = {}

    # FileToLink settings
    BIN_CHANNEL = 0
    MAX_BATCH_FILES = 50
    CHANNEL = False
    BANNED_CHANNELS = ""
    TOKEN_ENABLED = False
    TOKEN_TTL_HOURS = 24
    SHORTEN_ENABLED = False
    SHORTEN_MEDIA_LINKS = False
    URL_SHORTENER_API_KEY = ""
    URL_SHORTENER_SITE = ""
    GLOBAL_RATE_LIMIT = False
    MAX_GLOBAL_REQUESTS_PER_MINUTE = 4
    RATE_LIMIT_ENABLED = False
    MAX_FILES_PER_PERIOD = 2
    RATE_LIMIT_PERIOD_MINUTES = 1
    MAX_QUEUE_SIZE = 100

    # When True (default), docker-compose binds the web UI to 127.0.0.1 only —
    # operators must put a reverse proxy (nginx, Caddy, Cloudflare Tunnel) in
    # front. When False, the web UI binds 0.0.0.0 and is reachable on the
    # host LAN directly. Useful for quick deployments without a reverse proxy
    # or for operators who want direct access via an SSH tunnel.
    # Trade-off: False is more convenient but exposes the web UI to anyone
    # who can reach the host on port 8080.
    BIND_TO_LOOPBACK = True

    # Comma-separated regex patterns for allowed UPSTREAM_REPO URLs in
    # update.py. Default allows github.com, raw.githubusercontent.com, and
    # the Amaterasu Forgejo mirror. Add your own fork URL here to enable
    # auto-update from a custom fork. Example:
    #   UPSTREAM_ALLOWLIST="^https://github\.com/yourname/Amaterasu/?$"
    # Multiple patterns are comma-separated.
    UPSTREAM_ALLOWLIST = (
        r"^https://("
        r"github\.com/[\w.-]+/[\w.-]+/?|"
        r"raw\.githubusercontent\.com/[\w.-]+/[\w.-]+/?|"
        r"git\.nbmirror\.qzz\.io(?:/[\w.-]+/[\w.-]+)?/?"
        r")$"
    )

    # When True, the SABnzbd.ini patcher refuses to start SABnzbd if it
    # cannot replace known-bad credential markers (sabpassword, CHANGEME,
    # REPLACED_AT_BOOT_BY_AMATERASU). This is a safety net against shipping
    # default credentials. When False (skip the check), SABnzbd starts even
    # if the ini file has unknown content — useful for operators who manage
    # SABnzbd.ini manually or migrate from a custom config.
    SKIP_SABNZBD_INI_CHECK = False

    # Advanced / Web Server Settings
    FQDN = ""
    HAS_SSL = True
    PORT = 8080
    BASE_URL_PORT = 0
    NO_PORT = True
    CLOUDFLARE_TUNNEL_ENABLED = False
    CLOUDFLARE_TUNNEL_TOKEN = ""
    CLOUDFLARE_TUNNEL_TARGET = ""
    CLOUDFLARE_TUNNEL_METRICS = "127.0.0.1:49312"
    CLOUDFLARE_TUNNEL_AUTO_URL = True
    CLOUDFLARE_TUNNEL_AUTO_FQDN = None
    NAME = "Amaterasu"
    SLEEP_THRESHOLD = 600
    WORKERS = 8
    BIND_ADDRESS = "0.0.0.0"
    PING_INTERVAL = 840

    @classmethod
    def get(cls, key):
        return getattr(cls, key) if hasattr(cls, key) else None

    @staticmethod
    def _coerce_optional_bool(value):
        if value is None or isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("", "none", "null"):
            return None
        return text in ("true", "1", "t", "y", "yes", "on")

    @classmethod
    def set(cls, key, value):
        if hasattr(cls, key):
            if key == "CLOUDFLARE_TUNNEL_AUTO_FQDN":
                value = cls._coerce_optional_bool(value)
            else:
                value = cls._convert_env_type(key, value)
            setattr(cls, key, value)
            if key == "BASE_URL":
                cls.FQDN = ""
                cls.HAS_SSL = True
                cls.NO_PORT = True
            elif key == "CLOUDFLARE_TUNNEL_AUTO_URL":
                cls.CLOUDFLARE_TUNNEL_AUTO_FQDN = None
            elif key == "CLOUDFLARE_TUNNEL_AUTO_FQDN":
                if value is not None:
                    cls.CLOUDFLARE_TUNNEL_AUTO_URL = value
                cls.CLOUDFLARE_TUNNEL_AUTO_FQDN = None
            if key in [
                "PORT",
                "BASE_URL_PORT",
                "FQDN",
                "HAS_SSL",
                "NO_PORT",
                "BASE_URL",
            ]:
                cls.construct_base_url()
        elif key.startswith("MULTI_TOKEN"):
            cls.MULTI_TOKENS[key] = value.strip() if isinstance(value, str) else str(value)
        else:
            raise KeyError(f"{key} is not a valid configuration key.")

    @classmethod
    def get_all(cls):
        d = {
            key: getattr(cls, key)
            for key in cls.__dict__.keys()
            if not key.startswith("_")
            and key not in cls._LEGACY_URL_VARS
            and not callable(getattr(cls, key))
        }
        d.pop("MULTI_TOKENS", None)
        d.update(cls.MULTI_TOKENS)
        return d

    @classmethod
    def load(cls):
        cls.load_config()
        cls.load_env()
        cls._validate_required()
        cls.construct_base_url()

    @classmethod
    def _validate_required(cls):
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

    @classmethod
    def construct_base_url(cls):
        env_port = getenv("PORT", "")
        if env_port and str(env_port).isdigit():
            resolved_port = int(env_port)
        else:
            port_val = getattr(cls, "PORT", 0)
            base_port_val = getattr(cls, "BASE_URL_PORT", 0)
            p_val = int(port_val) if str(port_val).isdigit() else 0
            bp_val = int(base_port_val) if str(base_port_val).isdigit() else 0
            resolved_port = p_val or bp_val or 8080
            
        cls.PORT = resolved_port
        cls.BASE_URL_PORT = resolved_port

        if cls.BASE_URL:
            cls.BASE_URL = str(cls.BASE_URL).strip().rstrip("/")
            return

        cls.BASE_URL = ""
        if cls.FQDN:
            cls.FQDN = str(cls.FQDN).strip().strip("/")
            protocol = "https" if cls.HAS_SSL else "http"
            if cls.NO_PORT or cls.PORT in [80, 443]:
                cls.BASE_URL = f"{protocol}://{cls.FQDN}"
            else:
                cls.BASE_URL = f"{protocol}://{cls.FQDN}:{cls.PORT}"

    @classmethod
    def load_config(cls):
        try:
            settings = import_module("config")
        except ModuleNotFoundError:
            return
        for attr in dir(settings):
            if hasattr(cls, attr):
                value = getattr(settings, attr)
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                if isinstance(value, str):
                    value = value.strip()
                if attr == "DEFAULT_UPLOAD" and value != "gd":
                    value = "rc"
                elif attr in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                elif attr == "USENET_SERVERS":
                    try:
                        if not value[0].get("host"):
                            continue
                    except Exception:
                        continue
                elif attr == "CMD_SUFFIX":
                    value = str(value).strip()
                setattr(cls, attr, value)
            elif attr.startswith("MULTI_TOKEN"):
                value = getattr(settings, attr)
                if value:
                    cls.MULTI_TOKENS[attr] = value.strip() if isinstance(value, str) else str(value)
    @classmethod
    def load_env(cls):
        config_vars = cls.get_all()
        has_modern_auto_url = getenv("CLOUDFLARE_TUNNEL_AUTO_URL") is not None
        for key in config_vars:
            env_value = getenv(key)
            if env_value is not None:
                if key.startswith("MULTI_TOKEN"):
                    cls.MULTI_TOKENS[key] = env_value.strip()
                else:
                    converted_value = cls._convert_env_type(key, env_value)
                    cls.set(key, converted_value)
        for key in cls._LEGACY_URL_VARS:
            if key == "CLOUDFLARE_TUNNEL_AUTO_FQDN" and has_modern_auto_url:
                continue
            env_value = getenv(key)
            if env_value is not None:
                cls.set(key, env_value)
        # Also load extra MULTI_TOKENs that might not be in config_vars
        from os import environ
        for key, value in environ.items():
            if key.startswith("MULTI_TOKEN") and value.strip():
                cls.MULTI_TOKENS[key] = value.strip()

    @classmethod
    def _convert_env_type(cls, key, value):
        if key == "CMD_SUFFIX":
            return str(value).strip() if value is not None else ""
        original_value = getattr(cls, key, None)
        if original_value is None:
            return value
        if isinstance(original_value, bool):
            if isinstance(value, bool):
                return value
            return str(value).lower() in ["true", "1", "t", "y", "yes", "on"]
        elif isinstance(original_value, int):
            if isinstance(value, int):
                return value
            try:
                return int(value)
            except (ValueError, TypeError):
                return original_value
        elif isinstance(original_value, float):
            if isinstance(value, float):
                return value
            try:
                return float(value)
            except (ValueError, TypeError):
                return original_value
        elif isinstance(original_value, list):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                # Prefer JSON (safe). Fall back to literal_eval for backward
                # compat with existing deployments that may use Python-literal
                # syntax (e.g. "['a', 'b']"). Fall back to comma-split.
                parsed = _try_parse_collection(value, list)
                if parsed is not None:
                    return parsed
                if value.startswith("[") and value.endswith("]"):
                    return original_value
                return [v.strip() for v in value.split(",") if v.strip()]
            return original_value
        elif isinstance(original_value, dict):
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                parsed = _try_parse_collection(value, dict)
                if parsed is not None:
                    return parsed
            return original_value
        return value

    @classmethod
    def load_dict(cls, config_dict):
        has_base_url = "BASE_URL" in config_dict
        has_auto_url = "CLOUDFLARE_TUNNEL_AUTO_URL" in config_dict
        for key, value in config_dict.items():
            if (
                key in cls._LEGACY_URL_VARS
                and key != "CLOUDFLARE_TUNNEL_AUTO_FQDN"
                and has_base_url
            ):
                continue
            if key == "CLOUDFLARE_TUNNEL_AUTO_FQDN" and has_auto_url:
                continue
            if hasattr(cls, key):
                if key == "DEFAULT_UPLOAD" and value != "gd":
                    value = "rc"
                elif key in [
                    "BASE_URL",
                    "RCLONE_SERVE_URL",
                    "INDEX_URL",
                    "SEARCH_API_LINK",
                ]:
                    if value:
                        value = value.strip("/")
                elif key == "USENET_SERVERS":
                    try:
                        if not value[0].get("host"):
                            value = []
                    except Exception:
                        value = []
                cls.set(key, value)
            elif key.startswith("MULTI_TOKEN") and value:
                cls.MULTI_TOKENS[key] = value.strip() if isinstance(value, str) else str(value)
        if has_auto_url:
            cls.CLOUDFLARE_TUNNEL_AUTO_FQDN = None
        cls._validate_required()
        cls.construct_base_url()


class BinConfig:
    ARIA2_NAME = "aria2c"
    QBIT_NAME = "qbittorrent-nox"
    # Source-built FFmpeg is installed in /usr/local/bin; distro packages
    # use /usr/bin. Resolve it at startup so every encode/thumbnail command
    # uses the binary that is actually present in the image.
    FFMPEG_NAME = which("ffmpeg") or "/usr/bin/ffmpeg"
    RCLONE_NAME = "rclone"
    SABNZBD_NAME = "sabnzbdplus"
