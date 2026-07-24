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
  <a href="#"><img src="https://img.shields.io/badge/Version-1.6.4-orange?style=for-the-badge&logo=rocket"></a>
  <a href="#"><img src="https://img.shields.io/github/repo-size/Zan-getsu/Amaterasu?color=FF4500&label=Size&style=for-the-badge"></a>
  <a href="#"><img src="https://img.shields.io/github/license/Zan-getsu/Amaterasu?style=for-the-badge&color=FF8C00"></a>
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
  - [Cloudflare Tunnel Setup](#cloudflare-tunnel-setup)
  - [Maintenance & Operations](#maintenance--operations)
- [🔧 Configuration Reference](#configuration-reference)
  - [1. Required](#1-required-mandatory)
  - [2. Telegram Client & Sessions](#2-telegram-client--sessions)
  - [3. Chat & Permissions](#3-chat--permissions)
  - [4. Leech & Upload Settings](#4-leech--upload-settings)
  - [HyperDL / HyperUP Setup](#hyperdl--hyperup-setup)
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
  - [Drive Purge Manager](#drive-purge-manager)
- [🎞️ Encoding & Metadata](#encoding--metadata)
- [🎭 Auto-Rename Engine](#auto-rename)
- [🗂️ File Sorting Mode](#file-sorting-mode)
- [🎨 Encoding Profile Creator (Web UI)](#encoding-profile-creator-web-ui)
- [🔐 Google Token Generator (Web UI)](#google-token-generator-web-ui)
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
      <h3>🎭 Auto-Rename Engine</h3>
      <p>Intercept any leech task or upload to automatically rename it before uploading. Supports robust auto-rename templates (e.g. <code>/autorename</code>) for batch operations and dynamic media grouping.</p>
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
| **Upload Destinations** | Google Drive, Rclone remotes (OneDrive, Dropbox, S3, etc.), Telegram (as document or media), DDL hosters (GoFile, BuzzHeavier, PixelDrain, DevUploads, VikingFile) |
| **Leech Features** | Custom prefixes & suffixes, captions, auto-split for large files, hybrid leech (bot + user session), equal splits, media grouping, thumbnail layouts |
| **Media Processing** | FFmpeg integration, audio/video conversion (`-ca`, `-cv`), custom metadata injection (`-meta`), sample video generation (`-sv`), screenshot extraction (`-ss`), MediaInfo reports |
| **File Management** | Extract (`.zip`, `.rar`, `.7z`, `.tar`), archive with password, join split files, rename, auto-rename templates, name substitution via regex |
| **Search** | Torrent search via qBittorrent plugins, Google Drive search, Usenet/NZBHydra search, IMDB lookup |
| **Automation** | RSS feed monitoring with include/exclude filters, bulk download from text files, multi-link batch processing |
| **Streaming** | Built-in FileToLink web server with token-based access control, URL shortening, rate limiting, and multi-bot load balancing |
| **Admin Tools** | Shell access, async/sync Python exec, log retrieval, broadcast messaging, session restart, user management |
| **Runtime** | Python Telegram bot + web UI |
| **Deployment** | Docker & Docker Compose (buildx) |
| **Required config** | `BOT_TOKEN`, `TELEGRAM_API`, `TELEGRAM_HASH`, `OWNER_ID`, `DATABASE_URL` |
| **License** | [LICENSE](LICENSE) |

---

<a id="architecture"></a>

## 🧬 Architecture

```mermaid
graph TD
    A[Telegram User] -->|Commands / Files| B((Amaterasu Core))
    B --> L[(MongoDB)]
    
    B --> C{Download Engines}
    C -->|Torrents| D[qBittorrent & Aria2c]
    C -->|Usenet| E[Sabnzbd]
    C -->|Direct/Links| F[JDownloader & yt-dlp]
    C -->|Cloud| M[Mega CMD]
    
    B -.->|Telegram Files| N
    C -->|Downloaded Files| N{Media Processing}
    N -->|SVT-AV1 / HEVC| O[FFmpeg Encoding]
    N -->|Regex| P[Auto-Rename & Meta]
    N -->|Archives| Q[Extract / Split / Join]

    N --> G{Storage & Distribution}
    
    G -->|Cloud Drives| H[Google Drive & Rclone]
    G -->|Direct Download| I[FileToLink Server]
    G -->|Telegram| J[Leech Uploader]
    G -->|DDL Hosters| K[GoFile / BuzzHeavier / PixelDrain / DevUploads / VikingFile]
    
    style B fill:#FF4500,stroke:#333,stroke-width:2px,color:#fff
    style A fill:#2496ED,color:#fff
    style I fill:#28a745,color:#fff
    style L fill:#4DB33D,color:#fff
    style N fill:#9370DB,color:#fff
```

### Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.11 |
| Telegram Framework | WZGram 3.0.23 (`pyrogram` API) |
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
git clone https://github.com/Zan-getsu/Amaterasu.git && cd Amaterasu


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
| `token.pickle` | Google Drive authentication (OAuth2 token) | Send `/tokengen`, create a Google OAuth Web application client, upload `credentials.json`, then download or activate the generated token |
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
  BASE_URL = "https://stream.yourdomain.com"
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

<a id="cloudflare-tunnel-setup"></a>

### Cloudflare Tunnel Setup

Amaterasu can start `cloudflared` from its own config. This keeps Cloudflare Tunnel controlled by `config.py`, environment variables, MongoDB-backed `/bsetting`, and the normal bot settings UI.

Use a **quick tunnel** only for testing. Cloudflare gives a temporary `trycloudflare.com` URL, and that URL changes whenever the tunnel restarts.

```python
CLOUDFLARE_TUNNEL_ENABLED = True
CLOUDFLARE_TUNNEL_TOKEN = ""
CLOUDFLARE_TUNNEL_TARGET = ""
CLOUDFLARE_TUNNEL_AUTO_URL = True
```

With `CLOUDFLARE_TUNNEL_AUTO_URL = True`, Amaterasu watches the `cloudflared` logs, captures the generated `trycloudflare.com` URL, and updates `BASE_URL` in memory. If MongoDB is configured, it also saves the new `BASE_URL`.

The legacy Compose sidecar tunnel is opt-in. Start it only when you explicitly want the separate sidecar flow:

```bash
docker compose --profile tunnel up -d
```

For production, use a **named tunnel** with your own domain:

1. Open the Cloudflare dashboard.
2. Go to **Zero Trust** -> **Networks** -> **Tunnels**.
3. Create a Cloudflared tunnel and copy its token.
4. Add a public hostname pointing to `http://localhost:8080`.
5. Set the token in `config.py` or `/bsetting`:

```python
CLOUDFLARE_TUNNEL_ENABLED = True
CLOUDFLARE_TUNNEL_TOKEN = "eyJ..."
CLOUDFLARE_TUNNEL_TARGET = ""
BASE_URL = "https://stream.yourdomain.com"
PORT = 8080
```

The Cloudflare config variables are:

| Variable | Purpose |
|---|---|
| `CLOUDFLARE_TUNNEL_ENABLED` | Starts or stops `cloudflared` with Amaterasu |
| `CLOUDFLARE_TUNNEL_TOKEN` | Named tunnel token. Empty means quick tunnel |
| `CLOUDFLARE_TUNNEL_TARGET` | Local URL to expose. Empty means `http://127.0.0.1:PORT` |
| `CLOUDFLARE_TUNNEL_METRICS` | Local metrics listener, default `127.0.0.1:49312` |
| `CLOUDFLARE_TUNNEL_AUTO_URL` | Auto-save the generated quick tunnel URL |

Why this is safer than always-on tunnel containers or separate `.env` files:

- Normal deployments are unchanged unless `CLOUDFLARE_TUNNEL_ENABLED` is set.
- The tunnel token lives in the same config path as the rest of Amaterasu.
- `/bsetting` can enable, disable, or restart the tunnel without editing Compose.
- Quick tunnel URLs can be captured automatically, while named tunnels stay stable for production.

Troubleshooting:

| Symptom | Fix |
|---|---|
| Tunnel starts but links still point to an IP or old domain | Update `BASE_URL` to your public Cloudflare URL |
| Named tunnel refuses to start | Confirm `CLOUDFLARE_TUNNEL_TOKEN` is set correctly in config |
| Quick tunnel URL changed after restart | Expected behavior. Use a named tunnel for stable links |
| FileToLink or player page loads but streams fail | Make sure the Cloudflare public hostname points to `http://localhost:8080` and `PORT=8080` matches the bot web port |

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
| `HELPER_TOKENS` | `str` | `""` | Space-separated helper bot tokens used by HyperDL/HyperUP parallel Telegram transfers |
| `HELPER_STRINGS` | `str` | `""` | Space-separated helper user session strings. These clients can start with the bot, but HyperDL/HyperUP currently uses helper bot tokens as its active worker pool |
| `HELPER_BOT_PROXIES` | `str` | `""` | Optional newline-separated proxy dictionaries for `HELPER_TOKENS`, one proxy per helper bot |
| `HELPER_USER_PROXIES` | `str` | `""` | Optional newline-separated proxy dictionaries for `HELPER_STRINGS`, one proxy per helper user |
| `DEFAULT_LANG` | `str` | `""` | Default language code for the bot |
| `TG_PROXY` | `dict` | `{}` | Proxy config for Pyrogram (`{"scheme": "socks5", "hostname": "...", "port": ...}`) |
| `BOT_PM` | `bool` | `False` | If `True`, bot sends task completion messages in PM |
| `BOT_MAX_TASKS` | `int` | `0` | Global maximum concurrent tasks (0 = unlimited) |
| `USER_MAX_TASKS` | `int` | `0` | Per-user maximum concurrent tasks |
| `USER_TIME_INTERVAL` | `int` | `0` | Minimum seconds between user commands (anti-spam) |
| `VERIFY_TIMEOUT` | `int` | `0` | Verification timeout in seconds |
| `LOGIN_PASS` | `str` | `""` | Password for `/login` command (restricts unauthorized access) |
| `SET_COMMANDS` | `bool` | `False` | If `True`, registers bot commands in Telegram's command menu |
| `TIMEZONE` | `str` | `""` | Timezone for messages and the daily 06:00 automatic restart (e.g., `Asia/Dhaka`) |

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
| `TRANSMISSION_MODE` | `str` | `both` | Telegram upload mode: `bot`, `user`, or `both` |
| `USE_HYPER` | `bool` | `True` | Enable HyperDL/HyperUP acceleration when helper bots and `LEECH_DUMP_CHAT` are configured |
| `HYPER_THREADS` | `int` | `0` | Number of helper workers used for HyperDL. `0` lets Amaterasu choose automatically |
| `HYPER_PIPELINE` | `int` | `4` | Concurrent Telegram `GetFile` request depth per HyperDL worker group |
| `HYPER_CHUNK` | `int` | `524288` | HyperDL chunk size in bytes. Default is 512 KiB |
| `LEECH_PREFIX` | `str` | `""` | Text prepended to every uploaded filename |
| `LEECH_SUFFIX` | `str` | `""` | Text appended to every uploaded filename |
| `LEECH_FONT` | `str` | `""` | Font style for leech filenames |
| `LEECH_CAPTION` | `str` | `""` | Custom caption template for uploaded files |
| `THUMBNAIL_LAYOUT` | `str` | `""` | Default thumbnail layout (e.g., `3x3`) |
| `EXCLUDED_EXTENSIONS` | `str` | `""` | Space-separated file extensions to skip during upload |

### HyperDL / HyperUP Setup

HyperDL and HyperUP accelerate Telegram-to-server downloads and server-to-Telegram uploads by using extra helper bot clients in parallel. They are enabled only when all required runtime pieces are available; otherwise Amaterasu falls back to the normal Pyrogram transfer path.

Minimum working config:

```python
USE_HYPER = True
LEECH_DUMP_CHAT = "-1001234567890"
HELPER_TOKENS = "123456:AA... 234567:BB... 345678:CC..."
```

Required setup:

1. Create one or more extra Telegram bots with [@BotFather](https://t.me/BotFather). Do not reuse `BOT_TOKEN`.
2. Add the main bot and every helper bot to `LEECH_DUMP_CHAT`.
3. Give the bots permission to send messages/files in that chat. For channels, make them admins.
4. Put the helper bot tokens in `HELPER_TOKENS`, separated by spaces.
5. Restart the bot and check logs for lines like `Helper Bot [...] Started!`.

How it is used:

| Path | Requirement | Behavior |
|---|---|---|
| HyperDL | `USE_HYPER=True`, `HELPER_TOKENS`, `LEECH_DUMP_CHAT` | Telegram source media is copied to `LEECH_DUMP_CHAT`, then helper bots download different byte ranges in parallel |
| HyperUP | `USE_HYPER=True`, `HELPER_TOKENS`, `LEECH_DUMP_CHAT` | Helper bots upload file parts in parallel before the main client sends the final Telegram media |
| Normal transfer | Missing helper bots, missing dump chat, or `USE_HYPER=False` | Amaterasu uses the regular Telegram download/upload path |

Recommended helper count:

| Server / workload | Suggested helpers |
|---|---|
| Small VPS, 1-2 vCPU | 2-3 helper bots |
| Normal VPS, 2-4 vCPU | 3-5 helper bots |
| Heavy Telegram leech workload | 5-8 helper bots, then tune based on FloodWait logs |

Optional tuning:

```python
HYPER_THREADS = 0        # 0 = auto. Set 2, 4, 6... to cap parallel download parts.
HYPER_PIPELINE = 4       # Higher can be faster, but may increase FloodWaits.
HYPER_CHUNK = 512 * 1024 # Keep 512 KiB unless you are testing carefully.
```

Optional per-helper proxy config uses one Python dictionary per line. Blank lines mean "no proxy" for that helper index.

```python
HELPER_BOT_PROXIES = """
{"scheme": "socks5", "hostname": "1.2.3.4", "port": 1080, "username": "user", "password": "pass"}

{"scheme": "http", "hostname": "5.6.7.8", "port": 8080}
"""
```

Troubleshooting:

| Symptom | Check |
|---|---|
| Hyper never starts | Confirm `USE_HYPER=True`, `HELPER_TOKENS` is not empty, and `LEECH_DUMP_CHAT` is set |
| `Cannot copy to dump chat` | Main bot cannot copy the source message into `LEECH_DUMP_CHAT`; check chat ID and bot permissions |
| Helper bot failed at startup | Token may be wrong, bot may be banned/limited, or proxy syntax may be invalid |
| Many FloodWait logs | Reduce helper count, lower `HYPER_THREADS`, or lower `HYPER_PIPELINE` |
| Upload works but not faster | Add more helper bots, use a nearby VPS region, and ensure `LEECH_DUMP_CHAT` is a supergroup/channel where all helper bots can send |

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
| `BASE_URL` | `str` | `""` | Public URL for FileToLink and web UI links, e.g. `https://stream.example.com` |
| `WEB_PINCODE` | `bool` | `False` | Enable pincode verification for torrent file selection |
| `AMATERASU_WEB_SECRET` | `str` | `""` | Secret used to sign and verify web interface tokens. Set a long random value so file-selector and web auth links keep working after restarts |
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
| `IMAGES` | `list` | `[]` | Image URLs or Telegram photo file IDs used as random bot message photos |
| `IMG_SEARCH` | `str` | `""` | Comma-separated wallpaper search keywords used to auto-fill `IMAGES` on startup |
| `IMG_PAGE` | `int` | `1` | Number of Wallpaperflare result pages to fetch per `IMG_SEARCH` keyword |
| `USE_IMAGES` | `bool` | `False` | Enable random images on supported bot messages |
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
| `PROGRESS_BAR` | `str` | `"█:░"` | Progress bar symbols in `FILLED:EMPTY` format, e.g. `█:░` or `🟩:⬛` |
| `STATUS_LIMIT` | `int` | `10` | Max number of tasks shown per status page |
| `STATUS_UPDATE_INTERVAL` | `int` | `0` | Seconds between status message updates |
| `INCOMPLETE_TASK_NOTIFIER` | `bool` | `False` | Notify about incomplete tasks on restart |
| `INC_TASK_RESUME` | `bool` | `False` | Auto-resume incomplete tasks after restart |
| `CLEAN_LOG_MSG` | `bool` | `False` | Clean log messages after task completion |
| `DELETE_LINKS` | `bool` | `False` | Delete user's link message after processing |
| `MEDIA_STORE` | `bool` | `False` | Store media metadata |
| `COLORED_BTNS` | `bool` | `True` | Enable colored inline button styles where Telegram supports them |

### 13. FileToLink Streaming

| Variable | Type | Default | Description |
|---|---|---|---|
| `BIN_CHANNEL` | `int` | `0` | Telegram channel ID used as file storage backend |
| `MAX_BATCH_FILES` | `int` | `0` | Max files per batch operation |
| `CHANNEL` | `bool` | `False` | Enable channel mode |
| `MULTI_TOKEN1..3` | `str` | `""` | Additional bot tokens for load balancing |
| `AUTO_PROVISION_STREAM_BOTS` | `bool` | `False` | Use `USER_SESSION_STRING` at startup to add and promote configured `MULTI_TOKEN` bots in `BIN_CHANNEL` and `LEECH_DUMP_CHAT`; provisioning is skipped if unavailable. |
| `TOKEN_ENABLED` | `bool` | `False` | Reserved legacy setting; FileToLink URLs are always signed |
| `TOKEN_TTL_HOURS` | `int` | `0` | Reserved legacy setting; route tokens currently do not expire |
| `SHORTEN_ENABLED` | `bool` | `False` | Enable URL shortening for stream links |
| `GLOBAL_RATE_LIMIT` | `bool` | `False` | Reserved legacy setting; not currently enforced |
| `RATE_LIMIT_ENABLED` | `bool` | `False` | Reserved legacy setting; not currently enforced |

Runtime cache tuning is environment-driven: set `FILETOLINK_CACHE_MAX_MB` to cap a single cached file (default `256`) and `FILETOLINK_CACHE_TOTAL_MAX_MB` to cap total FileToLink cache usage (default `2048`). Use `/link status` to inspect stream clients, storage config, and cache usage.

### 14. Web Server

| Variable | Type | Default | Description |
|---|---|---|---|
| `PORT` | `int` | `8080` | Local web server port. Public links use `BASE_URL` |
| `BIND_TO_LOOPBACK` | `bool` | `True` | When `True`, the web UI binds to `127.0.0.1` only — operators must put a reverse proxy (nginx, Caddy, Cloudflare Tunnel) in front. When `False`, binds `0.0.0.0` for direct LAN access without a reverse proxy. Pair with `ports: ["0.0.0.0:8080:8080"]` in docker-compose for direct access. Trade-off: `False` is more convenient but exposes the web UI to anyone who can reach the host on port 8080. |
| `CLOUDFLARE_TUNNEL_ENABLED` | `bool` | `False` | Start Cloudflare Tunnel from Amaterasu |
| `CLOUDFLARE_TUNNEL_TOKEN` | `str` | `""` | Named tunnel token. Empty uses a temporary quick tunnel |
| `CLOUDFLARE_TUNNEL_TARGET` | `str` | `""` | Local URL exposed by the tunnel. Empty uses `http://127.0.0.1:PORT` |
| `CLOUDFLARE_TUNNEL_METRICS` | `str` | `"127.0.0.1:49312"` | Local cloudflared metrics listener |
| `CLOUDFLARE_TUNNEL_AUTO_URL` | `bool` | `True` | Auto-fill quick tunnel URL into `BASE_URL` |
| `WORKERS` | `int` | `0` | Number of Uvicorn worker processes |
| `LOGIN_PASS` | `str` | `""` | Optional web UI login password (separate from `WEB_ACCESS_PASSWORD`). When set, all non-public web routes require a `session_token` cookie obtained via `/login`. When empty, no login is required. `WEB_ACCESS_PASSWORD` protects file download links; `LOGIN_PASS` protects the web UI admin panel. |

#### Web UI Access

By default, the web UI binds to `127.0.0.1:8080` — only accessible from the host itself. This is the safest default: operators must put a TLS-terminating reverse proxy (nginx, Caddy, Cloudflare Tunnel) in front, which handles HTTPS and access control.

For quick deployments without a reverse proxy (e.g., testing on a local LAN, or accessing via SSH tunnel), set `BIND_TO_LOOPBACK=false` in your `.env` file or shell:

```bash
BIND_TO_LOOPBACK=false docker compose up -d
```

This rewrites the bind address to `0.0.0.0:8080:8080`, making the web UI reachable on the host LAN. **Trade-off:** anyone who can reach the host on port 8080 can access the web UI. Use only on trusted networks.

For an additional layer of protection on the web UI itself (beyond the file-download password), set `LOGIN_PASS` to require a login cookie for all admin routes.

### 14b. Self-Update

| Variable | Type | Default | Description |
|---|---|---|---|
| `UPSTREAM_REPO` | `str` | `https://github.com/Zan-getsu/Amaterasu` | Git repo URL for auto-update. Empty disables auto-update |
| `UPSTREAM_BRANCH` | `str` | `"main"` | Branch to track |
| `UPDATE_PKGS` | `bool` | `False` | Run `uv pip install -U -r requirements.txt` on every boot. Off by default to avoid surprises — pin and update explicitly |
| `UPSTREAM_ALLOWLIST` | `str` | (3 default patterns) | Comma-separated regex patterns for allowed `UPSTREAM_REPO` URLs. Default allows `github.com`, `raw.githubusercontent.com`, and `git.nbmirror.qzz.io`. Add your own fork URL here to enable auto-update from a custom fork |

#### Self-Update from a Custom Fork

By default, `update.py` only accepts `UPSTREAM_REPO` URLs matching one of three patterns: `github.com`, `raw.githubusercontent.com`, or `git.nbmirror.qzz.io`. This prevents arbitrary-repo fetch but breaks fork workflows — operators who fork Amaterasu to their own GitHub cannot auto-update.

To enable auto-update from your own fork, set `UPSTREAM_ALLOWLIST` in your `.env` file or `config.py`:

```bash
# .env file
UPSTREAM_ALLOWLIST=^https://github\.com/yourname/Amaterasu/?$
```

Multiple patterns are comma-separated:

```bash
UPSTREAM_ALLOWLIST=^https://github\.com/yourname/Amaterasu/?$,^https://gitlab\.com/yourname/Amaterasu/?$
```

Each pattern is a Python regex. Invalid patterns are skipped with a warning. If no valid patterns are parsed, the default 3-pattern allowlist is used as a fallback.

#### SABnzbd.ini Patcher Bypass

| Variable | Type | Default | Description |
|---|---|---|---|
| `SKIP_SABNZBD_INI_CHECK` | `bool` | `False` | When `True`, the SABnzbd.ini patcher skips validation and starts SABnzbd even if known-bad credential markers (`sabpassword`, `CHANGEME`, `REPLACED_AT_BOOT_BY_AMATERASU`) cannot be replaced. Use this only if you manage SABnzbd.ini manually or migrate from a custom config. The default (`False`) refuses to start SABnzbd with default credentials — a safety net against shipping known-bad credentials |

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
| `UPSTREAM_REPO` | `str` | `https://github.com/Zan-getsu/Amaterasu` | Repository URL for auto-updates on restart. Leave empty to skip code reset/update. Allowed hosts: `github.com`, `raw.githubusercontent.com`, `git.nbmirror.qzz.io` |
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
| `/uphoster` | `/up` | Download a link → upload to DDL servers (GoFile, BuzzHeavier, PixelDrain, DevUploads, VikingFile) |

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
| `/tokengen` | — | Open your private Google OAuth token generator and download manager |
| `/stats` | `/st` | View server hardware stats (CPU, RAM, Disk, Network) |
| `/ping` | — | Check bot response latency |
| `/help` | `/h` | Show all available commands with descriptions |
| `/login` | — | Authenticate with bot password (if `LOGIN_PASS` is set) |

<a id="media--file-tools"></a>

### 🎬 Media & File Tools

| Command | Shortcut | Description |
|---|---|---|
| `/link` | `/stream`, `/f2l` | Generate direct stream/download links for Telegram files |
| `/autorename` | `/ar` | Set up or use an auto-rename template |
| `/sort` | — | Toggle file sorting mode and resend collected files alphabetically |
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
| `/purge` | `/clear_drive` | Sudo | Scan and bulk-delete contents from a Google Drive folder |
| `/rss` | — | Authorized | Open the RSS feed management panel |

<a id="drive-purge-manager"></a>

### 🧹 Drive Purge Manager

The Drive Purge Manager provides Sudo users with an interactive cleanup panel
for a Google Drive folder.

```text
/purge
/clear_drive
/purge DRIVE_ID
/clear_drive DRIVE_ID
```

- Without a Drive ID, the command uses the configured `GDRIVE_ID`.
- A supplied Drive ID or Google Drive folder link overrides `GDRIVE_ID`.
- The target is scanned recursively before any destructive option is shown.
- Service Account authentication follows the existing GDrive behavior and
  falls back to `token.pickle` when the Service Account cannot access the target.

| Mode | Behavior |
|---|---|
| **Delete All** | Permanently deletes every file and subfolder inside the target |
| **Delete By Age** | Deletes items whose created and modified times are older than the selected duration |
| **Delete By Range** | Deletes the first selected number of files in scan order |
| **Delete Files Only** | Deletes files while preserving the folder structure |
| **Delete Empty Folders** | Deletes folder trees that contain no files |
| **Delete Only Folders** | Moves nested files to the target root, then deletes the folders |
| **Dry Run Preview** | Shows the full Delete All plan without deleting anything |

#### Safety and operation

- Google Drive deletion is permanent; items are not moved to Trash.
- Every destructive mode shows its exact file, folder, and size plan before
  deletion.
- Delete All, configured-root cleanup, operations over 1,000 files, and
  operations over 100 GB require a second confirmation button.
- The control panel expires after five minutes of inactivity. Custom age and
  amount inputs expire after 60 seconds.
- Only one purge panel or running purge can target the same Drive ID at a time.
- Deletions use Drive API batches of 50 with paced dispatch, per-item fallback,
  and quota-aware exponential backoff with jitter.
- **Stop Purge** finishes the current batch, stops new batches, and returns a
  partial completion report.
- Actions and results are written to the bot log with the user, target, mode,
  deleted totals, recovered size, execution time, and timestamp.

---

<a id="encoding--metadata"></a>

## 🎞️ Encoding & Metadata

Amaterasu features a powerful built-in FFmpeg encoding engine capable of transforming and optimizing media on the fly before uploading.

### 1. Encode Profiles
Instead of typing out complex FFmpeg commands every time, you can create and save **Encode Profiles** through your personal settings panel:
1. Send `/usetting` in the chat.
2. Navigate to **Encode Profiles** → **➕ Create Profile**.
3. Submit a JSON configuration defining your preferred codecs and parameters.

You can set any profile as your **Default**. The bot will automatically use this profile whenever you start an encoding task (e.g., using the `-en` flag).

### 2. Supported Codecs
- **Video**: `libsvtav1` (Next-gen AV1), `libx265` (HEVC/H.265), `libx264` (H.264), `copy`
- **Audio**: `libopus`, `aac`, `copy`
- **Subtitle**: `copy`, `none`

### 3. Track Mapping & Metadata Injection
You can dynamically isolate specific audio/subtitle tracks and inject custom metadata (titles, release years, track names) either directly into your **Encode Profile** or on the fly using the `-enmeta` command argument.

#### A. In your Encode Profile (JSON)
Include a `"metadata"` block in your profile configuration:
```json
{
    "name": "Multi-Audio AV1 Encode",
    "video_codec": "libsvtav1",
    "audio_codec": "libopus",
    "subtitle_mode": "copy",
    "metadata": {
        "title": "Dr. Stone S01E01",
        "v_track": "0",
        "a_track": "1",
        "s_track": "0",
        "s:v:0": "title=1080p SVT-AV1",
        "s:a:0": "title=English Dubbed",
        "s:s:0": "title=English Subtitles"
    }
}
```

#### B. On the Fly (Command Line)
Override or apply metadata instantly using the `-enmeta` flag. Separate key-value pairs with a pipe `|`:
```
/leech <link> -en -enmeta "title=My Movie|v_track=0|a_track=1|s:a:0=title=English Audio"
```

**Track Selection Keys:**
- `v_track`: Select which video track to keep (e.g., `0` for the first). Use `?` to keep all.
- `a_track`: Select which audio track to keep (e.g., `1` for the second).
- `s_track`: Select which subtitle track to keep.

**Stream Specifiers:**
- `s:v:0`: Applies metadata to the first video track.
- `s:a:1`: Applies metadata to the second audio track.
- `s:s:0`: Applies metadata to the first subtitle track.

### 4. Cover Art Embedding
When you set a custom thumbnail (via `/setthumb` or the `-t` argument), the bot will automatically embed that image as the official cover art (`attached_pic`) directly into the final MP4/MKV container during the encoding process.

---

<a id="auto-rename"></a>

## 🎭 Auto-Rename Engine

Amaterasu includes a powerful, regex-driven **Auto-Rename Engine** inspired by dedicated renaming bots. It can intelligently extract information from messy filenames and restructure them into clean, standardized formats.

### 1. Setting Up Your Template
Instead of manually typing a new name for every file, you define a **Template**.
1. Send `/usetting` in the bot's private chat.
2. Navigate to **Misc Settings** → **Auto-Rename**.
3. Enter your template using dynamic placeholders.

**Supported Placeholders:**
- `{title}` - The extracted base name of the media, stripped of tags and quality info.
- `{season}` - The extracted season number (e.g., `01`).
- `{episode}` - The extracted episode number (e.g., `04`).
- `{quality}` - The extracted resolution/quality (e.g., `1080p`, `4k`, `WEBRip`).

**Example Template:** 
`[MyGroup] {title} - S{season}E{episode} [{quality}]`
*If the bot receives `messy.show.s1.e4.1080p.mkv`, it will become `[MyGroup] Messy Show - S01E04 [1080p].mkv`.*

### 2. How to Use Auto-Rename

There are two primary ways the Auto-Rename Engine works:

**Mode 1: Live Telegram Renaming**
- Send `/autorename` in the bot's private chat to toggle Auto-Rename Mode **ON**.
- Simply forward or upload any media/document to the bot.
- The bot will instantly download it, apply your template to the filename, and upload it back to you.

**Mode 2: Download Tasks**
- When you start a mirror/leech task (e.g., downloading a torrent or a yt-dlp link), the bot will automatically apply your Auto-Rename template to all files inside the task *before* they are uploaded to your cloud drive or Telegram.

---

<a id="file-sorting-mode"></a>

## 🗂️ File Sorting Mode

File Sorting Mode lets you send a batch of Telegram files in any order, then have Amaterasu return them alphabetically by file name. It is designed for fast cleanup of messy uploads, episode packs, document batches, and renamed file sets.

### How to Use

1. Send `/sort` in the chat where you want to collect files.
2. Send or forward the files you want sorted.
3. Send `/sort` again to turn sorting off and deliver the files back in sorted order.

Example workflow:
```
/sort
03 - Ending.mkv
01 - Opening.mkv
02 - Episode.mkv
/sort
```

The bot will resend:
```
01 - Opening.mkv
02 - Episode.mkv
03 - Ending.mkv
```

### What Gets Stored

While sort mode is active, Amaterasu only caches Telegram metadata:

| Cached Data | Purpose |
|---|---|
| `file_id` | Resend the same Telegram file without downloading it |
| File name | Sort files alphabetically |
| Media type | Resend as document, video, audio, photo, or other supported media |
| Message ID | Keep a stable order when file names match |

> [!IMPORTANT]
> File Sorting Mode does **not** download files to the server. It uses Telegram `file_id`s to resend cached files, so delivery is fast and does not consume hosting bandwidth.

### Supported Media

Sort mode supports common Telegram media messages, including documents, videos, audio files, photos, voice notes, animations, video notes, and stickers. Files without a Telegram file name are assigned a safe fallback name for sorting.

### Notes

- Sending `/sort` a second time always ends the current sort session.
- If no files were collected, the bot simply disables sort mode.
- Files are sorted case-insensitively by file name.
- If your bot uses `CMD_SUFFIX`, use the suffixed command, such as `/sort1`.

---

<a id="encoding-profile-creator-web-ui"></a>

## 🎨 Encoding Profile Creator (Web UI)

Amaterasu ships with a **built-in visual web application** for creating, editing, and managing Encode Profiles — without writing a single line of JSON by hand.

Open User Settings in Telegram, choose **Encode Profiles**, then select
**Open Web Creator**. The bot generates the required signed URL automatically.

Opening `/app/encode-profiles` directly without the signed `user_id` and `token`
parameters intentionally uses browser-local offline storage and does not sync to MongoDB.

### Why Use the Web UI?

Encoding profiles are powerful but involve complex FFmpeg concepts — stream specifiers (`s:a:0`), disposition flags, CRF values, codec parameters, and metadata injection. The Web UI **completely abstracts all of this** into user-friendly dropdowns, sliders, and visual selectors.

| Traditional (Raw JSON) | Web UI Equivalent |
|---|---|
| `"s:a:0": "title=English"` | Select **Audio → Track 1 → Title** → Type `English` |
| `"a_track": "0,1"` | Select **Audio Tracks to Keep → Tracks 1 & 2** |
| `"crf": 24` | Drag the **CRF slider** to 24 |
| Typing full JSON and pasting into Telegram | Click **Save Profile** |

---

### 🏗️ Building a Profile (Step-by-Step)

#### Step 1: Open the Profile Builder

Navigate to the web UI URL and click **"➕ Create New Profile"**, or select an existing profile to edit. You can also start from a **Quick Preset** (pre-configured templates for common workflows like AV1 anime encoding or H.264 fast encoding).

#### Step 2: Configure Video Settings

The **Video Settings** section is open by default. Here you can configure:

| Setting | Description | UI Element |
|---|---|---|
| **Video Codec** | The encoder to use (`libsvtav1`, `libx265`, `libx264`, or `copy`) | Dropdown |
| **CRF (Quality)** | Quality level — lower = better quality, larger file. `24-28` recommended for AV1. | Slider with live label |
| **Preset / Speed** | Encoding speed vs compression tradeoff. Slower = smaller files. | Dropdown |
| **Pixel Format** | Bit depth. `yuv420p10le` recommended for 10-bit AV1/HEVC. | Dropdown |
| **Format Profile & Level** | Codec compliance level (e.g., Profile `0`, Level `5.1`). | Dropdowns |
| **Color Primaries / TRC / Colorspace** | HDR / SDR color metadata (`bt709`, `bt2020`, etc.). | Dropdowns |
| **Extra Parameters** | Advanced SVT-AV1/x265 params in colon-separated format. | Text field |

> [!NOTE]
> Hover over the **[?]** icon next to settings like CRF, Preset, and Pixel Format for instant explanations of what they do.

Below the video codec settings, you'll find the **Video Track Selection & Tags** sub-section:

- **Video Tracks to Keep**: A dropdown offering `Keep All Tracks`, `Track 1 Only`, `Tracks 1 & 2`, or a `Custom Mapping` option for advanced users.
- **Video Metadata Tags**: Visually add tags (Title, Language, Handler, or Custom) to specific video tracks. No need to type `s:v:0` — just select **Track 1** from a dropdown.
- **Video Disposition Flags**: Set flags like `default`, `forced`, or `0` (remove all) per track.

#### Step 3: Configure Audio Settings

Expand the **Audio Settings** section to configure:

| Setting | Description |
|---|---|
| **Audio Codec** | `libopus`, `aac`, `flac`, or `copy` |
| **Bitrate** | Output audio bitrate (e.g., `128k`, `192k`, `320k`) |
| **Channels** | Channel layout (Stereo, 5.1, 7.1, or keep original) |
| **VBR Toggle** | Variable bitrate optimization |

Just like Video, the Audio section includes its own **Track Selection**, **Metadata Tags**, and **Disposition Flags** sub-sections. For example, to label two audio tracks:

1. Click **"Add Tag"** → Select **Track 1** → **Title** → Type `English`.
2. Click **"Add Tag"** again → Select **Track 2** → **Title** → Type `Japanese`.
3. To set the language metadata, add another tag → Select **Track 1** → **Language** → Pick `English (eng)` from the dropdown.

> [!IMPORTANT]
> You can add **multiple tags** to the same track (e.g., both a Title and a Language for Track 1). The UI handles duplicate-key deconfliction automatically.

#### Step 4: Configure Subtitle Settings

Expand the **Subtitle Settings** section:

| Setting | Description |
|---|---|
| **Subtitle Mode** | `copy` (keep original subs) or `none` (discard all subtitles) |
| **Subtitle Tracks to Keep** | Same track selector as Video/Audio |
| **Subtitle Metadata Tags** | Add Title/Language tags to subtitle tracks |
| **Subtitle Disposition Flags** | Mark subtitle tracks as `default`, `forced`, etc. |

#### Step 5: Global Metadata

The **Global Metadata** section handles file-level settings:

| Setting | Description |
|---|---|
| **Rename File To** | Rename pattern for the output file (supports dynamic variables) |
| **Global Title** | The internal metadata title embedded in the container |
| **Cover Image URL** | A direct image URL or Telegram link to embed as cover art |

##### Dynamic Variable Chips

Below the **Rename File To** and **Global Title** fields, you'll see clickable chips for quick variable insertion:

| Chip | Inserts | Resolves To (Example) |
|---|---|---|
| `{title}` | Parsed show/movie title | `Dr STONE` |
| `{episode}` | Episode identifier | `S04E33` |
| `{quality}` | Resolution quality tag | `1080p` |
| `{resolution}` | Exact resolution | `1920x1080` |
| `{basename}` | Original filename without extension | `Dr.STONE.S04E33.1080p.WEB-DL` |
| `{filename}` | Full original filename | `Dr.STONE.S04E33.1080p.WEB-DL.mkv` |
| `{year}` | Detected year from filename | `2024` |
| `{audiolang}` | Primary audio language | `Japanese` |
| `{sublang}` | Primary subtitle language | `English` |

Click any chip to instantly insert it into the text field. Example rename pattern:
```
[Zangetsu] {title} - {episode}.mkv
```
This would produce: `[Zangetsu] Dr STONE - S04E33.mkv`

---

### 🔍 Live Preview

At the bottom of the Profile Builder, a **Live Preview** panel shows the output of your settings in real-time. You can toggle between two views:

| View | Description |
|---|---|
| **JSON Layout** | The raw JSON that will be saved as your profile. This is the exact format the bot's backend consumes. |
| **FFmpeg Command** | A generated mock `ffmpeg` CLI command showing how your settings translate to actual FFmpeg arguments. Great for advanced users to verify. |

The preview updates **instantly** as you change any setting.

---

### 📥 Importing & Exporting Profiles

| Action | How |
|---|---|
| **Export** | Click the **Copy** button (📋) in the preview panel. The JSON is copied to your clipboard. |
| **Import** | Click the **Import** button (⬇️) in the top bar. Paste any existing profile JSON into the prompt. The UI will auto-populate all fields. |
| **Save to Bot** | Click **Save Profile**. The profile is stored in your MongoDB database and immediately available in Telegram via `/usetting → Encode Profiles`. |

---

### 📋 Example: Complete Anime Encoding Profile

Here's what a typical anime encoding profile looks like when built through the Web UI:

```json
{
    "name": "My Custom Anime Preset",
    "video_codec": "libsvtav1",
    "audio_codec": "copy",
    "subtitle_mode": "copy",
    "metadata": {
        "title": "[MyGroup] {title} - {episode}",
        "v_track": "0",
        "a_track": "1,0",
        "s_track": "1,2",
        "s:v:0": "title=Encoded by MyGroup",
        "s:a:0": "title=English",
        "s:a:1": "title=Japanese",
        "s:s:1": "title=English",
        "s:s:2": "title=English (Signs/Songs)"
    },
    "video_params": {
        "crf": 24,
        "preset": 4,
        "pix_fmt": "yuv420p10le",
        "extra_params": "tune=0:film-grain=4",
        "profile": "0",
        "level": "5.1",
        "color_primaries": "bt709",
        "color_trc": "bt709",
        "colorspace": "bt709"
    },
    "audio_params": {
        "bitrate": "128k",
        "vbr": true
    },
    "rename": "{title} - {episode} [{resolution}].mkv",
    "cover_image": "https://example.com/poster.jpg",
    "disposition": {
        "a:0": "default",
        "s:1": "default"
    }
}
```

The above profile was built entirely through visual dropdowns and selectors — **zero FFmpeg knowledge required**.

---

<a id="google-token-generator-web-ui"></a>

## 🔐 Google Token Generator (Web UI)

Send `/tokengen` as an authorized user. The bot replies with a private, signed
link that expires after 15 minutes; run the command again whenever you need a
fresh link. The page is dedicated to that Telegram user and provides:

- **Upload credentials.json** for a Google OAuth **Web application** client.
- **Enter manually** using the same OAuth Client ID and Client Secret.
- A read-only callback URL to add under Google Cloud's **Authorized redirect URIs**.
- Legacy-compatible `token.pickle` and `token.json` downloads.
- Encrypted, per-user MongoDB storage so the generated files remain available
  through future `/tokengen` links.
- **Use in Amaterasu**, which explicitly copies the saved generated token into
  that user's existing `TOKEN_PICKLE` setting. Generation alone never replaces
  the user's active Drive token.

OAuth client input is encrypted only for the pending authorization attempt,
expires after 15 minutes, and is consumed once. The generated credential is
encrypted at the application layer before MongoDB storage. Keep
`AMATERASU_WEB_SECRET` stable: changing it intentionally makes previously saved
encrypted tokens unreadable.

The callback URL is always derived from `BASE_URL`, so configure a public
`https://` URL before using `/tokengen`. `DATABASE_URL` is also required.

> `token.pickle` and `token.json` contain sensitive Google credentials. Never
> share the private bot link or either downloaded file.

### Google Drive API and OAuth Setup

Use this flow when you want Amaterasu to upload to your own Google Drive account.
The short version: Google Cloud creates `credentials.json`; Amaterasu turns it
into your private `token.pickle`.

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Enable 2-Step Verification on the Google account you will authorize.
3. If you are on a phone or tablet, enable desktop site or desktop mode in the browser.
4. Create a new Google Cloud project, or select the project you want to use.
5. Open the navigation menu, then go to **APIs & Services -> Library**.
6. Click **Enable APIs and Services**.
7. Search for **Google Drive API**, open it, and click **Enable**.
8. Open **APIs & Services -> OAuth consent screen**.
9. Click **Get Started**.
10. Enter an app name.
11. Under **Audience**, select **External**.
12. Enter your Gmail address anywhere Google asks for a contact email.
13. Save the OAuth consent screen configuration.
14. Open **APIs & Services -> OAuth consent screen -> Audience**.
15. Under **Test users**, click **Add users**.
16. Add the same Gmail account you plan to use for authorization.
17. Open **APIs & Services -> Credentials**.
18. Click **Create credentials**, then select **OAuth client ID**.
19. For **Application type**, select **Web application**.
20. In Telegram, send `/tokengen` and open the private bot link.
21. Copy the **Authorized redirect URI** shown on the token generator page.
22. Return to Google Cloud and paste that URI into **Authorized redirect URIs**.
23. Click **Create**.
24. Download the OAuth client JSON file.
25. Rename the downloaded file exactly to `credentials.json`.
26. Return to the bot link.
27. In **Authorize your account**, upload `credentials.json`.
28. In **Google account hint**, enter the same Gmail address you added as a test user.
29. Click **Continue with Google**.
30. Sign in with the same Google account.
31. If Google shows an unverified-app warning, continue only after confirming
    the app and OAuth credentials belong to you.
32. Review the requested permissions and allow access.
33. After authorization completes, download `token.pickle` or click
    **Use in Amaterasu** to make the generated token the active Drive token for
    that Telegram user.

Keep `credentials.json` and `token.pickle` private. Do not upload them to a
public repository, paste them in chat, or share them with anyone.

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

For multiple consecutive files, reply to the first file and use `/link -i 10` to generate links for 10 files in one command.

Use `/link status` to check the active `BASE_URL`, stream bot pool, current stream loads, and FileToLink cache usage.

The web server serves an existing cached file immediately when available. For uncached full-file opens, the active transfer stays live-first and cache warming starts only after a successful full transfer; Range playback is kept live-first to avoid competing with initial seek/buffer requests.

### Multi-Token Load Balancing
Configure `MULTI_TOKEN1`, `MULTI_TOKEN2`, `MULTI_TOKEN3` with additional bot tokens. The server automatically distributes file requests across tokens to avoid Telegram's FloodWait rate limits, and temporarily cools down a stream bot after repeated fetch/stream failures so another available token can take over.

### Access Control
| Feature | Variable | Description |
|---|---|---|
| Web Token Signing | `AMATERASU_WEB_SECRET` | Signs web interface tokens for file selection and web auth. If empty, Amaterasu falls back to `LOGIN_PASS`, then `BOT_TOKEN` |
| Token Authentication | Always enabled | Generated stream URLs always contain a signed route token |
| Token Expiry | `TOKEN_TTL_HOURS` | Reserved for compatibility; route tokens currently do not expire |
| URL Shortening | `SHORTEN_ENABLED` | Shorten generated links via a URL shortener |
| Global Rate Limit | `GLOBAL_RATE_LIMIT` | Reserved for compatibility; not currently enforced |
| Session Rate Limit | `RATE_LIMIT_ENABLED` | Reserved for compatibility; not currently enforced |

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
  - Drive purge requires delete permission for every selected item. Google
    requires `organizer` permission on the parent folder for Shared Drive
    deletion (normally granted through Manager access).
  - Use **Dry Run Preview** first when validating a new Drive or Service Account.
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

  - Set `BASE_URL` to your public URL, for example `https://stream.example.com`.
  - Set `PORT` to the local web server port Amaterasu should bind.
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

<a id="acknowledgments"></a>

## 🙏 Acknowledgments & Credits

Amaterasu stands on the shoulders of giants. We want to express our deepest gratitude to the following legendary projects that paved the way and served as the foundational inspiration for this bot:

> [!IMPORTANT]  
> 🌟 **[WZML-X](https://github.com/SilentDemonSD/WZML-X)**  
> The undisputed core architecture and pioneering codebase that heavily influenced Amaterasu's powerful mirroring and leeching ecosystem.

> [!IMPORTANT]  
> 🌟 **[Auto-Rename-Bot](https://github.com/Codeflix-Bots/Auto-Rename-Bot)**  
> An incredible source of inspiration for our advanced auto-renaming and file manipulation algorithms. 

Please check out their repositories and drop them a star!

---

<div align="center">

### 🌟 Star History

If Amaterasu powers your workflow, please consider giving it a ⭐!

**[ ☀️ Awaken the Sun. Deploy Amaterasu Today. ☀️ ]**

*Built with ❤️ by [its-niloy](https://github.com/its-niloy)*

</div>
