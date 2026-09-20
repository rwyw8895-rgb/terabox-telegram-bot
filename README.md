# TeraBox Telegram Bot

Dockerized version of the working Google Colab bot.

## Current migration

- Colab Google Drive persistence -> Docker named volume
- Colab `/content/...` paths -> `/app/data/...`
- Colab Secrets -> environment variables
- Xvfb/Fluxbox/Chromium retained
- Downloader engine retained from the working notebook
- Telegram Bot API local-server support remains optional

## Run

1. Copy `.env.example` to `.env`
2. Fill in the Telegram credentials.
3. Build and start:

```bash
docker compose up -d --build
```

4. Logs:

```bash
docker compose logs -f
```

The first version intentionally keeps the local Telegram Bot API binary optional; without it, Telegram uses the normal cloud upload limit. We can add an ARM64-compatible local Bot API server after the base bot is verified.
