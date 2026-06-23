# ==========================================
# 1. REQUIRED CONFIGURATION
# ==========================================
BOT_TOKEN = ""
OWNER_ID = 0
TELEGRAM_API = 0
TELEGRAM_HASH = ""
DATABASE_URL = ""

# ==========================================
# 2. TELEGRAM CLIENT & SESSIONS
# ==========================================
USER_SESSION_STRING = ""
HELPER_TOKENS = ""
HELPER_STRINGS = ""
HELPER_BOT_PROXIES = ""
HELPER_USER_PROXIES = ""
DEFAULT_LANG = ""
TG_PROXY = {}
BOT_PM = False
BOT_MAX_TASKS = 10
USER_MAX_TASKS = 3
USER_TIME_INTERVAL = 0
VERIFY_TIMEOUT = 0
LOGIN_PASS = ""
SET_COMMANDS = False
TIMEZONE = ""

# ==========================================
# 3. CHAT & PERMISSIONS
# ==========================================
CMD_SUFFIX = ""
AUTHORIZED_CHATS = ""
SUDO_USERS = ""
FORCE_SUB_IDS = ""
BANNED_CHANNELS = ""

# ==========================================
# 4. LEECH & UPLOADS
# ==========================================
DEFAULT_UPLOAD = ""
LEECH_SPLIT_SIZE = 0
AS_DOCUMENT = False
EQUAL_SPLITS = False
MEDIA_GROUP = False
TRANSMISSION_MODE = "both"
USE_HYPER = True
HYPER_THREADS = 0
HYPER_PIPELINE = 4
HYPER_CHUNK = 512 * 1024
LEECH_PREFIX = ""
LEECH_SUFFIX = ""
LEECH_FONT = ""
LEECH_CAPTION = ""
THUMBNAIL_LAYOUT = ""
EXCLUDED_EXTENSIONS = ""

# DDL / Uphoster destinations
GOFILE_API = ""
GOFILE_FOLDER_ID = ""
PIXELDRAIN_KEY = ""
BUZZHEAVIER_API = ""
DEVUPLOADS_KEY = ""
DEVUPLOADS_FOLDER = ""
VIKINGFILE_HASH = ""
VIKINGFILE_FOLDER = ""

# ==========================================
# 5. GOOGLE DRIVE OPTIONS
# ==========================================
GDRIVE_ID = ""
GD_DESP = ""
IS_TEAM_DRIVE = False
STOP_DUPLICATE = False
INDEX_URL = ""
USE_SERVICE_ACCOUNTS = False
WEB_ACCESS_PASSWORD = ""  # Secret for deriving proxy passwords. Logs derived passwords at startup.

# ==========================================
# 6. RCLONE OPTIONS
# ==========================================
RCLONE_PATH = ""
RCLONE_FLAGS = ""
RCLONE_SERVE_URL = ""
SHOW_CLOUD_LINK = False
RCLONE_SERVE_PORT = 0
RCLONE_SERVE_USER = ""
RCLONE_SERVE_PASS = ""

# ==========================================
# 7. DOWNLOAD ENGINE LIMITS & CONFIGS
# ==========================================
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

# ==========================================
# 8. TORRENTS & ARIA2C / QBITTORRENT
# ==========================================
DISABLE_TORRENTS = False
DISABLE_SEED = False
TORRENT_TIMEOUT = 0
BASE_URL = ""
WEB_PINCODE = False
AMATERASU_WEB_SECRET = ""
QUEUE_ALL = 0
QUEUE_DOWNLOAD = 0
QUEUE_UPLOAD = 0

# ==========================================
# 9. JDOWNLOADER & SABNZBD
# ==========================================
JD_EMAIL = ""
JD_PASS = ""
MEGA_EMAIL = ""
MEGA_PASSWORD = ""
DISABLE_MEGA = False
DISABLE_JD = False
DISABLE_NZB = False
USENET_SERVERS = []

# ==========================================
# 10. MEDIA SEARCH & IMDB
# ==========================================
IMAGES = []
IMG_SEARCH = ""
IMG_PAGE = 1
USE_IMAGES = False
IMDB_TEMPLATE = ""
INSTADL_API = ""
HYDRA_IP = ""
HYDRA_API_KEY = ""

# ==========================================
# 11. YOUTUBE TOOLS
# ==========================================
YT_DESP = ""
YT_TAGS = []
YT_CATEGORY_ID = 0
YT_PRIVACY_STATUS = ""
YT_DLP_OPTIONS = ""

# ==========================================
# 12. TELEGRAPH & METADATA
# ==========================================
AUTHOR_NAME = ""
AUTHOR_URL = ""

# ==========================================
# 13. LOG CHANNELS & NOTIFIERS
# ==========================================
LEECH_DUMP_CHAT = ""
LINKS_LOG_ID = ""
MIRROR_LOG_ID = ""
PROGRESS_BAR = "█:░"
STATUS_LIMIT = 10
STATUS_UPDATE_INTERVAL = 0
INCOMPLETE_TASK_NOTIFIER = False
INC_TASK_RESUME = False
CLEAN_LOG_MSG = False
DELETE_LINKS = False
MEDIA_STORE = False
COLORED_BTNS = True

# ==========================================
# 14. DYNAMIC FILE-TO-LINK STREAMING
# ==========================================
BIN_CHANNEL = 0
MAX_BATCH_FILES = 0
CHANNEL = False
MULTI_TOKEN1 = ""
MULTI_TOKEN2 = ""
MULTI_TOKEN3 = ""
# When True, a configured USER_SESSION_STRING adds MULTI_TOKEN bots to
# BIN_CHANNEL and LEECH_DUMP_CHAT, then promotes them at startup.
AUTO_PROVISION_STREAM_BOTS = False

# Token System (FileToLink)
TOKEN_ENABLED = False
TOKEN_TTL_HOURS = 0

# URL Shortener (FileToLink)
SHORTEN_ENABLED = False
SHORTEN_MEDIA_LINKS = False
URL_SHORTENER_API_KEY = ""
URL_SHORTENER_SITE = ""

# Global Rate Limiting (FileToLink)
GLOBAL_RATE_LIMIT = False
MAX_GLOBAL_REQUESTS_PER_MINUTE = 0

# Session Rate Limiting (FileToLink)
RATE_LIMIT_ENABLED = False
MAX_FILES_PER_PERIOD = 0
RATE_LIMIT_PERIOD_MINUTES = 0
MAX_QUEUE_SIZE = 0

# ==========================================
# 15. DYNAMIC STREAMING WEB SERVER
# ==========================================
PORT = 8080
# When True (default), the web UI binds to 127.0.0.1 only — operators
# must put a reverse proxy (nginx, Caddy, Cloudflare Tunnel) in front.
# When False, binds 0.0.0.0 for direct LAN access. Trade-off: False is
# more convenient but exposes the web UI to anyone on the host LAN.
BIND_TO_LOOPBACK = True
CLOUDFLARE_TUNNEL_ENABLED = False
CLOUDFLARE_TUNNEL_TOKEN = ""
CLOUDFLARE_TUNNEL_TARGET = ""
CLOUDFLARE_TUNNEL_METRICS = "127.0.0.1:49312"
CLOUDFLARE_TUNNEL_AUTO_URL = True
NAME = ""
SLEEP_THRESHOLD = 0
WORKERS = 0
BIND_ADDRESS = ""
PING_INTERVAL = 0

# ==========================================
# 16. MISCELLANEOUS / EXTERNAL
# ==========================================
CMD_SUFFIX = ""
NAME_SWAP = ""
FFMPEG_CMDS = {}
UPLOAD_PATHS = {}
DISABLE_LEECH = False
DISABLE_BULK = False
DISABLE_MULTI = False
DISABLE_FF_MODE = False
DISABLE_RSS = False
DISABLE_SEARCH = False
DISABLE_YTDLP = False
CPU_LIMIT = 20
THROTTLE_SERVICES = "auto"
UPSTREAM_REPO = ""
UPSTREAM_BRANCH = "main"
UPDATE_PKGS = False
# Comma-separated regex patterns for allowed UPSTREAM_REPO URLs.
# Default (empty) uses the built-in 3-pattern allowlist:
#   github.com, raw.githubusercontent.com, git.nbmirror.qzz.io
# Add your own fork URL here to enable auto-update from a custom fork.
# Example: "^https://github\\.com/yourname/Amaterasu/?$"
UPSTREAM_ALLOWLIST = ""
# When True, the SABnzbd.ini patcher skips validation and starts SABnzbd
# even if known-bad credential markers cannot be replaced. Use only if
# you manage SABnzbd.ini manually. Default False refuses to start on
# default credentials — a safety net.
SKIP_SABNZBD_INI_CHECK = False

# RSS
RSS_DELAY = 600
RSS_CHAT = ""
RSS_SIZE_LIMIT = 0

# Torrent Search
SEARCH_API_LINK = ""
SEARCH_LIMIT = 0
SEARCH_PLUGINS = [
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/piratebay.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/limetorrents.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torlock.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentscsv.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/eztv.py",
    "https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentproject.py",
    "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/kickass_torrent.py",
    "https://raw.githubusercontent.com/MaurizioRicci/qBittorrent_search_engines/master/yts_am.py",
    "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/linuxtracker.py",
    "https://raw.githubusercontent.com/MadeOfMagicAndWires/qBit-plugins/master/engines/nyaasi.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/ettv.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/glotorrents.py",
    "https://raw.githubusercontent.com/LightDestory/qBittorrent-Search-Plugins/master/src/engines/thepiratebay.py",
    "https://raw.githubusercontent.com/v1k45/1337x-qBittorrent-search-plugin/master/leetx.py",
    "https://raw.githubusercontent.com/nindogo/qbtSearchScripts/master/magnetdl.py",
    "https://raw.githubusercontent.com/msagca/qbittorrent_plugins/main/uniondht.py",
    "https://raw.githubusercontent.com/khensolomon/leyts/master/yts.py",
]

# ==========================================
# 17. ENCODE SETTINGS
# ==========================================
DEFAULT_ENCODE_PRESET = {
    "video_codec": "libsvtav1",  # Standard SVT-AV1 Encoder
    "audio_codec": "libopus",
    "subtitle_mode": "copy",
    "video_params": {
        "crf": 34,  # Optimal CRF for standard anime encode
        "preset": 6,  # Standard preset sweet-spot for quality/speed
        "pix_fmt": "yuv420p10le",
        "profile": 0,
        "level": "5.1",
        # Standard Mainline SVT-AV1 Optimized Parameters:
        "extra_params": "tune=0:film-grain=4:film-grain-denoise=0:enable-overlays=1:scm=2:keyint=240:irefresh-type=2",
        "color_primaries": "bt709",
        "color_trc": "bt709",
        "colorspace": "bt709",
    },
    "audio_params": {"bitrate": "128k", "channels": 2, "vbr": True},
}
DISABLE_ENCODE = False

# ==========================================
# 18. SECURITY (DANGEROUS COMMANDS)
# ==========================================
# Disabled by default. Enable ONLY if you trust every sudo user
# AND understand these commands grant root-equivalent access in
# the container. With shell=True (shell) or exec() (exec), a
# compromised sudo account can exfiltrate config.py, BOT_TOKEN,
# DATABASE_URL, rclone.conf, and all service-account JSONs.
ENABLE_SHELL_COMMAND = False
ENABLE_EXEC_COMMAND = False

# Hosts for which TLS verification is skipped (e.g. internal mirrors
# with self-signed certs). Empty by default — all outbound HTTPS
# requests verify the server certificate.
INSECURE_HOSTS = []

# ==========================================
# 19. v1.6.3 NEW FEATURES
# ==========================================

# FFmpeg hardware acceleration. 'auto' detects NVENC/QSV/
# VAAPI/VideoToolbox at startup. Options: auto, nvenc, qsv, vaapi, none.
FFMPEG_HW_ACCEL = "auto"

# upload queue parallelism. Number of concurrent uploads.
UPLOAD_PARALLELISM = 3

# yt-dlp playlist parallelism (max 6).
PLAYLIST_PARALLELISM = 3

# Automatic subtitle download. Requires OPENSUBTITLES_API.
AUTO_SUBTITLES = False
SUBTITLE_LANGS = "en"
OPENSUBTITLES_API = ""

# Additional rclone upload remotes. Set to the rclone
# remote name configured via `rclone config`.
RCLONE_SFTP_REMOTE = ""
RCLONE_WEBDAV_REMOTE = ""
RCLONE_B2_REMOTE = ""
RCLONE_ONEDRIVE_REMOTE = ""
RCLONE_DROPBOX_REMOTE = ""

# Auto-detected at startup. Do NOT set manually.
IS_PREMIUM_BOT = False

# Per-user quota (0 = unlimited).
USER_DAILY_QUOTA_GB = 0
USER_MONTHLY_QUOTA_GB = 0

# Structured logging format: 'text' or 'json'.
LOG_FORMAT = "text"
