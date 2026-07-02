"""Test republish format — sends 3 sample posts to test channel.

Reads from the old channel live (fresh file_ids/captions), parses the plaintext
captions into structured data, rebuilds as proper HTML matching the bot's
template format, and sends to the test channel with ParseMode.HTML.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/test_republish_format.py
"""

import asyncio
import json
import logging
import os
import re
import sys

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

PUBLISHABLE_PATH = os.path.expanduser("~/Documents/publishable_entries.json")

TEST_CHANNEL = -1002383780897  # test channel — verify here first
OLD_CHANNEL = -1002176961000
_INTERNAL_OLD = str(OLD_CHANNEL).replace("-100", "", 1)


def parse_caption(text: str) -> dict:
    """Parse old-format plaintext caption into structured fields."""
    result: dict = {"title": "?", "tag": "?", "episodes": "?", "qualities": "?",
                    "languages": "?", "genres": "?", "overview": "?"}

    if not text:
        return result

    lines = text.strip().split("\n")

    # First non-empty line: "Title 『 #Tag 』"
    title_line = ""
    for line in lines:
        line = line.strip()
        if line:
            title_line = line
            break

    # Extract title and tag from 「『 #Tag 』」pattern
    tag_match = re.search(r'『\s*#([^』]+)』', title_line)
    if tag_match:
        result["tag"] = tag_match.group(1).strip()
        # Remove the tag portion to get just the title
        title_raw = re.sub(r'\s*『\s*#[^』]+』\s*', '', title_line).strip()
        result["title"] = title_raw

    # Parse metadata lines: 「⌬ KEY : VALUE」
    for line in lines:
        line = line.strip()
        # Match 「⌬ EPISODES : 12」patterns
        m = re.match(r'⌬\s*([^:]+?)\s*:\s*(.+)', line)
        if m:
            key = m.group(1).strip().lower()
            val = m.group(2).strip()
            if key == "episodes":
                result["episodes"] = val
            elif key == "quality":
                result["qualities"] = val
            elif key == "language":
                result["languages"] = val
            elif key == "genre":
                result["genres"] = val

    # Extract overview: 「‣ OverView : ...」
    overview_match = re.search(r'‣\s*OverView\s*:\s*(.*)', text, re.DOTALL)
    if overview_match:
        result["overview"] = overview_match.group(1).strip()

    return result


def build_html_caption(data: dict) -> str:
    """Rebuild as proper HTML matching the bot's template format."""
    # Escape HTML special chars
    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    title = esc(data["title"])
    tag = esc(data["tag"])
    episodes = esc(data["episodes"])
    qualities = esc(data["qualities"])
    languages = esc(data["languages"])
    genres = esc(data["genres"])
    overview = esc(data["overview"])

    caption = (
        f"<blockquote><b>{title}『 </b>#{tag} <b>』</b></blockquote>\n\n"
        f"<b>⌬ EPISODES :</b> {episodes}\n"
        f"<b>⌬ QUALITY :</b> {qualities}\n"
        f"<b>⌬ LANGUAGE :</b> {languages}\n"
        f"<b>⌬ GENRE :</b> {genres}\n\n"
        f"<blockquote expandable><b>‣ OverView :</b> {overview}</blockquote>"
    )
    return caption


async def main():
    # Load publishable entries
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("publishable_entries", [])
    print(f"Loaded {len(entries)} publishable entries")

    # Take first 3 for the test
    test_entries = entries[:3]
    print(f"Testing with {len(test_entries)} entries\n")

    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    client = await pool.acquire()
    print(f"Connected. Sending to test channel {TEST_CHANNEL}...\n")

    try:
        for i, entry in enumerate(test_entries):
            old_id = entry.get("id")
            title = entry.get("title", "?")

            print(f"--- Test {i+1}/3: {title} (msg {old_id}) ---")

            # 1. Fetch FRESH message from old channel to get live photo + caption
            fresh_msg = await client.get_messages(OLD_CHANNEL, old_id)
            if not fresh_msg:
                print(f"  ⚠ Could not fetch msg {old_id} from old channel, using stored data")
                caption_text = entry.get("caption", "")
                has_photo_data = bool(entry.get("photo"))
            else:
                caption_text = fresh_msg.caption or entry.get("caption", "")
                has_photo_data = bool(fresh_msg.photo or entry.get("photo"))
                print(f"  ✓ Fetched fresh message from old channel")

            # 2. Parse plaintext caption → structured data
            parsed = parse_caption(caption_text)
            print(f"  Parsed: title={parsed['title']!r}, tag={parsed['tag']!r}")

            # 3. Rebuild as HTML
            html_caption = build_html_caption(parsed)
            print(f"  HTML caption ({len(html_caption)} chars):")
            print(f"  {html_caption[:200]}...")
            print()

            # 4. Build buttons — INDEX + DOWNLOAD
            btns = entry.get("download_channels", [])
            index_btn = InlineKeyboardButton("ɪɴᴅᴇx", url="https://t.me/ani_weebs_index/310")
            dl_buttons = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in btns
            ]
            markup = InlineKeyboardMarkup([[index_btn] + dl_buttons])

            # 5. Send to test channel
            photo_url = None
            if has_photo_data and fresh_msg and fresh_msg.photo:
                # Use fresh file_id from the re-fetched message
                photo_file_id = fresh_msg.photo.file_id
                try:
                    sent = await client.send_photo(
                        TEST_CHANNEL,
                        photo=photo_file_id,
                        caption=html_caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                    )
                    print(f"  ✓ Sent with photo: msg {sent.id}")
                    continue
                except Exception as exc:
                    err = str(exc)
                    print(f"  ⚠ Photo send failed: {err[:80]}")
                    # Fall through to text-only

            # Fallback: send as text with the photo URL (or without)
            try:
                sent = await client.send_message(
                    TEST_CHANNEL,
                    html_caption,
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
                print(f"  ✓ Sent as text: msg {sent.id}")
            except Exception as exc:
                print(f"  ✗ Failed: {str(exc)[:100]}")

            await asyncio.sleep(2)  # small delay between tests
            print()

        print(f"\nDone! Check the test channel: https://t.me/c/{str(TEST_CHANNEL).replace('-100','',1)}/")

    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
