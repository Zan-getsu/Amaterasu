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

# Ensure all required native tools are present.
# The base image ships most of them, but install anything missing.
RUN set -eux; \
    missing=""; \
    for pkg_check in \
        "aria2c:aria2" \
        "qbittorrent-nox:qbittorrent-nox" \
        "ffmpeg:ffmpeg" \
        "ffprobe:ffmpeg" \
        "rclone:rclone" \
        "sabnzbdplus:sabnzbdplus" \
        "7z:p7zip-full" \
        "mediainfo:mediainfo" \
        "java:default-jre-headless" \
        "curl:curl" \
        "git:git" \
        "pkill:procps" \
        "taskset:util-linux" \
        "cpulimit:cpulimit" \
        "unzip:unzip"; do \
        cmd="${pkg_check%%:*}"; \
        pkg="${pkg_check##*:}"; \
        if ! command -v "$cmd" >/dev/null 2>&1; then \
            missing="$missing $pkg"; \
        fi; \
    done; \
    if [ -n "$missing" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends $missing; \
        apt-get clean; \
        rm -rf /var/lib/apt/lists/*; \
    fi; \
    echo "=== Tool verification ==="; \
    for cmd in \
        aria2c qbittorrent-nox ffmpeg ffprobe rclone sabnzbdplus 7z \
        mediainfo java split curl git pkill taskset cpulimit unzip; do \
        command -v "$cmd"; \
    done

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
