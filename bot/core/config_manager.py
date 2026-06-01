from importlib import import_module
from os import getenv


class Config:
    AS_DOCUMENT = False
    AUTHORIZED_CHATS = ""
    BASE_URL = ""
    BASE_URL_PORT = 80
    BOT_TOKEN = ""
    HELPER_TOKENS = ""
    BOT_MAX_TASKS = 0
    BOT_PM = False
    CMD_SUFFIX = ""
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
    EQUAL_SPLITS = False
    EXCLUDED_EXTENSIONS = ""
    FFMPEG_CMDS = {}
    FILELION_API = ""
    MEDIA_STORE = True
    FORCE_SUB_IDS = ""
    GOFILE_API = ""
    GOFILE_FOLDER_ID = ""
    PIXELDRAIN_KEY = ""
    PROTECTED_API = ""
    BUZZHEAVIER_API = ""
    GDRIVE_ID = ""
    GD_DESP = "Uploaded with Amaterasu"
    AUTHOR_NAME = "Ńiłøÿ Bhowmick"
    AUTHOR_URL = "https://t.me/itsniloybhowmick"
    INSTADL_API = ""
    IMDB_TEMPLATE = ""
    INCOMPLETE_TASK_NOTIFIER = False
    INDEX_URL = ""
    IS_TEAM_DRIVE = False
    JD_EMAIL = ""
    JD_PASS = ""
    MEGA_EMAIL = ""
    MEGA_PASSWORD = ""
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
    CLEAN_LOG_MSG = False
    LEECH_PREFIX = ""
    LEECH_CAPTION = ""
    LEECH_SUFFIX = ""
    LEECH_FONT = ""
    LEECH_SPLIT_SIZE = 2097152000
    MEDIA_GROUP = False
    HYBRID_LEECH = True
    HYPER_THREADS = 0
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
    RCLONE_SERVE_PORT = 8080
    RSS_CHAT = ""
    RSS_DELAY = 600
    RSS_SIZE_LIMIT = 0
    SEARCH_API_LINK = ""
    SEARCH_LIMIT = 0
    SEARCH_PLUGINS = []
    SET_COMMANDS = True
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
    USER_MAX_TASKS = 0
    USER_TIME_INTERVAL = 0
    UPLOAD_PATHS = {}
    UPSTREAM_REPO = "https://github.com/its-niloy/Amaterasu"
    UPSTREAM_BRANCH = "main"
    UPDATE_PKGS = True
    USENET_SERVERS = []
    USER_SESSION_STRING = ""
    USER_TRANSMISSION = True
    USE_SERVICE_ACCOUNTS = False
    WEB_PINCODE = True
    YT_DLP_OPTIONS = {}
    YT_DESP = "Uploaded with Amaterasu"
    YT_TAGS = ["telegram", "bot", "youtube"]
    YT_CATEGORY_ID = 22
    YT_PRIVACY_STATUS = "unlisted"
    DEFAULT_ENCODE_PRESET = {}
    DISABLE_ENCODE = False

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

    # Advanced / Web Server Settings
    FQDN = ""
    HAS_SSL = True
    PORT = 8080
    NO_PORT = True
    NAME = "Amaterasu"
    SLEEP_THRESHOLD = 600
    WORKERS = 8
    BIND_ADDRESS = "0.0.0.0"
    PING_INTERVAL = 840

    @classmethod
    def get(cls, key):
        return getattr(cls, key) if hasattr(cls, key) else None

    @classmethod
    def set(cls, key, value):
        if hasattr(cls, key):
            value = cls._convert_env_type(key, value)
            setattr(cls, key, value)
            if key in ["PORT", "BASE_URL_PORT", "FQDN", "HAS_SSL", "NO_PORT", "BASE_URL"]:
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
            if not key.startswith("__") and not callable(getattr(cls, key))
        }
        d.pop("MULTI_TOKENS", None)
        d.update(cls.MULTI_TOKENS)
        return d

    @classmethod
    def load(cls):
        cls.load_config()
        cls.load_env()
        cls.construct_base_url()

    @classmethod
    def construct_base_url(cls):
        # Synchronize and robustly resolve PORT and BASE_URL_PORT
        env_port = getenv("PORT", "")
        if env_port:
            try:
                resolved_port = int(env_port)
            except ValueError:
                resolved_port = 80
        else:
            # If PORT and BASE_URL_PORT are defined, choose the first non-zero/valid one. Otherwise default to 80.
            port_val = getattr(cls, "PORT", 0)
            base_port_val = getattr(cls, "BASE_URL_PORT", 0)
            
            try:
                p_val = int(port_val) if port_val else 0
            except ValueError:
                p_val = 0
                
            try:
                bp_val = int(base_port_val) if base_port_val else 0
            except ValueError:
                bp_val = 0
                
            resolved_port = p_val or bp_val or 80
            
        cls.PORT = resolved_port
        cls.BASE_URL_PORT = resolved_port

        if cls.FQDN:
            protocol = "https" if cls.HAS_SSL else "http"
            if cls.NO_PORT or not cls.PORT or cls.PORT in [80, 443]:
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
                if not value:
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
                setattr(cls, attr, value)
            elif attr.startswith("MULTI_TOKEN"):
                value = getattr(settings, attr)
                if value:
                    cls.MULTI_TOKENS[attr] = value.strip() if isinstance(value, str) else str(value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")

    @classmethod
    def load_env(cls):
        config_vars = cls.get_all()
        for key in config_vars:
            env_value = getenv(key)
            if env_value is not None:
                if key.startswith("MULTI_TOKEN"):
                    cls.MULTI_TOKENS[key] = env_value.strip()
                else:
                    converted_value = cls._convert_env_type(key, env_value)
                    cls.set(key, converted_value)
        # Also load extra MULTI_TOKENs that might not be in config_vars
        from os import environ
        for key, value in environ.items():
            if key.startswith("MULTI_TOKEN") and value.strip():
                cls.MULTI_TOKENS[key] = value.strip()

    @classmethod
    def _convert_env_type(cls, key, value):
        original_value = getattr(cls, key, None)
        if original_value is None:
            return value
        elif isinstance(original_value, bool):
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
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
        return value

    @classmethod
    def load_dict(cls, config_dict):
        for key, value in config_dict.items():
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
                value = cls._convert_env_type(key, value)
                setattr(cls, key, value)
            elif key.startswith("MULTI_TOKEN") and value:
                cls.MULTI_TOKENS[key] = value.strip() if isinstance(value, str) else str(value)
        for key in ["BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH"]:
            value = getattr(cls, key)
            if isinstance(value, str):
                value = value.strip()
            if not value:
                raise ValueError(f"{key} variable is missing!")
        cls.construct_base_url()


class BinConfig:
    ARIA2_NAME = "aria2c"
    QBIT_NAME = "qbittorrent-nox"
    FFMPEG_NAME = "/usr/bin/ffmpeg"
    RCLONE_NAME = "rclone"
    SABNZBD_NAME = "sabnzbdplus"
