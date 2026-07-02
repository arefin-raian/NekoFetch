"""Full republish to main channel — SILENT, with photos, HTML, buttons.

Downloads each photo from old channel via userbot, then sends via bot
with parse_mode=HTML + reply_markup (INDEX + DOWNLOAD buttons) + silent.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/republish_final.py
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
OUTPUT_PATH = os.path.expanduser("~/Documents/new_main_posts_v2.json")

MAIN_CHANNEL = -1002026477147
OLD_CHANNEL = -1002176961000
_INTERNAL_NEW = str(MAIN_CHANNEL).replace("-100", "", 1)

# Track new posts for index channel update
new_posts: list[dict] = []


def parse_caption(text: str) -> dict:
    result: dict = {"title": "?", "tag": "?", "episodes": "?",
                    "qualities": "?", "languages": "?", "genres": "?", "overview": "?"}
    if not text:
        return result
    lines = text.strip().split("\n")
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
    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    title = esc(data["title"])
    tag = esc(data["tag"])
    episodes = esc(data["episodes"])
    qualities = esc(data["qualities"])
    languages = esc(data["languages"])
    genres = esc(data["genres"])
    overview = esc(data["overview"])
    return (
        f"<blockquote><b>{title}『 </b>#{tag} <b>』</b></blockquote>\n\n"
        f"<b>⌬ EPISODES :</b> {episodes}\n"
        f"<b>⌬ QUALITY :</b> {qualities}\n"
        f"<b>⌬ LANGUAGE :</b> {languages}\n"
        f"<b>⌬ GENRE :</b> {genres}\n\n"
        f"<blockquote expandable><b>‣ OverView :</b> {overview}</blockquote>"
    )


async def main():
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("publishable_entries", [])
    total = len(entries)
    print(f"Publishing {total} entries to main channel...\n")

    # Userbot (download photos from old channel)
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()

    # Bot (send with buttons)
    env = get_env()
    import time as _time
    bot = Client(
        name=f"repub-{int(_time.time())}",
        api_id=env.telegram_api_id,
        api_hash=env.telegram_api_hash,
        bot_token=env.admin_bot_token,
        workdir=str(env.session_path),
        in_memory=True,
        plugins=None,
    )
    await bot.start()

    try:
        for i, entry in enumerate(entries):
            old_id = entry.get("id")
            title = entry.get("title", "?")

            # Fetch fresh message from old channel
            fresh = await userbot.get_messages(OLD_CHANNEL, old_id)
            if not fresh:
                print(f"  [{i+1}/{total}] {title} — SKIP (no old msg)")
                continue

            caption_text = fresh.caption or entry.get("caption", "")

            # Download photo
            photo_path = None
            if fresh.photo:
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    tmp.close()
                    dl = await userbot.download_media(fresh, file_name=tmp.name)
                    if dl and Path(dl).exists():
                        photo_path = dl
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    pass

            # Parse + build HTML
            parsed = parse_caption(caption_text)
            html_caption = build_html_caption(parsed)

            # Buttons
            dl_buttons = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in entry.get("download_channels", [])
            ]
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310")] + dl_buttons
            ])

            # Send
            try:
                if photo_path:
                    sent = await bot.send_photo(
                        MAIN_CHANNEL, photo=photo_path,
                        caption=html_caption, reply_markup=markup,
                        parse_mode=ParseMode.HTML, disable_notification=True,
                    )
                else:
                    sent = await bot.send_message(
                        MAIN_CHANNEL, html_caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML, disable_notification=True,
                    )

                new_posts.append({
                    "title": title,
                    "old_id": old_id,
                    "new_id": sent.id,
                    "old_link": entry.get("old_link", ""),
                    "new_link": f"https://t.me/c/{_INTERNAL_NEW}/{sent.id}",
                })
                print(f"  [{i+1}/{total}] {title} → msg {sent.id}")

            except Exception as exc:
                print(f"  [{i+1}/{total}] {title} — FAILED: {str(exc)[:80]}")

            # Cleanup
            if photo_path:
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass

            # Small delay to avoid flood
            await asyncio.sleep(1.5)

        # Save tracking
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "main_channel": MAIN_CHANNEL,
                "total": total,
                "published": len(new_posts),
                "posts": new_posts,
            }, f, indent=2, ensure_ascii=False)

        print(f"\nDone! Published {len(new_posts)}/{total} entries")
        print(f"Tracking saved to: {OUTPUT_PATH}")

    finally:
        await bot.stop()
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
