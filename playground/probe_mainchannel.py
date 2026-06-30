"""Probe the main channel publishing flow end-to-end.

Tests:
  1. gather_facts() — assembles PublicationFacts from DB packs + TMDB enrichment
  2. Renders the caption template with the assembled facts
  3. Builds the [Index][Download] button row
  4. Shows the backdrop photo URL that will be used as the post image

Usage:
    python playground/probe_mainchannel.py <anime_doc_id>
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nekofetch.core.container import Container
from nekofetch.core.logging import setup_logging
from nekofetch.services.main_channel_service import MainChannelService


async def main() -> None:
    parser = argparse.ArgumentParser(description="Probe main channel publishing")
    parser.add_argument("anime_doc_id", help="Anime document ID to inspect (e.g. naruto-shippuden)")
    args = parser.parse_args()

    setup_logging(log_level="INFO", json=False)

    # Boot the container (needs DB + env configured)
    container = Container()
    await container.start()

    try:
        svc = MainChannelService(container)

        print(f"📡 Gathering facts for: {args.anime_doc_id!r}")
        facts = await svc.gather_facts(args.anime_doc_id)

        print("\n" + "=" * 60)
        print("📊 PUBLICATION FACTS")
        print("=" * 60)
        for field in ("anime_doc_id", "title", "tag", "episodes", "qualities",
                      "languages", "genres", "overview", "poster_url",
                      "backdrop_url", "bot_username"):
            value = getattr(facts, field, None) or "—"
            if isinstance(value, str) and len(value) > 120:
                value = value[:120] + "…"
            print(f"  {field:20s}: {value}")

        print("\n" + "=" * 60)
        print("💬 CAPTION (rendered)")
        print("=" * 60)
        caption = svc._caption(facts)
        print(caption)

        print("\n" + "=" * 60)
        print("🔘 BUTTONS")
        print("=" * 60)
        markup = await svc._buttons(facts)
        if markup:
            for row in markup.inline_keyboard:
                for btn in row:
                    print(f"  [{btn.text}]  →  {btn.url or btn.callback_data}")
        else:
            print("  (no buttons — no index channel link or bot username)")

        print("\n📸 Photo URL for the post:")
        photo = facts.backdrop_url or facts.poster_url
        print(f"  {photo or '— (no image available)'}")

    finally:
        await container.stop()


asyncio.run(main())
