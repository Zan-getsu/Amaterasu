ARG BASE_IMAGE=nbots/amaterasu:v1

FROM python:3.11-slim-bookworm AS aria2-provider

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends aria2 binutils; \
    mkdir -p /aria2-out/opt/aria2/bin /aria2-out/opt/aria2/lib /aria2-out/usr/local/bin; \
    cp /usr/bin/aria2c /aria2-out/opt/aria2/bin/aria2c; \
    ldd /usr/bin/aria2c \
        | awk '/=> \// {print $3} /^\// {print $1}' \
        | sort -u \
        | xargs -r -I '{}' cp '{}' /aria2-out/opt/aria2/lib/; \
    cp /lib/*/libnss_dns.so.2 /lib/*/libnss_files.so.2 /aria2-out/opt/aria2/lib/ 2>/dev/null || true; \
    loader="$(readelf -l /usr/bin/aria2c | awk '/Requesting program interpreter/ {gsub(/[][]/, "", $NF); print $NF}')"; \
    cp "$loader" /aria2-out/opt/aria2/lib/; \
    loader_name="$(basename "$loader")"; \
    printf '#!/bin/sh\nexec /opt/aria2/lib/%s --library-path /opt/aria2/lib /opt/aria2/bin/aria2c "$@"\n' "$loader_name" > /aria2-out/usr/local/bin/aria2c; \
    chmod +x /aria2-out/usr/local/bin/aria2c; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

FROM ${BASE_IMAGE}

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/amaterasuvenv \
    PATH="/amaterasuvenv/bin:${PATH}"

WORKDIR /usr/src/app

COPY --from=aria2-provider /aria2-out/ /

COPY requirements.txt .
RUN uv pip install --python /amaterasuvenv/bin/python --no-cache-dir -r requirements.txt
RUN /usr/local/bin/aria2c --version

COPY . .

RUN sed -i 's/\r$//' *.sh \
    && chmod +x start.sh

CMD ["bash", "start.sh"]
