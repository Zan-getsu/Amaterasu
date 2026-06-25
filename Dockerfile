FROM mysterysd/wzmlx:v3

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/wzvenv \
    PATH="/wzvenv/bin:${PATH}"

WORKDIR /usr/src/app

COPY requirements.txt .
RUN set -eux; \
    if [ -x /wzvenv/bin/python ]; then \
        /wzvenv/bin/python -m pip install --no-cache-dir --upgrade pip uv wheel; \
        uv pip install --python /wzvenv/bin/python --no-cache-dir -r requirements.txt; \
    else \
        python3 -m pip install --no-cache-dir --upgrade pip uv wheel; \
        uv pip install --system --no-cache -r requirements.txt; \
    fi

COPY . .

RUN sed -i 's/\r$//' *.sh \
    && chmod +x start.sh \
    && mkdir -p /usr/src/app/downloads /JDownloader /data

CMD ["bash", "start.sh"]
