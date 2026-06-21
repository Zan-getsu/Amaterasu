FROM python:3.11-slim-bookworm

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /usr/src/app

# Update and install system dependencies
RUN apt-get update && apt-get upgrade -y && \
    # Add non-free repo for unrar (if using debian bullseye/bookworm)
    sed -i 's/main$/main contrib non-free/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true && \
    sed -i 's/main$/main contrib non-free/g' /etc/apt/sources.list 2>/dev/null || true && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        git \
        curl \
        wget \
        gnupg \
        build-essential \
        libssl-dev \
        libffi-dev \
        libxml2-dev \
        libxslt-dev \
        libmagic1 \
        locales \
        tzdata \
        aria2 \
        qbittorrent-nox \
        p7zip-full \
        p7zip-rar \
        unrar \
        unzip \
        cpulimit \
        rclone \
        sabnzbdplus \
        procps \
        mediainfo \
        nodejs \
        default-jre-headless \
        openssh-client \
    # Install MEGAcmd
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://mega.nz/linux/repo/Debian_12/Release.key | gpg --dearmor -o /etc/apt/keyrings/mega.nz.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/etc/apt/keyrings/mega.nz.gpg] https://mega.nz/linux/repo/Debian_12/ ./" > /etc/apt/sources.list.d/mega.nz.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends megacmd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64|arm64) cf_arch="$arch" ;; *) echo "Unsupported cloudflared arch: $arch" && exit 1 ;; esac \
    && curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cf_arch}" -o /usr/local/bin/cloudflared \
    && chmod +x /usr/local/bin/cloudflared \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Debian Bookworm ships FFmpeg 5.1, which lacks the AV1 workflow support used
# by this project.  Build the pinned FFmpeg 8.1.2 release instead of silently
# falling back to the distro package.  Keep libsvtav1 and libaom enabled for
# modern AV1 encode paths, alongside the existing H.264/H.265/Opus support.
# MEGAcmd adds a duplicate source with a different keyring.  Remove it before
# this next apt-get update without invalidating the completed package layer.
ARG FFMPEG_VERSION=8.1.2
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/meganz.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        nasm \
        yasm \
        pkg-config \
        libaom-dev \
        libopus-dev \
        libsvtav1-dev \
        libx264-dev \
        libx265-dev; \
    curl -fsSLO "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    tar -xJf "ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    cd "ffmpeg-${FFMPEG_VERSION}"; \
    ./configure \
        --prefix=/usr/local \
        --enable-gpl \
        --enable-version3 \
        --enable-libaom \
        --enable-libopus \
        --enable-libsvtav1 \
        --enable-libx264 \
        --enable-libx265 \
        --disable-debug \
        --disable-doc; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    cd /; \
    rm -rf "/usr/src/app/ffmpeg-${FFMPEG_VERSION}" \
           "/usr/src/app/ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Copy and install python requirements
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip uv && \
    uv pip install --system --no-cache -r requirements.txt

# Copy all the project files
COPY . .

# Setup permissions
RUN chmod +x start.sh

# Create a non-root user for the bot process. The user owns /usr/src/app
# so it can write downloads, logs, and config files. We still need
# cap_add SYS_ADMIN if cpulimit is used on child processes — operators
# who need that should add it via docker-compose.
#
# Also create /JDownloader (owned by amaterasu) so the bot can extract
# cfg.zip there on first boot if JDownloader is enabled. Without this,
# startup.py's `7z x cfg.zip -o/JDownloader` fails with permission
# denied when running as non-root.
RUN groupadd -r amaterasu \
    && useradd -r -g amaterasu -m -d /home/amaterasu amaterasu \
    && mkdir -p /usr/src/app/downloads /JDownloader \
    && chown -R amaterasu:amaterasu /usr/src/app /JDownloader

USER amaterasu

# Start the bot
CMD ["bash", "start.sh"]
