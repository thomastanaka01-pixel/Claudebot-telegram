"""
Unified download engine — routes Spotify, SoundCloud, and YouTube
URLs through a single interface with real-time progress callbacks.
"""
import asyncio
import re
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Awaitable
import yt_dlp

from config import (
    DOWNLOAD_DIR,
    AUDIO_FORMAT,
    AUDIO_QUALITY,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    COOKIES_FILE,
)

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]


class Platform(str, Enum):
    YOUTUBE = "youtube"
    SOUNDCLOUD = "soundcloud"
    SPOTIFY = "spotify"
    UNKNOWN = "unknown"


@dataclass
class DownloadResult:
    success: bool
    platform: Platform
    title: str = ""
    track_count: int = 0
    failed_count: int = 0
    output_dir: Path = DOWNLOAD_DIR
    error: str = ""


@dataclass
class ActiveDownload:
    url: str
    platform: Platform
    cancelled: bool = False
    completed_tracks: int = 0
    total_tracks: int = 0
    current_title: str = ""
    errors: list = field(default_factory=list)


_YOUTUBE_RE = re.compile(
    r"(youtube\.com/(watch|playlist|shorts)|youtu\.be/)", re.I
)
_SOUNDCLOUD_RE = re.compile(r"soundcloud\.com/", re.I)
_SPOTIFY_RE = re.compile(r"open\.spotify\.com/", re.I)


def detect_platform(url: str) -> Platform:
    if _SPOTIFY_RE.search(url):
        return Platform.SPOTIFY
    if _SOUNDCLOUD_RE.search(url):
        return Platform.SOUNDCLOUD
    if _YOUTUBE_RE.search(url):
        return Platform.YOUTUBE
    return Platform.UNKNOWN


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def _yt_opts(output_dir: Path, dl: ActiveDownload, loop: asyncio.AbstractEventLoop,
              on_progress: ProgressCallback) -> dict:
    """Build yt-dlp options with a live progress hook."""

    def progress_hook(d: dict):
        status = d.get("status")
        filename = Path(d.get("filename", "")).stem
        if status == "downloading":
            dl.current_title = filename
            pct = d.get("_percent_str", "?%").strip()
            speed = d.get("_speed_str", "?/s").strip()
            asyncio.run_coroutine_threadsafe(
                on_progress(f"⬇️ `{filename[:40]}` — {pct} @ {speed}"),
                loop,
            )
        elif status == "finished":
            dl.completed_tracks += 1
            asyncio.run_coroutine_threadsafe(
                on_progress(
                    f"✅ Track {dl.completed_tracks}/{dl.total_tracks or '?'}: `{filename[:40]}`"
                ),
                loop,
            )
        elif status == "error":
            dl.errors.append(filename)
            asyncio.run_coroutine_threadsafe(
                on_progress(f"⚠️ Failed: `{filename[:40]}`"),
                loop,
            )

    outtmpl = str(output_dir / "%(playlist_title)s" / "%(playlist_index)s - %(title)s.%(ext)s")
    opts: dict = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": False,
        "ignoreerrors": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": AUDIO_FORMAT,
                "preferredquality": AUDIO_QUALITY,
            },
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ],
        "writethumbnail": True,
        "addmetadata": True,
        "retries": 5,
        "fragment_retries": 5,
    }
    if COOKIES_FILE:
        opts["cookiefile"] = COOKIES_FILE
    return opts


async def _fetch_playlist_info(url: str) -> dict:
    """Extract playlist metadata without downloading."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": "in_playlist",
    }
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False) or {},
    )


async def _download_ytdlp(
    url: str,
    dl: ActiveDownload,
    output_dir: Path,
    on_progress: ProgressCallback,
) -> DownloadResult:
    loop = asyncio.get_event_loop()
    info = await _fetch_playlist_info(url)
    playlist_title = info.get("title") or info.get("webpage_url_basename") or "download"
    entries = info.get("entries") or []
    dl.total_tracks = len(entries) if entries else 1

    await on_progress(
        f"📋 *{playlist_title}*\n"
        f"🎵 {dl.total_tracks} track(s) detected on {dl.platform.value.capitalize()}\n"
        f"📂 Saving to `{output_dir}`"
    )

    safe_dir = output_dir / _sanitize(playlist_title)
    safe_dir.mkdir(parents=True, exist_ok=True)

    opts = _yt_opts(output_dir, dl, loop, on_progress)
    opts["outtmpl"] = str(safe_dir / "%(playlist_index)s - %(title)s.%(ext)s")

    def _run():
        if dl.cancelled:
            return
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    await loop.run_in_executor(None, _run)
    failed = len(dl.errors)
    return DownloadResult(
        success=not dl.cancelled,
        platform=dl.platform,
        title=playlist_title,
        track_count=dl.completed_tracks,
        failed_count=failed,
        output_dir=safe_dir,
    )


async def _download_spotify(
    url: str,
    dl: ActiveDownload,
    output_dir: Path,
    on_progress: ProgressCallback,
) -> DownloadResult:
    """
    Downloads Spotify playlists/albums/tracks via spotdl.
    spotdl resolves each Spotify track to a YouTube match and downloads it.
    """
    try:
        import spotdl
        from spotdl import Spotdl
        from spotdl.types.options import DownloaderOptionalOptions
    except ImportError:
        return DownloadResult(
            success=False,
            platform=Platform.SPOTIFY,
            error="spotdl is not installed. Run: pip install spotdl",
        )

    await on_progress("🔍 Resolving Spotify playlist via spotdl…")

    loop = asyncio.get_event_loop()

    def _run():
        client_args = {}
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            client_args = {
                "client_id": SPOTIFY_CLIENT_ID,
                "client_secret": SPOTIFY_CLIENT_SECRET,
            }
        downloader_opts: DownloaderOptionalOptions = {
            "output": str(output_dir / "{list-name}/{list-position} - {title}"),
            "format": AUDIO_FORMAT,
            "bitrate": f"{AUDIO_QUALITY}k",
            "save_file": None,
            "overwrite": "skip",
        }
        app = Spotdl(
            client_id=client_args.get("client_id", "5f573c9620494bae87890c0f08a60293"),
            client_secret=client_args.get("client_secret", "212476d9b0f3472eaa762d90b19b0ba8"),
            downloader_settings=downloader_opts,
        )
        songs, _ = app.search([url])
        dl.total_tracks = len(songs)
        asyncio.run_coroutine_threadsafe(
            on_progress(
                f"🎵 {dl.total_tracks} track(s) found\n📂 Saving to `{output_dir}`"
            ),
            loop,
        )
        results = []
        for idx, song in enumerate(songs, 1):
            if dl.cancelled:
                break
            asyncio.run_coroutine_threadsafe(
                on_progress(f"⬇️ {idx}/{dl.total_tracks}: `{song.display_name[:40]}`"),
                loop,
            )
            try:
                app.download(song)
                dl.completed_tracks += 1
            except Exception as e:
                dl.errors.append(str(e))
                asyncio.run_coroutine_threadsafe(
                    on_progress(f"⚠️ Failed: `{song.display_name[:40]}`"),
                    loop,
                )
        return songs[0].list_name if songs else "Spotify Download"

    playlist_name = await loop.run_in_executor(None, _run)
    return DownloadResult(
        success=not dl.cancelled,
        platform=Platform.SPOTIFY,
        title=str(playlist_name),
        track_count=dl.completed_tracks,
        failed_count=len(dl.errors),
        output_dir=output_dir,
    )


async def download(
    url: str,
    on_progress: ProgressCallback,
    output_dir: Path = DOWNLOAD_DIR,
) -> DownloadResult:
    """Main entry point — detect platform and dispatch to the right downloader."""
    platform = detect_platform(url)
    dl = ActiveDownload(url=url, platform=platform)

    if platform == Platform.UNKNOWN:
        return DownloadResult(
            success=False,
            platform=Platform.UNKNOWN,
            error=(
                "Could not detect platform. Supported URLs:\n"
                "• youtube.com/playlist?list=…\n"
                "• soundcloud.com/user/sets/…\n"
                "• open.spotify.com/playlist/…"
            ),
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    if platform == Platform.SPOTIFY:
        return await _download_spotify(url, dl, output_dir, on_progress)
    else:
        return await _download_ytdlp(url, dl, output_dir, on_progress)
