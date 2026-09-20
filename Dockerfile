# ============================================================
# Stage 1: Build official Telegram Bot API
# ============================================================
FROM ubuntu:24.04 AS telegram-bot-api-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    g++ \
    make \
    cmake \
    gperf \
    zlib1g-dev \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN git clone --recursive --depth 1 \
    https://github.com/tdlib/telegram-bot-api.git

WORKDIR /build/telegram-bot-api

RUN mkdir build \
    && cd build \
    && cmake -DCMAKE_BUILD_TYPE=Release \
              -DCMAKE_INSTALL_PREFIX=/usr/local .. \
    && cmake --build . --target install -j2


# ============================================================
# Stage 2: TeraBox Telegram Bot
# ============================================================
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    fluxbox \
    x11vnc \
    novnc \
    websockify \
    x11-utils \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=telegram-bot-api-builder \
    /usr/local/bin/telegram-bot-api \
    /usr/local/bin/telegram-bot-api

RUN chmod +x /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY main.py .

RUN mkdir -p /app/data/terabox_profile \
             /app/data/browser_downloads \
             /app/data/tg_data \
             /app/data/tg_temp

CMD ["python", "main.py"]
