# Lazy DJ Bot

A Telegram bot that acts as your remote control to download playlists and tracks from **YouTube**, **SoundCloud**, and **Spotify** into a single local music folder.

## Features

| Platform | Playlists | Albums | Single tracks |
|----------|-----------|--------|---------------|
| YouTube | ✅ | — | ✅ |
| SoundCloud | ✅ | — | ✅ |
| Spotify | ✅ | ✅ | ✅ |

- Real-time progress updates in Telegram
- Automatic platform detection — just paste the URL
- Downloads to `~/Music/LazyDJ/<playlist-name>/`
- Configurable output format (MP3/FLAC/WAV/M4A/Opus) and bitrate
- Optional user whitelist for private deployments

## Quick start

### 1. Prerequisites

```bash
# Python 3.11+
python --version

# FFmpeg (required for audio conversion)
# Ubuntu/Debian
sudo apt install ffmpeg
# macOS
brew install ffmpeg
# Windows — download from https://ffmpeg.org/download.html
```

### 2. Clone & install

```bash
git clone <this-repo>
cd Claudebot-telegram
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set TELEGRAM_TOKEN
```

**Get a Telegram token:** open [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, follow the prompts.

**Spotify (optional):** create an app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and add `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` to `.env`. Without these, `spotdl` falls back to its bundled public credentials which may be rate-limited.

### 4. Run

```bash
python bot.py
```

The bot runs in long-polling mode — no public server or SSL certificate needed. It works perfectly from a home desktop or laptop.

## Bot commands

| Command | Description |
|---------|-------------|
| `/download <url>` | Download a playlist or track |
| `/status` | Show your active downloads |
| `/cancel` | Cancel all your running downloads |
| `/help` | Show command reference |

You can also just **paste a URL directly** without the `/download` prefix.

## Example URLs

```
# YouTube playlist
https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI

# SoundCloud playlist
https://soundcloud.com/artist/sets/my-playlist

# Spotify playlist
https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M

# Spotify album
https://open.spotify.com/album/4eLPsYPBmXABThSJ821sqY

# Single YouTube video
https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

## Running as a background service (Linux)

```ini
# /etc/systemd/system/lazydj.service
[Unit]
Description=Lazy DJ Telegram Bot
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/path/to/Claudebot-telegram
EnvironmentFile=/path/to/Claudebot-telegram/.env
ExecStart=/path/to/Claudebot-telegram/.venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now lazydj
```

## Architecture

```
bot.py          — Telegram interface & command routing
downloader.py   — Unified download engine
  ├── yt-dlp   — YouTube & SoundCloud
  └── spotdl   — Spotify (resolves to YouTube internally)
config.py       — Environment-based settings
```
