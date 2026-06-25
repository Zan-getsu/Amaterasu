ARG BASE_IMAGE=amaterasu:v1
FROM ${BASE_IMAGE}

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/amaterasuvenv \
    PATH="/amaterasuvenv/bin:${PATH}"

WORKDIR /usr/src/app

COPY requirements.txt .
RUN uv pip install --python /amaterasuvenv/bin/python --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' *.sh \
    && chmod +x start.sh

CMD ["bash", "start.sh"]
