FROM python:3.11-slim

ENV LANG=C.UTF-8 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Dhaka \
    PYTHONUNBUFFERED=1

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
        build-essential \
        libssl-dev \
        libffi-dev \
        libxml2-dev \
        libxslt-dev \
        libmagic1 \
        locales \
        tzdata \
        ffmpeg \
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
        default-jre-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python requirements
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# Copy all the project files
COPY . .

# Setup permissions
RUN chmod +x start.sh

# Start the bot
CMD ["bash", "start.sh"]
