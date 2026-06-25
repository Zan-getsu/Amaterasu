ARG BASE_IMAGE=nbots/amaterasu:v1
FROM ${BASE_IMAGE}

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/amaterasuvenv \
    PATH="/amaterasuvenv/bin:${PATH}"

WORKDIR /usr/src/app

# Restore the symlinks for the obfuscated binaries in wzmlx:v3.
# The base image provides these under custom names; we must link them back
# to the standard names before apt tries to install anything.
RUN set -eux; \
    link_cmd() { \
        if command -v "$2" >/dev/null 2>&1; then return 0; fi; \
        if command -v "$1" >/dev/null 2>&1; then \
            ln -sf "$(command -v "$1")" "/usr/local/bin/$2"; \
        fi; \
    }; \
    link_cmd blitzfetcher aria2c; \
    link_cmd stormtorrent qbittorrent-nox; \
    link_cmd mediaforge ffmpeg; \
    link_cmd ghostdrive rclone; \
    link_cmd newsripper sabnzbdplus

# Install all required native tools. The base image may already have some;
# apt will skip packages that are already present.

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        aria2 \
        curl \
        cpulimit \
        default-jre-headless \
        git \
        mediainfo \
        p7zip-full \
        procps \
        qbittorrent-nox \
        rclone \
        sabnzbdplus \
        unzip \
        util-linux \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


RUN set -eux; \
    if [ -d /wzvenv ] && [ ! -e /amaterasuvenv ]; then \
        ln -s /wzvenv /amaterasuvenv; \
    fi; \
    if [ ! -x /amaterasuvenv/bin/python ]; then \
        python3 -m venv /amaterasuvenv; \
    fi; \
    /amaterasuvenv/bin/python -m pip install --no-cache-dir --upgrade pip uv wheel; \
    /amaterasuvenv/bin/python -c "from mega import MegaApi, MegaListener, MegaRequest, MegaTransfer; print('Mega SDK Python bindings OK')"

COPY requirements.txt .
RUN uv pip install --python /amaterasuvenv/bin/python --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' *.sh \
    && chmod +x start.sh

CMD ["bash", "start.sh"]
