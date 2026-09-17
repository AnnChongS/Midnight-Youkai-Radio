#!/usr/bin/env python3
"""Download A-One Toho Eurobeat albums Vol 1–20 via yt-dlp."""

import os
import sys
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "Touhou_Eurobeat")

WARP_PROXY = os.environ.get("YTDLP_PROXY", "")

# A-One Toho Eurobeat — one search per volume
VOLUMES = [f"A-One Toho Eurobeat Vol {i}" for i in range(1, 21)]

# Additional A-One compilations / best-of
EXTRA = [
    "A-One Touhou Eurobeat Best",
    "A-One TOHO EUROBEAT COMPLETE",
    "東方 Eurobeat A-One",
]


def find_ytdlp() -> str:
    """Locate yt-dlp binary."""
    for name in ("yt-dlp", "yt-dlp.exe"):
        path = shutil.which(name)
        if path:
            return path
    print("[download_tracks] ERROR: yt-dlp not found.")
    print("  Install: pip install yt-dlp")
    sys.exit(1)


def download_query(ytdlp: str, query: str, output_dir: str) -> int:
    """Search YouTube for query, download best audio. Returns new-file count."""
    before = set(os.listdir(output_dir))
    cmd = [
        ytdlp,
        f"ytsearch10:{query}",
        "--js-runtimes", "node",
        "--proxy", WARP_PROXY,
        "--ignore-errors",
        "--no-abort-on-error",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--output", os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
        "--restrict-filenames",
        "--no-overwrites",
        "--match-filter", "duration < 1200",
        "--sleep-interval", "2",
        "--max-sleep-interval", "5",
        "--retries", "3",
        "--fragment-retries", "3",
    ]
    print(f"\n[download_tracks] === {query} ===")
    try:
        subprocess.run(cmd, timeout=900, check=False)
    except subprocess.TimeoutExpired:
        print(f"[download_tracks] Timeout: {query}")
    except Exception as e:
        print(f"[download_tracks] Error: {e}")

    after = set(os.listdir(output_dir))
    return len(after - before)


def main():
    ytdlp = find_ytdlp()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"[download_tracks] Output: {OUTPUT_DIR}")
    print(f"[download_tracks] Targeting A-One Toho Eurobeat Vol 1–20 + extras")

    total_new = 0

    for q in VOLUMES:
        count = download_query(ytdlp, q, OUTPUT_DIR)
        total_new += count
        print(f"[download_tracks]   -> {count} new tracks from '{q}'")

    for q in EXTRA:
        count = download_query(ytdlp, q, OUTPUT_DIR)
        total_new += count
        print(f"[download_tracks]   -> {count} new tracks from '{q}'")

    exts = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"}
    all_tracks = [
        f for f in os.listdir(OUTPUT_DIR)
        if os.path.splitext(f)[1].lower() in exts
    ]
    print(f"\n[download_tracks] Done. {total_new} new / {len(all_tracks)} total tracks in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
