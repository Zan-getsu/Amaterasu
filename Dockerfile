ARG BASE_IMAGE=mysterysd/wzmlx:v3
FROM ${BASE_IMAGE}

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/amaterasuvenv \
    PATH="/amaterasuvenv/bin:${PATH}"

WORKDIR /usr/src/app

RUN set -eux; \
    link_cmd() { \
        source_name="$1"; \
        target_name="$2"; \
        if command -v "$target_name" >/dev/null 2>&1; then \
            return 0; \
        fi; \
        source_path="$(command -v "$source_name")"; \
        ln -sf "$source_path" "/usr/local/bin/$target_name"; \
    }; \
    link_cmd blitzfetcher aria2c; \
    link_cmd stormtorrent qbittorrent-nox; \
    link_cmd mediaforge ffmpeg; \
    link_cmd ghostdrive rclone; \
    link_cmd newsripper sabnzbdplus; \
    for cmd in \
        aria2c qbittorrent-nox ffmpeg ffprobe rclone sabnzbdplus 7z \
        mediainfo java split curl git pkill taskset cpulimit unzip; do \
        command -v "$cmd"; \
    done; \
    aria2c --version; \
    qbittorrent-nox --version; \
    ffmpeg -version; \
    ffprobe -version; \
    rclone --version; \
    sabnzbdplus --version; \
    7z i; \
    mediainfo --Version; \
    java -version

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
