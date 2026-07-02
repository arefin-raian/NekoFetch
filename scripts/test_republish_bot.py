"""Test republish using ADMIN BOT (not userbot) with photos.

Bot accounts CAN post inline keyboards to channels, user accounts can't.

Flow per entry:
1. Fetch fresh caption + photo FROM OLD CHANNEL using userbot
2. Download photo to temp file using userbot
3. Parse caption → rebuild as proper HTML
4. Send to test channel using BOT with send_photo + HTML + buttons
5. Clean up temp file

Usage:
    PYTHONIOENCODING=utf-8 python scripts/test_republish_bot.py
"""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.core.config import get_env
from nekofetch.sources.telegram.userbot import UserbotPool
from nekofetch.core.container import Container

PUBLISHABLE_PATH = os.path.expanduser("~/Documents/publishable_entries.json")

TEST_CHANNEL = -1002383780897
OLD_CHANNEL = -1002176961000


def parse_caption(text: str) -> dict:
    """Parse old-format plaintext caption into structured fields."""
    result: dict = {"title": "?", "tag": "?", "episodes": "?",
                    "qualities": "?", "languages": "?", "genres": "?", "overview": "?"}

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

    tag_match = re.search(r'『\s*#([^』]+)』', title_line)
    if tag_match:
        result["tag"] = tag_match.group(1).strip()
        title_raw = re.sub(r'\s*『\s*#[^』]+』\s*', '', title_line).strip()
        result["title"] = title_raw
    else:
        result["title"] = title_line

    for line in lines:
        line = line.strip()
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

    overview_match = re.search(r'‣\s*OverView\s*:\s*(.*)', text, re.DOTALL)
    if overview_match:
        result["overview"] = overview_match.group(1).strip()

    return result


def build_html_caption(data: dict) -> str:
    """Rebuild as proper HTML matching the bot's template format."""
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
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("publishable_entries", [])

    test_entries = entries[:3]
    print(f"Testing {len(test_entries)} entries\n")

    # 1. Start userbot (to download photos from old channel)
    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()
    print("Userbot connected")

    # 2. Start bot client (to send with buttons)
    env = get_env()
    bot = Client(
        name="nekofetch-republish",
        api_id=env.telegram_api_id,
        api_hash=env.telegram_api_hash,
        bot_token=env.admin_bot_token,
        workdir=str(env.session_path),
        plugins=None,
    )
    await bot.start()
    me = await bot.get_me()
    print(f"Bot connected: @{me.username}")

    try:
        for i, entry in enumerate(test_entries):
            old_id = entry.get("id")
            title = entry.get("title", "?")
            print(f"\n--- Test {i+1}/3: {title} (old msg {old_id}) ---")

            # 1. Fetch fresh message from old channel via userbot
            fresh = await userbot.get_messages(OLD_CHANNEL, old_id)
            if not fresh:
                print("  ✗ Could not fetch from old channel")
                continue

            caption_text = fresh.caption or entry.get("caption", "")

            # 2. Download photo to temp file
            photo_path = None
            if fresh.photo:
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    tmp.close()
                    dl_path = await userbot.download_media(fresh, file_name=tmp.name)
                    if dl_path and Path(dl_path).exists():
                        photo_path = dl_path
                        print(f"  ✓ Photo downloaded: {Path(photo_path).name}")
                    else:
                        os.unlink(tmp.name)
                except Exception as exc:
                    print(f"  ⚠ Photo download failed: {str(exc)[:80]}")

            # 3. Parse caption → rebuild as HTML
            parsed = parse_caption(caption_text)
            html_caption = build_html_caption(parsed)
            print(f"  Caption: {len(html_caption)} chars")

            # 4. Build buttons — "INDEX" and "DOWNLOAD"
            index_btn = InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310")
            dl_buttons = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in entry.get("download_channels", [])
            ]
            markup = InlineKeyboardMarkup([[index_btn] + dl_buttons])
            print(f"  Buttons: 1 INDEX + {len(dl_buttons)} DOWNLOAD")

            # 5. Send via BOT with photo + HTML + buttons + silent
            try:
                if photo_path:
                    sent = await bot.send_photo(
                        TEST_CHANNEL,
                        photo=photo_path,
                        caption=html_caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                        disable_notification=True,
                    )
                    print(f"  ✓ Sent with photo: msg {sent.id}")
                else:
                    sent = await bot.send_message(
                        TEST_CHANNEL,
                        html_caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                        disable_notification=True,
                    )
                    print(f"  ✓ Sent as text: msg {sent.id}")

                # Verify
                await asyncio.sleep(1)
                v = await bot.get_messages(TEST_CHANNEL, sent.id)
                has_txt = bool(v.text or v.caption)
                has_kb = bool(v.reply_markup)
                has_photo = bool(v.photo)
                print(f"  Verify: text={has_txt}, photo={has_photo}, kb={has_kb}")

                if v.reply_markup:
                    for ri, row in enumerate(v.reply_markup.inline_keyboard):
                        for b in row:
                            print(f"    [{b.text}] -> {b.url}")

            except Exception as exc:
                print(f"  ✗ Send failed: {str(exc)[:150]}")

            # 6. Clean up temp photo
            if photo_path:
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass

            await asyncio.sleep(2)

    finally:
        await bot.stop()
        await pool.close()
        await container.shutdown()

    internal = str(TEST_CHANNEL).replace("-100", "", 1)
    print(f"\nDone! Check: https://t.me/c/{internal}/")


if __name__ == "__main__":
    asyncio.run(main())
