import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ALLOWED_USERS = os.getenv("ALLOWED_USERS", "")  # comma-separated Telegram user IDs; empty = allow all
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", str(Path.home() / "Music" / "LazyDJ")))
AUDIO_FORMAT = os.getenv("AUDIO_FORMAT", "mp3")        # mp3, flac, wav, m4a, opus
AUDIO_QUALITY = os.getenv("AUDIO_QUALITY", "320")      # kbps for mp3
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
COOKIES_FILE = os.getenv("COOKIES_FILE", "")           # optional: path to cookies.txt for age-gated content

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
