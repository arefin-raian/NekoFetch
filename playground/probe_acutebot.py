"""Probe @acutebot integration — metadata fetch + photo download end-to-end.

Usage:
    python playground/probe_acutebot.py <title> [--photo-dir <path>]

Tests:
  1. Sends /anime <title> to @acutebot via the userbot pool
  2. Parses the info card into structured metadata (title, genres, score, synopsis, etc.)
  3. Downloads the card photo to a persistent directory (optional)
  4. Prints the parsed metadata and photo path

Example:
    python playground/probe_acutebot.py "Attack on Titan"
    python playground/probe_acutebot.py "Naruto" --photo-dir /tmp/acutebot_test
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nekofetch.core.config import get_env
from nekofetch.core.logging import setup_logging
from nekofetch.sources.telegram.userbot import UserbotPool


async def main() -> None:
    parser = argparse.ArgumentParser(description="Probe @acutebot metadata + photo")
    parser.add_argument("title", help="Anime title to query")
    parser.add_argument("--photo-dir", default=None, help="Persistent directory for the downloaded photo")
    args = parser.parse_args()

    # Set up logging so we can see acutebot debug output
    # (The log level is controlled by LOG_LEVEL env — default INFO shows warnings+)
    setup_logging(log_level="DEBUG", json=False)

    env = get_env()
    pool = UserbotPool.from_env(env.telegram_api_id, env.telegram_api_hash,
                                str(env.session_path))

    from nekofetch.providers.acute_bot import fetch_from_acutebot

    print(f"🔍 Querying @acutebot for: {args.title!r}")
    meta = await fetch_from_acutebot(args.title, pool, photo_dir=args.photo_dir)

    if meta is None:
        print("❌ AcuteBot returned no data (unreachable or title not found)")
        return

    print("\n" + "=" * 60)
    print("📋 PARSED METADATA")
    print("=" * 60)
    for key, value in meta.items():
        if key == "_source":
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            value = ", ".join(value) if value else "—"
        elif value is None:
            value = "—"
        print(f"  {label:20s}: {value}")

    if args.photo_dir:
        safe = "".join(c for c in args.title if c.isalnum() or c in (" ", "-", "_")).strip()
        safe = safe.replace(" ", "_")[:64] or "anime"
        expected = Path(args.photo_dir) / f"{safe}.jpg"
        if expected.exists():
            size_kb = expected.stat().st_size / 1024
            print(f"\n📸 Photo saved: {expected} ({size_kb:.1f} KB)")
        else:
            print(f"\n⚠️ Photo not found at expected path: {expected}")


asyncio.run(main())
