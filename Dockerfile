FROM python:3.11-slim-bookworm

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1 \
    PIP_DEFAULT_TIMEOUT=100

WORKDIR /usr/src/app

# --- Layer 1: apt packages (changes rarely, cached aggressively) ---
# Every package here was verified to be used either directly (by Python
# code, shell scripts, or configs) or indirectly (as a build/runtime
# dependency of a pip package). See analysis in scripts/analyze_dockerfile_deps.sh.
#
# Direct usage:
#   bash          - start.sh, setpkgs.sh
#   git           - update.py (self-update), bot_settings.py, stats.py
#   curl          - setpkgs.sh (tracker list), Dockerfile (MEGA key, deno)
#   wget          - fallback HTTP client (no direct use, but tiny and useful)
#   gnupg         - Dockerfile (gpg --dearmor for MEGA repo key)
#   ca-certificates - HTTPS for curl, pip
#   build-essential - compile lxml, cryptography, pillow, pycountry
#   libssl-dev    - compile cryptography/pyopenssl
#   libffi-dev    - compile cffi (cryptography dep)
#   libxml2-dev   - compile lxml
#   libxslt-dev   - compile lxml
#   libmagic1     - runtime dep of python-magic (files_utils.py)
#   locales       - LANG=C.UTF-8 support
#   tzdata        - Config.TIMEZONE support (pytz)
#   ffmpeg        - media_utils.py, common.py, thumbnails, encode
#   aria2         - download engine (setpkgs.sh, aria2_*.py)
#   qbittorrent-nox - torrent download engine
#   p7zip-full    - files_utils.py (7z x), startup.py (cfg.zip extraction)
#   p7zip-rar     - RAR support via 7z
#   unrar         - SABnzbd.ini (enable_unrar=1)
#   unzip         - bot_settings.py
#   cpulimit      - setpkgs.sh (SABnzbd throttle), jdownloader_booter.py
#   rclone        - rclone_utils/*.py, common.py
#   sabnzbdplus   - Usenet downloader (config_manager.py, setpkgs.sh)
#   procps        - pkill (restart.py:791, bot_settings.py:771,1196)
#   mediainfo     - mediainfo.py, media_utils.py, bot_commands.py
#   util-linux    - taskset (setpkgs.sh, common.py, jdownloader_booter.py)
#   nodejs        - JS runtime for yt-dlp-ejs (YouTube signature bypass)
#   default-jre-headless - jdownloader_booter.py (java -jar JDownloader.jar)
RUN apt-get update && apt-get upgrade -y && \
    sed -i 's/main$/main contrib non-free/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/main$/main contrib non-free/g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        bash git curl wget gnupg ca-certificates \
        build-essential libssl-dev libffi-dev libxml2-dev libxslt-dev \
        libmagic1 locales tzdata \
        ffmpeg aria2 qbittorrent-nox \
        p7zip-full p7zip-rar unrar unzip \
        cpulimit rclone sabnzbdplus \
        procps mediainfo util-linux \
        nodejs \
        default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Layer 2: MEGAcmd (separate so MEGA repo issues don't block apt) ---
# megacmd provides the native MEGA SDK libraries used by the `mega`
# Python package (mega_sdk.py imports MegaApi, MegaListener, etc.).
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://mega.nz/linux/repo/Debian_12/Release.key | gpg --dearmor -o /etc/apt/keyrings/mega.nz.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/etc/apt/keyrings/mega.nz.gpg] https://mega.nz/linux/repo/Debian_12/ ./" > /etc/apt/sources.list.d/mega.nz.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends megacmd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# --- Layer 3: cloudflared binary (used by cloudflare_tunnel.py) ---
RUN arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64|arm64) cf_arch="$arch" ;; *) echo "Unsupported cloudflared arch: $arch" && exit 1 ;; esac \
    && curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cf_arch}" -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared

# --- Layer 4: Deno runtime (used by yt-dlp-ejs for YouTube JS solver) ---
# yt-dlp-ejs ships JavaScript solver bundles (core.min.js, lib.min.js)
# that yt-dlp can execute via deno/node/bun to bypass YouTube's
# signature challenges. Deno is the recommended runtime (fastest).
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# --- Layer 5: Python dependencies (rebuilds only when requirements.txt changes) ---
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip uv && \
    uv pip install --system --no-cache -r requirements.txt

# --- Layer 6: Create non-root user (fast, cached) ---
RUN groupadd -r amaterasu \
    && useradd -r -g amaterasu -m -d /home/amaterasu amaterasu \
    && mkdir -p /usr/src/app/downloads /JDownloader \
    && chown -R amaterasu:amaterasu /usr/src/app /JDownloader

# --- Layer 7: Copy app code (rebuilds every time you change code, fast) ---
COPY --chown=amaterasu:amaterasu . .
RUN chmod +x start.sh

USER amaterasu

CMD ["bash", "start.sh"]
