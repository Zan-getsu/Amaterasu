<div align="center">

# ☀️ A M A T E R A S U ☀️

```text
      █████╗ ███╗   ███╗███████╗████████╗███████╗██████╗  █████╗ ███████╗██╗   ██╗
     ██╔══██╗████╗ ████║██╔════╝╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔════╝██║   ██║
     ███████║██╔████╔██║█████╗     ██║   █████╗  ██████╔╝███████║███████╗██║   ██║
     ██╔══██║██║╚██╔╝██║██╔══╝     ██║   ██╔══╝  ██╔══██╗██╔══██║╚════██║██║   ██║
     ██║  ██║██║ ╚═╝ ██║███████╗   ██║   ███████╗██║  ██║██║  ██║███████║╚██████╔╝
     ╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝ 
```

**The Absolute Pinnacle of Telegram Mirroring and Leeching**

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/Version-1.1.0-orange?style=for-the-badge&logo=rocket"></a>
  <a href="#"><img src="https://img.shields.io/github/repo-size/its-niloy/Amaterasu?color=FF4500&label=Size&style=for-the-badge"></a>
  <a href="#"><img src="https://img.shields.io/github/license/its-niloy/Amaterasu?style=for-the-badge&color=FF8C00"></a>
  <br>
  <a href="#"><img src="https://img.shields.io/badge/Powered%20By-Python_3.11-blue?style=for-the-badge&logo=python"></a>
  <a href="#"><img src="https://img.shields.io/badge/Deployed_Via-Docker-2496ED?style=for-the-badge&logo=docker"></a>
  <a href="#"><img src="https://img.shields.io/badge/Framework-Pyrogram_2.2.19-green?style=for-the-badge&logo=telegram"></a>
</p>

[**Telegram Channel**](#) • [**Support Group**](#) • [**Report a Bug**](#)

</div>

---

## 📑 Table of Contents

- [🔮 Overview](#overview)
- [💎 Features](#features)
- [🧬 Architecture](#architecture)
- [⚙️ Prerequisites](#prerequisites)
- [🚀 Deployment](#deployment)
  - [Step 1: Prepare Your Server](#step-1-prepare-your-server)
  - [Step 2: Clone & Configure](#step-2-clone--configure)
  - [Step 3: Optional Files Setup](#step-3-optional-files-setup)
  - [Step 4: Build & Launch](#step-4-build--launch)
  - [What Happens on Boot?](#what-happens-on-boot)
  - [Reverse Proxy Setup](#reverse-proxy-setup)
  - [Maintenance & Operations](#maintenance--operations)
- [🔧 Configuration Reference](#configuration-reference)
  - [1. Required](#1-required-mandatory)
  - [2. Telegram Client & Sessions](#2-telegram-client--sessions)
  - [3. Chat & Permissions](#3-chat--permissions)
  - [4. Leech & Upload Settings](#4-leech--upload-settings)
  - [5. Google Drive](#5-google-drive)
  - [6. Rclone](#6-rclone)
  - [7. Download Size Limits](#7-download-size-limits)
  - [8. Torrent / Aria2c / qBittorrent](#8-torrent--aria2c--qbittorrent)
  - [9. JDownloader & Usenet](#9-jdownloader--usenet)
  - [10. Media & Search](#10-media--search)
  - [11. YouTube Tools](#11-youtube-tools)
  - [12. Log Channels & Notifications](#12-log-channels--notifications)
  - [13. FileToLink Streaming](#13-filetolink-streaming)
  - [14. Web Server](#14-web-server)
  - [15. Miscellaneous](#15-miscellaneous)
- [📖 Command Reference](#command-reference)
  - [Mirror Commands](#mirror-commands)
  - [Leech Commands](#leech-commands)
  - [Upload Hoster Commands](#upload-hoster-commands)
  - [Search & Info Commands](#search--info-commands)
  - [Task Management](#task-management)
  - [User Commands](#user-commands)
  - [Media & File Tools](#media--file-tools)
  - [Admin / Sudo Commands](#admin--sudo-commands)
- [🧰 Advanced Usage & Arguments](#advanced-usage--arguments)
  - [Argument Quick Reference](#argument-quick-reference)
  - [Telegram Link Downloads](#telegram-link-downloads)
  - [Rclone Paths](#rclone-paths)
  - [Upload Destination Shortcuts](#upload-destination-shortcuts)
- [🌐 FileToLink Streaming Server](#filetolink-streaming-server)
- [📡 RSS Automation](#rss-automation)
- [🔑 User Roles & Permissions](#user-roles--permissions)
- [❓ FAQ & Troubleshooting](#faq--troubleshooting)


---

<a id="overview"></a>

## 🔮 Overview

**Amaterasu** is a feature-dense, production-ready Telegram bot designed for power users who need a single interface to download from virtually any source on the internet, and then upload the result to a cloud drive or back to Telegram — all from a chat window.

It converges five industrial download engines (Aria2c, qBittorrent, JDownloader, Sabnzbd, yt-dlp) and multiple storage backends (Google Drive, Rclone remotes, Telegram, DDL hosters) into one cohesive, self-hosted system.

> [!IMPORTANT]
> Amaterasu also ships with a built-in **FileToLink** streaming web server. Any file uploaded to a designated Telegram channel can be instantly converted into a direct HTTP stream link — seekable, resumable, and playable in VLC, MX Player, or any browser.

---

<a id="features"></a>

## 💎 Features

<table align="center">
  <tr>
    <td align="center" width="50%">
      <h3>🌐 FileToLink Gateway</h3>
      <p>Instantly spawn HTTP 206 streamable links from Telegram files. Features automated <strong>Multi-Token Load Balancing</strong> across multiple bot tokens to evade FloodWait penalties and maintain zero latency under heavy load.</p>
    </td>
    <td align="center" width="50%">
      <h3>🎭 Smart Rename Engine</h3>
      <p>Toggle <code>/rename</code> mode to intercept any leech task or file sent via PM. Type your new filename and Amaterasu renames before uploading. Supports auto-rename templates for batch operations.</p>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <h3>🌩️ Multi-Engine Downloads</h3>
      <p>Pull from Torrents (Aria2c + qBittorrent), Direct Links, Usenet (Sabnzbd), Mega, JDownloader, and 1800+ sites via yt-dlp. Every engine has its own size limits and queue management.</p>
    </td>
    <td align="center" width="50%">
      <h3>🛡️ Enterprise Resilience</h3>
      <p>MongoDB-backed persistence for all user configs, queuing, and task state. Automated retries, dynamic polling, and graceful FloodWait handling ensure zero data loss even on restart.</p>
    </td>
  </tr>
</table>

### Full Feature List

| Category | Features |
|---|---|
| **Download Sources** | Direct links, Torrents (magnet & .torrent), Mega, Google Drive, Rclone remotes, Usenet (NZB), JDownloader, YouTube & 1800+ yt-dlp sites, Telegram files & links |
| **Upload Destinations** | Google Drive, Rclone remotes (OneDrive, Dropbox, S3, etc.), Telegram (as document or media), DDL hosters (GoFile, BuzzHeavier, PixelDrain) |
| **Leech Features** | Custom prefixes & suffixes, captions, auto-split for large files, hybrid leech (bot + user session), equal splits, media grouping, thumbnail layouts |
| **Media Processing** | FFmpeg integration, audio/video conversion (`-ca`, `-cv`), custom metadata injection (`-meta`), sample video generation (`-sv`), screenshot extraction (`-ss`), MediaInfo reports |
| **File Management** | Extract (`.zip`, `.rar`, `.7z`, `.tar`), archive with password, join split files, rename, auto-rename templates, name substitution via regex |
| **Search** | Torrent search via qBittorrent plugins, Google Drive search, Usenet/NZBHydra search, IMDB lookup |
| **Automation** | RSS feed monitoring with include/exclude filters, bulk download from text files, multi-link batch processing |
| **Streaming** | Built-in FileToLink web server with token-based access control, URL shortening, rate limiting, and multi-bot load balancing |
| **Admin Tools** | Shell access, async/sync Python exec, log retrieval, broadcast messaging, session restart, user management |

---

<a id="architecture"></a>

## 🧬 Architecture

```mermaid
graph TD
    A[Telegram User] -->|Commands / Files| B((Amaterasu Core))
    B --> C{Download Engines}
    C -->|Torrents| D[qBittorrent & Aria2c]
    C -->|Usenet| E[Sabnzbd]
    C -->|Direct/Links| F[JDownloader & yt-dlp]
    C -->|Cloud| M[Mega CMD]
    B --> G{Storage & Distribution}
    G -->|Cloud Drives| H[Google Drive & Rclone]
    G -->|Direct Download| I[FileToLink Server]
    G -->|Telegram| J[Leech Uploader]
    G -->|DDL Hosters| K[GoFile / BuzzHeavier / PixelDrain]
    B --> L[(MongoDB)]
    
    style B fill:#FF4500,stroke:#333,stroke-width:2px,color:#fff
    style A fill:#2496ED,color:#fff
    style I fill:#28a745,color:#fff
    style L fill:#4DB33D,color:#fff
```

### Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| Telegram Framework | Pyrogram (pyrotgfork 2.2.19) |
| Web Server | FastAPI + Uvicorn |
| Database | MongoDB (Motor async driver) |
| Containerization | Docker / Podman |
| Torrent Client | qBittorrent-nox + Aria2c |
| Usenet Client | Sabnzbd |
| Cloud Sync | Rclone |
| Media Toolkit | FFmpeg, yt-dlp, MediaInfo |

---

<a id="prerequisites"></a>

## ⚙️ Prerequisites

Before deploying Amaterasu, you will need:

| Requirement | Where to Get It | Notes |
|---|---|---|
| **Telegram API ID & Hash** | [my.telegram.org](https://my.telegram.org) | Create an application under "API Development Tools" |
| **Bot Token** | [@BotFather](https://t.me/BotFather) | Send `/newbot` and follow the prompts |
| **MongoDB URI** | [MongoDB Atlas](https://www.mongodb.com/atlas) (free tier) or self-hosted | Format: `mongodb+srv://user:pass@cluster.mongodb.net/dbname` |
| **Owner ID** | [@MissRose_bot](https://t.me/MissRose_bot) or [@userinfobot](https://t.me/userinfobot) | Send `/id` to get your numeric Telegram User ID |
| **VPS / Server** | Any Linux VPS (Ubuntu/Debian recommended) | Minimum: **1 CPU, 1 GB RAM, 20 GB disk** (2 GB+ RAM recommended for heavy media) |
| **Google Drive** *(optional)* | [Google Cloud Console](https://console.cloud.google.com) | Generate `token.pickle` or Service Account keys for GDrive uploads |
| **User Session String** *(optional)* | Generate with Pyrogram's `StringSession` | Needed for downloading restricted Telegram content or uploading files > 2 GB |

---

<a id="deployment"></a>

## 🚀 Deployment

### Step 1: Prepare Your Server

> [!IMPORTANT]
> **Minimum Requirements**: 1 vCPU, 1 GB RAM, 20 GB SSD.
> **Recommended**: 2 vCPU, 2+ GB RAM, 40+ GB SSD (for heavy media processing, FFmpeg, and extraction).

Connect to your VPS and install the container runtime of your choice:

<details>
  <summary><b>Install Docker + Docker Compose (Ubuntu/Debian)</b></summary>
  <br>

  ```bash
  # Update system
  sudo apt update && sudo apt upgrade -y

  # Install Docker
  curl -fsSL https://get.docker.com | sh

  # Install Docker Compose plugin
  sudo apt install docker-compose-plugin -y

  # Verify installation
  docker --version
  docker compose version
  ```
</details>

<details>
  <summary><b>Install Podman (Ubuntu/Debian)</b></summary>
  <br>

  ```bash
  sudo apt update && sudo apt upgrade -y
  sudo apt install podman -y

  # Verify installation
  podman --version
  ```
</details>

---

### Step 2: Clone & Configure

```bash
# Clone the repository
git clone https://github.com/its-niloy/Amaterasu.git && cd Amaterasu

# Create your config file from the sample
cp config_sample.py config.py

# Edit config with your credentials
nano config.py
```

Inside `config.py`, fill in the **5 mandatory variables** at minimum:

```python
# ==========================================
# 1. REQUIRED CONFIGURATION
# ==========================================
BOT_TOKEN = "123456:ABC-DEF1234..."       # From @BotFather
OWNER_ID = 123456789                       # Your numeric Telegram User ID
TELEGRAM_API = 12345678                    # From my.telegram.org
TELEGRAM_HASH = "0123456789abcdef..."      # From my.telegram.org
DATABASE_URL = "mongodb+srv://user:pass@cluster.mongodb.net/amaterasu"  # MongoDB URI
```

> [!TIP]
> You can also set these as **environment variables** instead of editing `config.py`. The bot checks both — environment variables take priority over the config file. This is useful for PaaS deployments.

---

### Step 3: Optional Files Setup

These files are **not required** but unlock additional functionality. Place them in the project root directory (`/Amaterasu/`).

| File | Purpose | How to Generate |
|---|---|---|
| `token.pickle` | Google Drive authentication (OAuth2 token) | Run the Google OAuth flow using the [Google API Console](https://console.cloud.google.com). Create OAuth credentials → download `credentials.json` → run `python3 gen_scripts/generate_token.py` |
| `accounts.zip` | Service Account keys for GDrive (bypasses quota limits) | Create multiple Service Accounts in GCP → download JSON keys → zip all `.json` files into `accounts.zip` |
| `rclone.conf` | Rclone remote configurations for cloud storage | Run `rclone config` on your local machine → copy `~/.config/rclone/rclone.conf` to the project |
| `cookies.txt` | Browser cookies for authenticated site downloads | Export cookies from your browser using a "Get cookies.txt" extension (Netscape format) |
| `.netrc` | Machine-level login credentials for FTP/HTTP sites | Create manually: `machine host login user password pass` |
| `list_drives.txt` | Multiple GDrive destinations with labels | Format: `Drive Name gdrive_folder_id index_url` (one per line) |
| `shortener.txt` | URL shortener configuration | Format per line: `domain shortener_api_url shortener_api_key` |

> [!NOTE]
> All of these can also be uploaded later via the `/bsetting` (Bot Settings) panel in Telegram — no server SSH required.

---

### Step 4: Build & Launch

Choose one of the following deployment methods:

#### Method A: Docker Compose ⭐ (Recommended)

```bash
# Build the image and start in detached mode
sudo docker compose up --build -d

# Watch live logs
sudo docker compose logs -f
```

The `docker-compose.yml` is pre-configured with:
- **`network_mode: host`** — the container shares your server's network stack directly (no port mapping needed, qBittorrent/Aria2c work without extra config).
- **`restart: always`** — auto-restarts on crash or server reboot.
- **Volume mount** (`.:/usr/src/app:z`) — your local `config.py`, `token.pickle`, etc. are live-synced into the container.

#### Method B: Docker (Manual)

```bash
# Build the image
sudo docker build -t amaterasu .

# Run with host networking (recommended for torrents)
sudo docker run -d --name amaterasu --restart always --network host \
  -v $(pwd):/usr/src/app:z \
  -e TZ=Asia/Dhaka \
  amaterasu

# View logs
sudo docker logs -f amaterasu
```

#### Method C: Podman

```bash
# Build the image
sudo podman build -t amaterasu .

# Run with auto-restart and port mapping
sudo podman run -d --name amaterasu --restart always \
  --network host \
  -v $(pwd):/usr/src/app:z \
  amaterasu

# View logs
sudo podman logs -f amaterasu
```

#### Method D: Cloud Platforms (Heroku / Railway / Render / CapRover)

1. **Fork** this repository to your GitHub account.
2. **Connect** your PaaS dashboard to the forked repo.
3. **Set environment variables** matching the mandatory config variables (`BOT_TOKEN`, `OWNER_ID`, `TELEGRAM_API`, `TELEGRAM_HASH`, `DATABASE_URL`).
4. **Deploy** — the `Dockerfile` and `captain-definition` handle everything automatically.

> [!WARNING]
> Most free-tier PaaS platforms have ephemeral storage. Files will be lost on restart. Use MongoDB-backed config (the default) and cloud storage (GDrive/Rclone) instead of local paths.

---

<a id="what-happens-on-boot"></a>

### 🔄 What Happens on Boot?

When the container starts, Amaterasu executes a precise boot sequence:

```
start.sh → update.py → python3 -m bot
```

| Step | What It Does |
|---|---|
| **1. Auto-Update** | Pulls the latest code from `UPSTREAM_REPO` / `UPSTREAM_BRANCH` (resets local changes to match remote) |
| **2. Package Update** | Runs `uv pip install -U -r requirements.txt` to sync Python dependencies (disable with `UPDATE_PKGS = False`) |
| **3. Config Import** | Loads `config.py` → merges with saved config from MongoDB → environment variables override both |
| **4. Engine Boot** | Starts Aria2c (with auto-fetched tracker lists), qBittorrent-nox, Sabnzbd, and JDownloader (if configured) |
| **5. Telegram Connect** | Initializes the bot client, user session(s), and helper/stream bot tokens |
| **6. FileToLink Server** | Launches the FastAPI + Uvicorn web server on the configured `PORT` |
| **7. Ready** | Registers command handlers and begins responding to Telegram messages |

> [!NOTE]
> Because of Step 1, the bot **automatically updates itself** on every restart. If you push a commit to your `UPSTREAM_REPO`, simply restart the bot (or send `/restart` in Telegram) and it will pull the latest changes.

---

<a id="reverse-proxy-setup"></a>

### 🌐 Reverse Proxy Setup (Optional)

If you want to serve the FileToLink streaming server over HTTPS with a custom domain:

<details>
  <summary><b>Nginx Example</b></summary>
  <br>

  ```nginx
  server {
      listen 443 ssl http2;
      server_name stream.yourdomain.com;

      ssl_certificate /etc/letsencrypt/live/stream.yourdomain.com/fullchain.pem;
      ssl_certificate_key /etc/letsencrypt/live/stream.yourdomain.com/privkey.pem;

      location / {
          proxy_pass http://127.0.0.1:83;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
          proxy_buffering off;        # Required for streaming
          proxy_request_buffering off;
      }
  }
  ```

  Then in `config.py`:
  ```python
  FQDN = "stream.yourdomain.com"
  HAS_SSL = True
  NO_PORT = True   # Nginx handles the port
  PORT = 83        # Internal port (not exposed publicly)
  ```
</details>

<details>
  <summary><b>Caddy Example (Auto-SSL)</b></summary>
  <br>

  ```
  stream.yourdomain.com {
      reverse_proxy localhost:83
  }
  ```

  Caddy automatically provisions and renews SSL certificates. Set the same `config.py` values as the Nginx example.
</details>

---

<a id="maintenance--operations"></a>

### 🛠️ Maintenance & Operations

| Action | Docker Compose | Podman | Direct Docker |
|---|---|---|---|
| **Stop** | `sudo docker compose stop` | `sudo podman stop amaterasu` | `sudo docker stop amaterasu` |
| **Start** | `sudo docker compose start` | `sudo podman start amaterasu` | `sudo docker start amaterasu` |
| **Restart** | `sudo docker compose restart` | `sudo podman restart amaterasu` | `sudo docker restart amaterasu` |
| **Rebuild** | `sudo docker compose up --build -d` | `sudo podman build -t amaterasu . && podman run ...` | `sudo docker build -t amaterasu . && docker run ...` |
| **View Logs** | `sudo docker compose logs -f` | `sudo podman logs -f amaterasu` | `sudo docker logs -f amaterasu` |
| **Shell Into** | `sudo docker compose exec amaterasu bash` | `sudo podman exec -it amaterasu bash` | `sudo docker exec -it amaterasu bash` |
| **Disk Cleanup** | `sudo docker system prune -af` | `sudo podman system prune -af` | `sudo docker system prune -af` |

> [!TIP]
> **Quick Update Workflow**: You don't need to rebuild the container to update the bot. Simply restart it — the auto-update system (`update.py`) pulls the latest code from your `UPSTREAM_REPO` on every boot. Only rebuild if you've changed the `Dockerfile`, `requirements.txt`, or system-level dependencies.

---

<a id="configuration-reference"></a>

## 🔧 Configuration Reference

All variables go inside `config.py`. Copy `config_sample.py` as your starting template.

### 1. Required (Mandatory)

| Variable | Type | Description |
|---|---|---|
| `BOT_TOKEN` | `str` | Bot token from [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | `int` | Your Telegram User ID (numeric) |
| `TELEGRAM_API` | `int` | API ID from [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_HASH` | `str` | API Hash from [my.telegram.org](https://my.telegram.org) |
| `DATABASE_URL` | `str` | MongoDB connection string |

### 2. Telegram Client & Sessions

| Variable | Type | Default | Description |
|---|---|---|---|
| `USER_SESSION_STRING` | `str` | `""` | Pyrogram string session for a user account. Required for restricted content downloads and uploads >2 GB |
| `HELPER_TOKENS` | `str` | `""` | Additional bot tokens for FileToLink load balancing (space-separated) |
| `DEFAULT_LANG` | `str` | `""` | Default language code for the bot |
| `TG_PROXY` | `dict` | `{}` | Proxy config for Pyrogram (`{"scheme": "socks5", "hostname": "...", "port": ...}`) |
| `BOT_PM` | `bool` | `False` | If `True`, bot sends task completion messages in PM |
| `BOT_MAX_TASKS` | `int` | `0` | Global maximum concurrent tasks (0 = unlimited) |
| `USER_MAX_TASKS` | `int` | `0` | Per-user maximum concurrent tasks |
| `USER_TIME_INTERVAL` | `int` | `0` | Minimum seconds between user commands (anti-spam) |
| `VERIFY_TIMEOUT` | `int` | `0` | Verification timeout in seconds |
| `LOGIN_PASS` | `str` | `""` | Password for `/login` command (restricts unauthorized access) |
| `SET_COMMANDS` | `bool` | `False` | If `True`, registers bot commands in Telegram's command menu |
| `TIMEZONE` | `str` | `""` | Timezone string (e.g., `Asia/Dhaka`) |

### 3. Chat & Permissions

| Variable | Type | Default | Description |
|---|---|---|---|
| `CMD_SUFFIX` | `str` | `""` | Suffix appended to all commands (useful when running multiple bot instances) |
| `AUTHORIZED_CHATS` | `str` | `""` | Space-separated chat IDs where bot will respond |
| `SUDO_USERS` | `str` | `""` | Space-separated user IDs with elevated privileges |
| `FORCE_SUB_IDS` | `str` | `""` | Channel IDs users must join before using the bot |
| `BANNED_CHANNELS` | `str` | `""` | Blocked channel IDs |

### 4. Leech & Upload Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `DEFAULT_UPLOAD` | `str` | `""` | Default upload mode: `gd` (Google Drive), `rc` (Rclone), or leave empty for Telegram |
| `LEECH_SPLIT_SIZE` | `int` | `0` | Max file size per split in bytes (0 = Telegram default: 2 GB for premium, 4 GB for bots) |
| `AS_DOCUMENT` | `bool` | `False` | Upload files as documents instead of media (preserves original filename) |
| `EQUAL_SPLITS` | `bool` | `False` | Split files into equal-sized parts instead of Telegram's default |
| `MEDIA_GROUP` | `bool` | `False` | Send split files as a media group (album) |
| `USER_TRANSMISSION` | `bool` | `False` | Use user session for uploads by default |
| `HYBRID_LEECH` | `bool` | `False` | Upload via both bot and user session based on file size |
| `LEECH_PREFIX` | `str` | `""` | Text prepended to every uploaded filename |
| `LEECH_SUFFIX` | `str` | `""` | Text appended to every uploaded filename |
| `LEECH_FONT` | `str` | `""` | Font style for leech filenames |
| `LEECH_CAPTION` | `str` | `""` | Custom caption template for uploaded files |
| `THUMBNAIL_LAYOUT` | `str` | `""` | Default thumbnail layout (e.g., `3x3`) |
| `EXCLUDED_EXTENSIONS` | `str` | `""` | Space-separated file extensions to skip during upload |

### 5. Google Drive

| Variable | Type | Default | Description |
|---|---|---|---|
| `GDRIVE_ID` | `str` | `""` | Default Google Drive folder ID for mirror uploads |
| `GD_DESP` | `str` | `""` | Description text for the GDrive destination |
| `IS_TEAM_DRIVE` | `bool` | `False` | Set `True` if `GDRIVE_ID` is a Shared/Team Drive |
| `STOP_DUPLICATE` | `bool` | `False` | Check for duplicate files on GDrive before uploading |
| `INDEX_URL` | `str` | `""` | GDrive Index URL for generating direct links |
| `USE_SERVICE_ACCOUNTS` | `bool` | `False` | Use Service Account JSON files for GDrive operations |

### 6. Rclone

| Variable | Type | Default | Description |
|---|---|---|---|
| `RCLONE_PATH` | `str` | `""` | Default Rclone remote path (e.g., `remote:path/to/folder`) |
| `RCLONE_FLAGS` | `str` | `""` | Extra Rclone flags applied to all operations |
| `RCLONE_SERVE_URL` | `str` | `""` | URL for Rclone serve |
| `SHOW_CLOUD_LINK` | `bool` | `False` | Show cloud link after mirror upload |
| `RCLONE_SERVE_PORT` | `int` | `0` | Port for Rclone serve |
| `RCLONE_SERVE_USER` | `str` | `""` | Basic auth username for Rclone serve |
| `RCLONE_SERVE_PASS` | `str` | `""` | Basic auth password for Rclone serve |

### 7. Download Size Limits

All limits are in **GB**. Set `0` to disable the limit.

| Variable | Description |
|---|---|
| `DIRECT_LIMIT` | Max size for direct link downloads |
| `MEGA_LIMIT` | Max size for Mega downloads |
| `TORRENT_LIMIT` | Max size for torrent downloads |
| `GD_DL_LIMIT` | Max size for GDrive downloads |
| `RC_DL_LIMIT` | Max size for Rclone downloads |
| `CLONE_LIMIT` | Max size for clone operations |
| `JD_LIMIT` | Max size for JDownloader downloads |
| `NZB_LIMIT` | Max size for Usenet downloads |
| `YTDLP_LIMIT` | Max size for yt-dlp downloads |
| `PLAYLIST_LIMIT` | Max number of videos in a YouTube playlist |
| `LEECH_LIMIT` | Max total size for leech operations |
| `EXTRACT_LIMIT` | Max size for extraction operations |
| `ARCHIVE_LIMIT` | Max size for archive/zip operations |
| `STORAGE_LIMIT` | Max total storage usage on server |

### 8. Torrent / Aria2c / qBittorrent

| Variable | Type | Default | Description |
|---|---|---|---|
| `DISABLE_TORRENTS` | `bool` | `False` | Completely disable torrent functionality |
| `DISABLE_SEED` | `bool` | `False` | Disable seeding after torrent download |
| `TORRENT_TIMEOUT` | `int` | `0` | Timeout for torrent downloads in seconds |
| `BASE_URL` | `str` | `""` | Base URL for the web server (e.g., `http://your-ip:8080`) |
| `BASE_URL_PORT` | `int` | `0` | Port for the web server |
| `WEB_PINCODE` | `bool` | `False` | Enable pincode verification for torrent file selection |
| `QUEUE_ALL` | `int` | `0` | Max total tasks in queue (0 = unlimited) |
| `QUEUE_DOWNLOAD` | `int` | `0` | Max concurrent downloads |
| `QUEUE_UPLOAD` | `int` | `0` | Max concurrent uploads |

### 9. JDownloader & Usenet

| Variable | Type | Default | Description |
|---|---|---|---|
| `JD_EMAIL` | `str` | `""` | MyJDownloader account email |
| `JD_PASS` | `str` | `""` | MyJDownloader account password |
| `MEGA_EMAIL` | `str` | `""` | Mega.nz account email |
| `MEGA_PASSWORD` | `str` | `""` | Mega.nz account password |
| `USENET_SERVERS` | `list` | `[]` | List of Usenet server configurations for Sabnzbd |

### 10. Media & Search

| Variable | Type | Default | Description |
|---|---|---|---|
| `IMDB_TEMPLATE` | `str` | `""` | Custom HTML template for IMDB results |
| `INSTADL_API` | `str` | `""` | Instagram downloader API endpoint |
| `HYDRA_IP` | `str` | `""` | NZBHydra2 IP address for Usenet search |
| `HYDRA_API_KEY` | `str` | `""` | NZBHydra2 API key |
| `SEARCH_API_LINK` | `str` | `""` | Torrent search API URL |
| `SEARCH_LIMIT` | `int` | `0` | Max search results to display |
| `SEARCH_PLUGINS` | `list` | `[]` | qBittorrent search plugin URLs |

### 11. YouTube Tools

| Variable | Type | Default | Description |
|---|---|---|---|
| `YT_DLP_OPTIONS` | `str` | `""` | Default yt-dlp options in JSON format |
| `YT_DESP` | `str` | `""` | Default description for YouTube uploads |
| `YT_TAGS` | `list` | `[]` | Default tags for YouTube uploads |
| `YT_CATEGORY_ID` | `int` | `0` | YouTube category ID |
| `YT_PRIVACY_STATUS` | `str` | `""` | YouTube upload privacy (`public`, `unlisted`, `private`) |

### 12. Log Channels & Notifications

| Variable | Type | Default | Description |
|---|---|---|---|
| `LEECH_DUMP_CHAT` | `str` | `""` | Chat ID where leeched files are dumped (e.g., `-100123456789`) |
| `LINKS_LOG_ID` | `str` | `""` | Chat ID for logging generated links |
| `MIRROR_LOG_ID` | `str` | `""` | Chat ID for logging mirror uploads |
| `STATUS_LIMIT` | `int` | `0` | Max number of tasks shown per status page |
| `STATUS_UPDATE_INTERVAL` | `int` | `0` | Seconds between status message updates |
| `INCOMPLETE_TASK_NOTIFIER` | `bool` | `False` | Notify about incomplete tasks on restart |
| `CLEAN_LOG_MSG` | `bool` | `False` | Clean log messages after task completion |
| `DELETE_LINKS` | `bool` | `False` | Delete user's link message after processing |
| `MEDIA_STORE` | `bool` | `False` | Store media metadata |

### 13. FileToLink Streaming

| Variable | Type | Default | Description |
|---|---|---|---|
| `BIN_CHANNEL` | `int` | `0` | Telegram channel ID used as file storage backend |
| `MAX_BATCH_FILES` | `int` | `0` | Max files per batch operation |
| `CHANNEL` | `bool` | `False` | Enable channel mode |
| `MULTI_TOKEN1..3` | `str` | `""` | Additional bot tokens for load balancing |
| `TOKEN_ENABLED` | `bool` | `False` | Enable token-based access for stream links |
| `TOKEN_TTL_HOURS` | `int` | `0` | Token expiry time in hours |
| `SHORTEN_ENABLED` | `bool` | `False` | Enable URL shortening for stream links |
| `GLOBAL_RATE_LIMIT` | `bool` | `False` | Enable global rate limiting |
| `RATE_LIMIT_ENABLED` | `bool` | `False` | Enable per-session rate limiting |

### 14. Web Server

| Variable | Type | Default | Description |
|---|---|---|---|
| `FQDN` | `str` | `""` | Fully Qualified Domain Name for the streaming server |
| `HAS_SSL` | `bool` | `False` | Set `True` if using HTTPS |
| `PORT` | `int` | `0` | Server port |
| `NO_PORT` | `bool` | `False` | If `True`, don't append port to URLs (when behind reverse proxy) |
| `WORKERS` | `int` | `0` | Number of Uvicorn worker processes |

### 15. Miscellaneous

| Variable | Type | Default | Description |
|---|---|---|---|
| `NAME_SWAP` | `str` | `""` | Default name substitution rules |
| `FFMPEG_CMDS` | `dict` | `{}` | Pre-defined FFmpeg command presets |
| `UPLOAD_PATHS` | `dict` | `{}` | Named upload path shortcuts |
| `DISABLE_LEECH` | `bool` | `False` | Disable all leech functionality |
| `DISABLE_BULK` | `bool` | `False` | Disable bulk download feature |
| `DISABLE_MULTI` | `bool` | `False` | Disable multi-link feature |
| `DISABLE_FF_MODE` | `bool` | `False` | Disable FFmpeg processing |
| `UPSTREAM_REPO` | `str` | GitHub URL | Repository URL for auto-updates on restart |
| `UPSTREAM_BRANCH` | `str` | `main` | Branch to pull updates from |
| `UPDATE_PKGS` | `bool` | `True` | Auto-update pip packages on restart |
| `RSS_DELAY` | `int` | `0` | Seconds between RSS feed checks |
| `RSS_CHAT` | `str` | `""` | Chat ID for RSS notifications |
| `RSS_SIZE_LIMIT` | `int` | `0` | Max file size for RSS auto-downloads |

---

<a id="command-reference"></a>

## 📖 Command Reference

<a id="mirror-commands"></a>

### ☁️ Mirror Commands (Download → Cloud Drive)

| Command | Shortcut | Description |
|---|---|---|
| `/mirror` | `/m` | Download a link, torrent file, or magnet → upload to cloud drive (GDrive/Rclone) |
| `/qbmirror` | `/qm` | Same as mirror but forces qBittorrent engine (best for torrents) |
| `/jdmirror` | `/jm` | Same as mirror but forces JDownloader engine |
| `/nzbmirror` | `/nm` | Download a `.nzb` file via Sabnzbd → upload to cloud |
| `/ytdl` | `/y` | Download from YouTube or 1800+ sites via yt-dlp → upload to cloud |
| `/clone` | `/cl` | Copy a Google Drive / Rclone file or folder directly to your drive |

<a id="leech-commands"></a>

### 📥 Leech Commands (Download → Telegram)

| Command | Shortcut | Description |
|---|---|---|
| `/leech` | `/l` | Download a link/torrent → upload directly to Telegram |
| `/qbleech` | `/ql` | Leech using qBittorrent engine |
| `/jdleech` | `/jl` | Leech using JDownloader engine |
| `/nzbleech` | `/nl` | Leech a `.nzb` via Sabnzbd → upload to Telegram |
| `/ytdlleech` | `/yl` | Download from YouTube/yt-dlp sites → upload to Telegram |

<a id="upload-hoster-commands"></a>

### 📤 Upload Hoster Commands

| Command | Shortcut | Description |
|---|---|---|
| `/uphoster` | `/up` | Download a link → upload to DDL servers (GoFile, BuzzHeavier, PixelDrain) |

<a id="search--info-commands"></a>

### 🔍 Search & Info Commands

| Command | Shortcut | Description |
|---|---|---|
| `/list` | — | Search your Google Drive(s) for files/folders |
| `/search` | — | Search torrents via installed qBittorrent search plugins |
| `/nzbsearch` | `/ns` | Search Usenet via NZBHydra2 |
| `/imdb` | — | Look up a movie or TV show on IMDB |
| `/count` | — | Count files/folders in a Google Drive link |
| `/mediainfo` | `/mi` | Get detailed MediaInfo for a file (reply or link) |

<a id="task-management"></a>

### ⚙️ Task Management

| Command | Shortcut | Description |
|---|---|---|
| `/status` | `/s` | View live dashboard of all active downloads/uploads |
| `/cancel` | `/c` | Cancel a specific task (by GID or reply) |
| `/cancelall` | `/call` | Cancel all active tasks (with confirmation) |
| `/forcestart` | `/fs` | Force a queued task to start immediately |
| `/select` | `/sel` | Select specific files from a torrent/NZB to download |

<a id="user-commands"></a>

### 👤 User Commands

| Command | Shortcut | Description |
|---|---|---|
| `/usetting` | `/us` | Open your personal settings panel (thumbnail, prefix, upload destination, etc.) |
| `/stats` | `/st` | View server hardware stats (CPU, RAM, Disk, Network) |
| `/ping` | — | Check bot response latency |
| `/help` | `/h` | Show all available commands with descriptions |
| `/login` | — | Authenticate with bot password (if `LOGIN_PASS` is set) |

<a id="media--file-tools"></a>

### 🎬 Media & File Tools

| Command | Shortcut | Description |
|---|---|---|
| `/link` | `/stream`, `/f2l` | Generate direct stream/download links for Telegram files |
| `/rename` | `/renamemode` | Toggle rename mode or rename a specific file (reply to it) |
| `/autorename` | `/ar` | Set up or use an auto-rename template |
| `/telegraph` | `/tg` | Upload an image or video (under 5 MB) to Telegraph and get a permanent link |
| `/speedtest` | `/stest` | Run a server speed test via speedtest.net |

<a id="admin--sudo-commands"></a>

### 🔐 Admin / Sudo Commands

| Command | Shortcut | Permission | Description |
|---|---|---|---|
| `/bsetting` | `/bs` | Sudo | Open the bot configuration dashboard |
| `/authorize` | `/a` | Sudo | Authorize a chat or user |
| `/unauthorize` | `/ua` | Sudo | Revoke authorization |
| `/addsudo` | `/as` | Sudo | Grant sudo privileges to a user |
| `/rmsudo` | `/rs` | Sudo | Revoke sudo privileges |
| `/users` | — | Sudo | View all registered users and their settings |
| `/broadcast` | `/bc` | Sudo | Send a message to all bot users |
| `/log` | — | Sudo | Download the bot's log file |
| `/shell` | — | Sudo | Execute a shell command on the server |
| `/exec` | — | Sudo | Execute synchronous Python code |
| `/aexec` | — | Sudo | Execute asynchronous Python code |
| `/restart` | `/r` | Sudo | Restart the bot (pulls updates if `UPSTREAM_REPO` is set) |
| `/restartses` | `/rses` | Sudo | Restart all user/helper sessions |
| `/rss` | — | Authorized | Open the RSS feed management panel |

---

<a id="advanced-usage--arguments"></a>

## 🧰 Advanced Usage & Arguments

Every mirror/leech command supports powerful inline arguments. Combine them freely:

```
/mirror https://example.com/file.zip -n "My File" -e -up gdl
```

### Argument Quick Reference

| Argument | Purpose | Example |
|---|---|---|
| `-n [name]` | Rename the downloaded file | `/mirror link -n MyMovie.mkv` |
| `-e [password]` | Extract archive (optional password) | `/leech link -e secretpass` |
| `-z [password]` | Compress into ZIP (optional password) | `/mirror link -z mypassword` |
| `-up [dest]` | Override upload destination | `/mirror link -up gdl` or `-up rc` or `-up @channel` |
| `-s` | Show quality/file selection buttons | `/ytdl link -s` |
| `-i [count]` | Multi-link: process N consecutive messages | `/mirror -i 5` |
| `-b` | Bulk: process links from a text file/message | `/leech -b` |
| `-m [folder]` | Move all downloads into a single folder | `/mirror -i 3 -m MyFolder` |
| `-j` | Join split files before processing | `/mirror link -j` |
| `-d [ratio:time]` | Seed torrent (ratio and/or time in minutes) | `/qbmirror link -d 1.0:60` |
| `-t [url]` | Custom thumbnail for this task | `/leech link -t https://img.url/thumb.jpg` |
| `-sp [size]` | Custom split size | `/leech link -sp 500mb` |
| `-sv [dur:part]` | Generate sample video | `/leech link -sv 60:4` |
| `-ss [count]` | Take screenshots | `/leech link -ss 10` |
| `-ca [format]` | Convert audio to format | `/leech link -ca mp3` |
| `-cv [format]` | Convert video to format | `/leech link -cv mp4` |
| `-meta [data]` | Inject metadata (pipe-separated) | `/mirror link -meta title=My Movie\|year=2024` |
| `-ff [preset]` | Apply FFmpeg preset | `/leech link -ff subtitle` |
| `-ns [rules]` | Name substitution rules | `/mirror link -ns old/new/s` |
| `-rcf [flags]` | Rclone flags override | `/mirror link -rcf --buffer-size:8M` |
| `-f` | Force start (bypass queue) | `/mirror link -f` |
| `-fd` | Force download only | `/mirror link -fd` |
| `-fu` | Force upload only | `/mirror link -fu` |
| `-doc` | Force upload as document | `/leech link -doc` |
| `-med` | Force upload as media | `/leech link -med` |
| `-bt` | Leech via bot session | `/leech link -bt` |
| `-ut` | Leech via user session | `/leech link -ut` |
| `-hl` | Hybrid leech (auto bot/user) | `/leech link -hl` |
| `-tl [WxH]` | Thumbnail layout | `/leech link -tl 3x3` |
| `-au [user]` | Direct link auth username | `/mirror link -au admin` |
| `-ap [pass]` | Direct link auth password | `/mirror link -ap secret` |
| `-h [headers]` | Custom HTTP headers | `/mirror link -h Referer: https://site.com` |

### Telegram Link Downloads

The bot can download files from Telegram links directly:

```
/mirror https://t.me/channel_name/123          # Public channel
/mirror tg://openmessage?user_id=123&message_id=456   # Private message
/mirror https://t.me/c/123456/789              # Private channel (needs USER_SESSION_STRING)
/mirror https://t.me/channel_name/100-150      # Range download (messages 100 to 150)
```

### Rclone Paths

Use Rclone paths exactly like links:

```
/mirror remote:path/to/file.iso               # Download from Rclone remote
/mirror rcl                                    # Interactive remote/path selection
/mirror mrcc:myremote:path                     # Use your personal Rclone config (from /usetting)
```

### Upload Destination Shortcuts

| Prefix | Meaning |
|---|---|
| `gdl` | Upload using GDrive (interactive folder picker) |
| `gd` | Upload to default `GDRIVE_ID` |
| `rc` | Upload to default `RCLONE_PATH` |
| `rcl` | Upload using Rclone (interactive remote picker) |
| `tp:id` | Upload to GDrive ID using token.pickle |
| `sa:id` | Upload to GDrive ID using Service Accounts |
| `mtp:id` | Upload using your personal token.pickle (from /usetting) |
| `mrcc:path` | Upload using your personal Rclone config (from /usetting) |
| `b:@channel` | Leech to channel via bot session |
| `u:@channel` | Leech to channel via user session |
| `h:@channel` | Hybrid leech to channel |
| `pm` | Leech to your private messages |

---

<a id="filetolink-streaming-server"></a>

## 🌐 FileToLink Streaming Server

Amaterasu includes a built-in FastAPI web server that converts any Telegram file into a direct HTTP stream link.

### How It Works
1. Reply to any file in Telegram with `/link` (or `/stream` or `/f2l`).
2. The bot generates a direct download URL and a streaming URL.
3. These links are **seekable** (HTTP 206 Range Requests), meaning you can play videos directly in VLC, MX Player, or any browser without downloading the full file.

### Multi-Token Load Balancing
Configure `MULTI_TOKEN1`, `MULTI_TOKEN2`, `MULTI_TOKEN3` with additional bot tokens. The server automatically distributes file requests across tokens to avoid Telegram's FloodWait rate limits.

### Access Control
| Feature | Variable | Description |
|---|---|---|
| Token Authentication | `TOKEN_ENABLED` | Require a token parameter in stream URLs |
| Token Expiry | `TOKEN_TTL_HOURS` | Auto-expire tokens after N hours |
| URL Shortening | `SHORTEN_ENABLED` | Shorten generated links via a URL shortener |
| Global Rate Limit | `GLOBAL_RATE_LIMIT` | Cap total requests per minute |
| Session Rate Limit | `RATE_LIMIT_ENABLED` | Cap requests per user session |

---

<a id="rss-automation"></a>

## 📡 RSS Automation

The built-in RSS module monitors feeds and auto-downloads new entries matching your filters.

### Setup
1. Send `/rss` to open the RSS management panel.
2. Add feeds with the format:

```
Title https://rss-feed-url.com -c /mirror -inf 1080|mkv -exf cam|ts
```

### Filter Syntax
- **`-inf`** (Include Filter): Only download titles matching these words.
- **`-exf`** (Exclude Filter): Skip titles containing these words.
- **`|`** means AND between groups.
- **`or`** means OR within a group.
- **`-stv true`** for case-sensitive matching.

### Example
```
Anime https://nyaa.si/?page=rss -c /qbleech -inf 1080p|mkv or mp4 -exf batch|DVD
```
This auto-leeches new anime releases in 1080p (mkv or mp4), excluding batch packs and DVDs.

---

<a id="user-roles--permissions"></a>

## 🔑 User Roles & Permissions

| Role | How to Assign | Capabilities |
|---|---|---|
| **Owner** | Set `OWNER_ID` in config | Full access: all commands, shell, exec, bot settings, user management |
| **Sudo** | `/addsudo [user_id]` or set `SUDO_USERS` in config | Admin commands: bot settings, authorize, restart, broadcast, logs |
| **Authorized** | `/authorize [chat_id]` or set `AUTHORIZED_CHATS` in config | All download, leech, search, and user commands |
| **Unauthorized** | Default | Only `/start` and `/login` (if password is set) |

---

<a id="faq--troubleshooting"></a>

## ❓ FAQ & Troubleshooting

<details>
  <summary><b>The bot starts but doesn't respond to commands</b></summary>
  <br>

  - Verify `BOT_TOKEN` is correct.
  - Check that your chat is authorized (add your chat ID to `AUTHORIZED_CHATS`).
  - Ensure `CMD_SUFFIX` matches what you're typing (e.g., if `CMD_SUFFIX = "1"`, use `/mirror1`).
  - Review logs: `sudo docker-compose logs -f`
</details>

<details>
  <summary><b>Google Drive upload fails with "Permission Denied"</b></summary>
  <br>

  - Make sure `token.pickle` is valid and not expired.
  - If using Service Accounts, verify the SA email has Editor access to your Drive folder.
  - Set `IS_TEAM_DRIVE = True` if your `GDRIVE_ID` is a Shared Drive.
</details>

<details>
  <summary><b>Files larger than 2 GB fail to upload to Telegram</b></summary>
  <br>

  - You need `USER_SESSION_STRING` from a Telegram Premium account.
  - Or set `LEECH_SPLIT_SIZE` to a value below 2 GB to auto-split files.
</details>

<details>
  <summary><b>"Unclosed client session" errors in logs</b></summary>
  <br>

  - These are cosmetic warnings from aiohttp when the bot shuts down abruptly (e.g., due to a crash or container restart). They do not affect functionality. Fix the root cause of the crash (check for `SyntaxError` or `ImportError` above the warning).
</details>

<details>
  <summary><b>Torrent downloads stuck at 0%</b></summary>
  <br>

  - Ensure your server's firewall allows incoming connections on the torrent port.
  - Try switching between Aria2c (`/mirror`) and qBittorrent (`/qbmirror`).
  - Set `TORRENT_TIMEOUT` to auto-cancel stalled downloads.
</details>

<details>
  <summary><b>JDownloader not connecting</b></summary>
  <br>

  - Verify `JD_EMAIL` and `JD_PASS` match your MyJDownloader account.
  - The JDownloader headless instance takes ~30 seconds to boot inside Docker. Check logs for "JDownloader connected" message.
</details>

<details>
  <summary><b>FileToLink stream URLs not working</b></summary>
  <br>

  - Set `FQDN` to your server's public IP or domain.
  - Set `PORT` to match your Docker port mapping.
  - If behind a reverse proxy (Nginx/Caddy), set `HAS_SSL = True` and `NO_PORT = True`.
</details>

<details>
  <summary><b>How to generate a Pyrogram String Session?</b></summary>
  <br>

  ```python
  from pyrogram import Client

  app = Client("my_account", api_id=YOUR_API_ID, api_hash="YOUR_API_HASH")

  with app:
      print(app.export_session_string())
  ```

  Run this script locally (not on the server), enter your phone number and OTP, and save the printed string as `USER_SESSION_STRING`.
</details>

---

<div align="center">

### 🌟 Star History

If Amaterasu powers your workflow, please consider giving it a ⭐!

**[ ☀️ Awaken the Sun. Deploy Amaterasu Today. ☀️ ]**

*Built with ❤️ by [its-niloy](https://github.com/its-niloy)*

</div>
