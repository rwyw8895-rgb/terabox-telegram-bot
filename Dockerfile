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
    procps \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY main.py .

RUN mkdir -p \
    /app/data/terabox_profile \
    /app/data/browser_downloads \
    /app/data/tg_data \
    /app/data/tg_temp

CMD ["python", "main.py"]