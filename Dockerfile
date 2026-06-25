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
        ca-certificates \
        git \
        curl \
        wget \
        gnupg \
        build-essential \
        autoconf \
        autoconf-archive \
        automake \
        libtool-bin \
        swig \
        python3-dev \
        pkg-config \
        libcurl4-openssl-dev \
        libc-ares-dev \
        libcrypto++-dev \
        libssl-dev \
        libffi-dev \
        libxml2-dev \
        libxslt-dev \
        libmagic1 \
        zlib1g-dev \
        libsqlite3-dev \
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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install MEGAcmd. Keep this separate from the large base package layer because
# mega.nz occasionally resets the key download connection during Docker builds.
RUN set -eux; \
    mkdir -p /etc/apt/keyrings; \
    for attempt in 1 2 3 4 5; do \
        curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
            https://mega.nz/linux/repo/Debian_12/Release.key \
            -o /tmp/mega-release.key && test -s /tmp/mega-release.key && break; \
        if [ "$attempt" = "5" ]; then exit 1; fi; \
        sleep 5; \
    done; \
    gpg --dearmor -o /etc/apt/keyrings/mega.nz.gpg /tmp/mega-release.key; \
    rm -f /tmp/mega-release.key; \
    echo "deb [arch=amd64,arm64 signed-by=/etc/apt/keyrings/mega.nz.gpg] https://mega.nz/linux/repo/Debian_12/ ./" > /etc/apt/sources.list.d/mega.nz.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends megacmd; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in amd64|arm64) cf_arch="$arch" ;; *) echo "Unsupported cloudflared arch: $arch" && exit 1 ;; esac; \
    curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cf_arch}" \
        -o /usr/local/bin/cloudflared; \
    chmod +x /usr/local/bin/cloudflared; \
    curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
        https://deno.land/install.sh \
        -o /tmp/deno-install.sh; \
    DENO_INSTALL=/usr/local sh /tmp/deno-install.sh; \
    rm -f /tmp/deno-install.sh

# Debian Bookworm ships FFmpeg 5.1, which lacks the AV1 workflow support used
# by this project.  Build the pinned FFmpeg 8.1.2 release instead of silently
# falling back to the distro package.  Keep libsvtav1 and libaom enabled for
# modern AV1 encode paths, alongside the existing H.264/H.265/Opus support.
# MEGAcmd adds a duplicate source with a different keyring.  Remove it before
# this next apt-get update without invalidating the completed package layer.
ARG FFMPEG_VERSION=8.1.2
RUN set -eux; \
    find /etc/apt/sources.list.d -maxdepth 1 -type f \
        -exec grep -l 'meganz-archive-keyring.gpg' {} + \
        | xargs -r rm -f; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        nasm \
        yasm \
        cmake \
        libaom-dev \
        libass-dev \
        libdav1d-dev \
        libfontconfig1-dev \
        libfreetype6-dev \
        libmp3lame-dev \
        libopus-dev \
        libx264-dev \
        libx265-dev \
        libvorbis-dev \
        libvpx-dev \
        libwebp-dev \
        libzimg-dev; \
    git clone --depth 1 https://github.com/nekotrix/SVT-AV1-Essential.git /tmp/svt-av1; \
    cd /tmp/svt-av1/Build; \
    cmake .. -G"Unix Makefiles" -DCMAKE_BUILD_TYPE=Release; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    cd /usr/src/app; \
    curl -fsSLO "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    tar -xJf "ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    cd "ffmpeg-${FFMPEG_VERSION}"; \
    ./configure \
        --prefix=/usr/local \
        --enable-gpl \
        --enable-version3 \
        --enable-libaom \
        --enable-libass \
        --enable-libdav1d \
        --enable-libfontconfig \
        --enable-libfreetype \
        --enable-libmp3lame \
        --enable-libopus \
        --enable-libsvtav1 \
        --enable-libvorbis \
        --enable-libvpx \
        --enable-libwebp \
        --enable-libx264 \
        --enable-libx265 \
        --enable-libzimg \
        --disable-debug \
        --disable-doc; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    cd /; \
    rm -rf /tmp/svt-av1 \
           "/usr/src/app/ffmpeg-${FFMPEG_VERSION}" \
           "/usr/src/app/ffmpeg-${FFMPEG_VERSION}.tar.xz"; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Copy and install python requirements
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip uv wheel

# The bot's Mega implementation uses the official MEGA SDK Python bindings
# (`from mega import MegaApi`), which are not provided by MEGAcmd or PyPI.
# v7.x is the latest upstream SDK line that still includes bindings/python.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libsodium-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ARG MEGA_SDK_VERSION=v7.0.0
RUN set -eux; \
    git clone --depth 1 --branch "$MEGA_SDK_VERSION" https://github.com/meganz/sdk.git /tmp/mega-sdk; \
    cd /tmp/mega-sdk; \
    ./autogen.sh; \
    sed -i 's/-std=c++11/-std=c++17/g' configure; \
    CXXFLAGS="-g -O2 -std=c++17" ./configure \
        --disable-silent-rules \
        --enable-python \
        --disable-examples \
        --without-freeimage \
        --without-libraw \
        --without-readline; \
    make -j"$(nproc)"; \
    cd /tmp/mega-sdk/bindings/python; \
    python setup.py bdist_wheel; \
    python -m pip install --no-cache-dir dist/*.whl; \
    python -c "from mega import MegaApi, MegaListener, MegaRequest, MegaTransfer; print('Mega SDK Python bindings OK')"; \
    rm -rf /tmp/mega-sdk

RUN uv pip install --system --no-cache -r requirements.txt

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
