"""CLEAN republish to main channel — chronological, silent, no doubles.

Each post is sent in the SAME order as the old main channel (msg 285 first).
Photos are downloaded fresh from old channel via userbot, then re-uploaded
via the admin bot (supports inline keyboards).
ALL sends use disable_notification=True — no subscriber alerts.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/republish_clean.py
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
TRACKING_PATH = os.path.expanduser("~/Documents/new_main_posts_v2.json")

MAIN_CHANNEL = -1002026477147
OLD_CHANNEL = -1002176961000
_INTERNAL_NEW = str(MAIN_CHANNEL).replace("-100", "", 1)


def parse_caption(text: str) -> dict:
    """Parse old-format plaintext caption into structured fields."""
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
    """Rebuild as proper HTML matching the bot's template format."""
    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<blockquote><b>{esc(data['title'])}『 </b>#{esc(data['tag'])} <b>』</b></blockquote>\n\n"
        f"<b>⌬ EPISODES :</b> {esc(data['episodes'])}\n"
        f"<b>⌬ QUALITY :</b> {esc(data['qualities'])}\n"
        f"<b>⌬ LANGUAGE :</b> {esc(data['languages'])}\n"
        f"<b>⌬ GENRE :</b> {esc(data['genres'])}\n\n"
        f"<blockquote expandable><b>‣ OverView :</b> {esc(data['overview'])}</blockquote>"
    )


async def main():
    # Load entries, sort chronologically (oldest first in old channel)
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    entries = sorted(data.get("publishable_entries", []), key=lambda e: e.get("id", 0))
    total = len(entries)

    # Load tracking to avoid doubles
    already_sent: set[int] = set()
    if os.path.exists(TRACKING_PATH):
        with open(TRACKING_PATH, encoding="utf-8") as f:
            existing = json.load(f)
        for p in existing.get("posts", []):
            already_sent.add(p.get("old_id"))
        print(f"Already sent: {len(already_sent)} entries")
    else:
        print("No previous tracking — starting fresh")

    # Filter out already-sent
    to_send = [e for e in entries if e.get("id") not in already_sent]
    print(f"To send now: {len(to_send)}/{total} (skipping {total - len(to_send)} already sent)\n")

    if not to_send:
        print("Nothing to send!")
        return

    # Connect userbot (download photos)
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()

    # Connect bot (send with buttons)
    import time
    bot = Client(
        name=f"repub-{int(time.time())}",
        api_id=container.env.telegram_api_id,
        api_hash=container.env.telegram_api_hash,
        bot_token=container.env.admin_bot_token,
        workdir=str(container.env.session_path),
        in_memory=True,
        plugins=None,
    )
    await bot.start()

    try:
        for i, entry in enumerate(to_send):
            old_id = entry.get("id")
            title = entry.get("title", "?")
            new_posts_list = []

            print(f"  [{i+1}/{len(to_send)}] msg {old_id} — {title}...", end=" ", flush=True)

            # 1. Fetch fresh from old channel
            fresh = await userbot.get_messages(OLD_CHANNEL, old_id)
            if not fresh:
                print("SKIP (no old msg)")
                continue

            caption_raw = fresh.caption or entry.get("caption", "")

            # 2. Download photo
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

            # 3. Parse + build HTML
            parsed = parse_caption(caption_raw)
            html_caption = build_html_caption(parsed)

            # 4. Buttons: INDEX + DOWNLOAD
            dl_btns = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in entry.get("download_channels", [])
            ]
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310")] + dl_btns
            ])

            # 5. Send — SILENT
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

                new_posts_list.append({
                    "title": title,
                    "old_id": old_id,
                    "new_id": sent.id,
                    "old_link": entry.get("old_link", ""),
                    "new_link": f"https://t.me/c/{_INTERNAL_NEW}/{sent.id}",
                })
                print(f"msg {sent.id} (silent)")

            except Exception as exc:
                print(f"FAILED: {str(exc)[:80]}")

            # Cleanup photo
            if photo_path:
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass

            # Save tracking after each post
            all_posts = []
            # Load existing tracking
            if os.path.exists(TRACKING_PATH):
                with open(TRACKING_PATH, encoding="utf-8") as f:
                    existing_data = json.load(f)
                all_posts = existing_data.get("posts", [])
            all_posts.extend(new_posts_list)
            with open(TRACKING_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "main_channel": MAIN_CHANNEL,
                    "total": total,
                    "published": len(all_posts),
                    "posts": all_posts,
                }, f, indent=2, ensure_ascii=False)

            # 1.5s delay to avoid flood
            await asyncio.sleep(1.5)

        # Final count
        with open(TRACKING_PATH, encoding="utf-8") as f:
            final = json.load(f)
        print(f"\nDone! Published {final['published']}/{total} entries total")

    finally:
        await bot.stop()
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
