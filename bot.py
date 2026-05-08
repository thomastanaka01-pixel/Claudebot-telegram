"""
Lazy DJ Bot — Telegram remote control for playlist downloads.

Commands:
  /start    — Welcome message
  /download <url> — Download a playlist or track
  /status   — Show active downloads
  /cancel   — Cancel all running downloads for your user
  /help     — Command reference
"""
import asyncio
import logging
import textwrap
from collections import defaultdict
from typing import Optional

from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import ALLOWED_USERS, DOWNLOAD_DIR, TELEGRAM_TOKEN
from downloader import Platform, download, detect_platform

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# user_id → list of asyncio.Task
_active: dict[int, list[asyncio.Task]] = defaultdict(list)
# task → cancellation flag
_cancel_flags: dict[asyncio.Task, list] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Auth helper
# ──────────────────────────────────────────────────────────────────────────────

def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    allowed = {int(uid.strip()) for uid in ALLOWED_USERS.split(",") if uid.strip()}
    return user_id in allowed


async def _deny(update: Update):
    await update.message.reply_text("⛔ You are not authorised to use this bot.")


# ──────────────────────────────────────────────────────────────────────────────
# Platform badge
# ──────────────────────────────────────────────────────────────────────────────

_BADGES = {
    Platform.YOUTUBE: "🎬 YouTube",
    Platform.SOUNDCLOUD: "🔊 SoundCloud",
    Platform.SPOTIFY: "🎵 Spotify",
    Platform.UNKNOWN: "❓ Unknown",
}


# ──────────────────────────────────────────────────────────────────────────────
# /start
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return await _deny(update)
    await update.message.reply_text(
        textwrap.dedent("""
            🎧 *Lazy DJ Bot* — your playlist downloader remote control

            Drop a playlist URL and I'll grab every track for you.

            *Supported platforms:*
            🎬 YouTube playlists & videos
            🔊 SoundCloud playlists & tracks
            🎵 Spotify playlists, albums & tracks

            *Commands:*
            `/download <url>` — start a download
            `/status` — show active downloads
            `/cancel` — cancel your running downloads
            `/help` — this message
        """),
        parse_mode=constants.ParseMode.MARKDOWN,
    )


# ──────────────────────────────────────────────────────────────────────────────
# /help
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)


# ──────────────────────────────────────────────────────────────────────────────
# /download
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_download(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        return await _deny(update)

    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Usage: `/download <url>`\n\nExample:\n`/download https://www.youtube.com/playlist?list=PLxxx`",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    url = args[0].strip()
    platform = detect_platform(url)

    if platform == Platform.UNKNOWN:
        await update.message.reply_text(
            "❌ Unrecognised URL. Paste a YouTube, SoundCloud, or Spotify link.",
        )
        return

    status_msg = await update.message.reply_text(
        f"{_BADGES[platform]} detected — queuing download…",
    )

    # Throttled progress updater — sends at most one Telegram edit per 3 s
    _last_text: list[str] = [""]
    _last_sent: list[float] = [0.0]

    async def on_progress(text: str):
        import time
        now = time.monotonic()
        if text == _last_text[0]:
            return
        _last_text[0] = text
        if now - _last_sent[0] < 3.0 and "✅" not in text and "⚠️" not in text:
            return
        _last_sent[0] = now
        try:
            await status_msg.edit_text(text, parse_mode=constants.ParseMode.MARKDOWN)
        except Exception:
            pass

    async def run_download():
        try:
            result = await download(url, on_progress, DOWNLOAD_DIR)
            if result.success:
                summary = (
                    f"✅ *Done!* {_BADGES[platform]}\n"
                    f"📀 *{result.title}*\n"
                    f"🎵 {result.track_count} track(s) downloaded"
                    + (f"\n⚠️ {result.failed_count} failed" if result.failed_count else "")
                    + f"\n📂 `{result.output_dir}`"
                )
            else:
                summary = f"❌ Download failed\n`{result.error}`"
            await status_msg.edit_text(summary, parse_mode=constants.ParseMode.MARKDOWN)
        except asyncio.CancelledError:
            await status_msg.edit_text("🛑 Download cancelled.")
        except Exception as e:
            log.exception("Download error")
            await status_msg.edit_text(f"💥 Unexpected error:\n`{e}`", parse_mode=constants.ParseMode.MARKDOWN)
        finally:
            tasks = _active.get(user.id, [])
            task = asyncio.current_task()
            if task in tasks:
                tasks.remove(task)

    task = asyncio.create_task(run_download())
    _active[user.id].append(task)


# ──────────────────────────────────────────────────────────────────────────────
# /status
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        return await _deny(update)

    tasks = [t for t in _active.get(user.id, []) if not t.done()]
    if not tasks:
        await update.message.reply_text("✅ No active downloads.")
        return
    await update.message.reply_text(f"⏳ {len(tasks)} download(s) running.\nUse /cancel to stop them.")


# ──────────────────────────────────────────────────────────────────────────────
# /cancel
# ──────────────────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        return await _deny(update)

    tasks = [t for t in _active.get(user.id, []) if not t.done()]
    if not tasks:
        await update.message.reply_text("Nothing to cancel.")
        return
    for t in tasks:
        t.cancel()
    _active[user.id].clear()
    await update.message.reply_text(f"🛑 Cancelled {len(tasks)} download(s).")


# ──────────────────────────────────────────────────────────────────────────────
# Plain URL message handler — no /download prefix needed
# ──────────────────────────────────────────────────────────────────────────────

async def handle_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """If the user pastes a bare URL, treat it as /download."""
    text = (update.message.text or "").strip()
    if text.startswith("http"):
        ctx.args = [text]
        await cmd_download(update, ctx)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN is not set. Add it to your .env file.")

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("download", cmd_download))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url)
    )

    log.info("Lazy DJ Bot starting — polling for updates…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
