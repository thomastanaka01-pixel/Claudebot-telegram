"""
Quick smoke-test for the Lazy DJ download engine.
No Telegram token needed — runs entirely in the terminal.

Usage:
  python3 test_cli.py                        # platform-detection tests only
  python3 test_cli.py --fetch  <url>         # fetch metadata (no download)
  python3 test_cli.py --download <url>       # full download to /tmp/lazydj_test/
"""
import sys
import asyncio
from pathlib import Path

# ── 1. Platform-detection unit tests (no network) ────────────────────────────

from downloader import detect_platform, Platform

PLATFORM_CASES = [
    ("https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI", Platform.YOUTUBE),
    ("https://youtu.be/dQw4w9WgXcQ",                                              Platform.YOUTUBE),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",                               Platform.YOUTUBE),
    ("https://soundcloud.com/artist/sets/my-playlist",                             Platform.SOUNDCLOUD),
    ("https://soundcloud.com/artist/track-name",                                   Platform.SOUNDCLOUD),
    ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",                  Platform.SPOTIFY),
    ("https://open.spotify.com/album/4eLPsYPBmXABThSJ821sqY",                     Platform.SPOTIFY),
    ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",                     Platform.SPOTIFY),
    ("https://example.com/random",                                                  Platform.UNKNOWN),
]

def run_detection_tests():
    print("\n── Platform detection tests ─────────────────────────────")
    passed = failed = 0
    for url, expected in PLATFORM_CASES:
        got = detect_platform(url)
        ok = got == expected
        mark = "✅" if ok else "❌"
        label = url[:60].ljust(60)
        print(f"  {mark}  {label}  →  {got.value}")
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"       expected: {expected.value}")
    print(f"\n  {passed}/{passed+failed} passed")
    return failed == 0


# ── 2. Metadata fetch (network, no download) ──────────────────────────────────

async def run_fetch(url: str):
    import yt_dlp
    print(f"\n── Metadata fetch ───────────────────────────────────────")
    print(f"  URL: {url}")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "extract_flat": "in_playlist",
    }
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(
        None,
        lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False) or {},
    )
    title = info.get("title") or info.get("webpage_url_basename") or "(no title)"
    entries = info.get("entries") or []
    print(f"  Title      : {title}")
    print(f"  Track count: {len(entries) if entries else '1 (single track)'}")
    if entries:
        for i, e in enumerate(entries[:5], 1):
            print(f"    {i}. {e.get('title', e.get('url', '?'))[:70]}")
        if len(entries) > 5:
            print(f"    … and {len(entries)-5} more")
    print("  ✅ Fetch OK")


# ── 3. Full download (network + ffmpeg) ──────────────────────────────────────

async def run_download(url: str):
    from downloader import download
    out = Path("/tmp/lazydj_test")
    out.mkdir(exist_ok=True)
    print(f"\n── Full download test ───────────────────────────────────")
    print(f"  URL       : {url}")
    print(f"  Output dir: {out}\n")

    async def progress(msg: str):
        print(f"  {msg}")

    result = await download(url, progress, out)
    print()
    if result.success:
        print(f"  ✅ Done — '{result.title}'")
        print(f"     Tracks downloaded : {result.track_count}")
        if result.failed_count:
            print(f"     Failed           : {result.failed_count}")
        print(f"     Saved to         : {result.output_dir}")
    else:
        print(f"  ❌ Failed: {result.error}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--fetch" in args:
        idx = args.index("--fetch")
        url = args[idx + 1] if idx + 1 < len(args) else None
        if not url:
            print("Usage: python3 test_cli.py --fetch <url>")
            sys.exit(1)
        run_detection_tests()
        asyncio.run(run_fetch(url))

    elif "--download" in args:
        idx = args.index("--download")
        url = args[idx + 1] if idx + 1 < len(args) else None
        if not url:
            print("Usage: python3 test_cli.py --download <url>")
            sys.exit(1)
        run_detection_tests()
        asyncio.run(run_download(url))

    else:
        ok = run_detection_tests()
        print("\nTo test metadata fetching (no download):")
        print("  python3 test_cli.py --fetch 'https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI'")
        print("\nTo do a full download:")
        print("  python3 test_cli.py --download 'https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI'")
        sys.exit(0 if ok else 1)
