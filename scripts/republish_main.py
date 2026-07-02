"""Republish all anime entries to the new main channel (-1002026477147).

Flow per entry:
1. Fetch fresh message FROM OLD CHANNEL using userbot
2. Download photo to temp file
3. Parse caption → rebuild as proper HTML (bot's template)
4. Send to MAIN channel using BOT with send_photo + HTML + buttons + silent
5. Track mapping (old_id → new_id) for index channel update
6. Save progress after each post (resumable)

Usage:
    PYTHONIOENCODING=utf-8 python scripts/republish_main.py
"""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
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
PROGRESS_PATH = os.path.expanduser("~/Documents/republish_progress.json")

MAIN_CHANNEL = -1002026477147
OLD_CHANNEL = -1002176961000
_INTERNAL_MAIN = str(MAIN_CHANNEL).replace("-100", "", 1)

POST_DELAY = 3  # seconds between posts
FLOOD_WAIT_BASE = 5  # base delay for flood-wait retries


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


def load_progress() -> set[int]:
    """Load set of old_ids that were already published (for resumability)."""
    if not os.path.exists(PROGRESS_PATH):
        return set()
    try:
        with open(PROGRESS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {p["old_id"] for p in data.get("published", [])}
    except (json.JSONDecodeError, KeyError):
        return set()


def save_progress(published: list[dict]) -> None:
    """Save progress to disk after each post."""
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "main_channel": MAIN_CHANNEL,
            "total_published": len(published),
            "published": published,
        }, f, indent=2, ensure_ascii=False)


async def main():
    # Load entries
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    all_entries = data.get("publishable_entries", [])
    print(f"Total publishable: {len(all_entries)}")

    # Load progress (skip already-published)
    done_ids = load_progress()
    entries = [e for e in all_entries if e.get("id") not in done_ids]
    print(f"Already published: {len(done_ids)}")
    if not entries:
        print("All entries already published!")
        return

    # Load existing published list
    published = []
    if os.path.exists(PROGRESS_PATH):
        try:
            with open(PROGRESS_PATH, encoding="utf-8") as f:
                published = json.load(f).get("published", [])
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"Remaining to publish: {len(entries)}")

    # Start userbot (for downloading photos from old channel)
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()
    print("Userbot connected")

    # Start bot client (for sending with buttons)
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
    print(f"Target: {MAIN_CHANNEL}")
    print()

    total_count = len(all_entries)
    start_idx = total_count - len(entries)

    try:
        for i, entry in enumerate(entries):
            idx = start_idx + i + 1
            old_id = entry.get("id")
            title = entry.get("title", "?")

            print(f"[{idx}/{total_count}] {title} (msg {old_id})...", end=" ", flush=True)

            # 1. Fetch fresh message from old channel
            fresh = None
            try:
                fresh = await userbot.get_messages(OLD_CHANNEL, old_id)
            except Exception:
                pass

            caption_text = (fresh.caption if fresh else None) or entry.get("caption", "")

            # 2. Download photo to temp file
            photo_path = None
            if fresh and fresh.photo:
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                    tmp.close()
                    dl = await userbot.download_media(fresh, file_name=tmp.name)
                    if dl and Path(dl).exists():
                        photo_path = dl
                except Exception:
                    if os.path.exists(tmp.name):
                        try:
                            os.unlink(tmp.name)
                        except OSError:
                            pass

            # 3. Parse + rebuild as HTML
            parsed = parse_caption(caption_text)
            html_caption = build_html_caption(parsed)

            # 4. Build buttons — INDEX + DOWNLOAD
            index_btn = InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310")
            dl_buttons = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in entry.get("download_channels", [])
            ]
            markup = InlineKeyboardMarkup([[index_btn] + dl_buttons])

            # 5. Send via BOT with retry on flood-wait
            sent = None
            for attempt in range(3):  # retry up to 3 times
                try:
                    if photo_path:
                        sent = await bot.send_photo(
                            MAIN_CHANNEL,
                            photo=photo_path,
                            caption=html_caption,
                            reply_markup=markup,
                            parse_mode=ParseMode.HTML,
                            disable_notification=True,
                        )
                    else:
                        sent = await bot.send_message(
                            MAIN_CHANNEL,
                            html_caption,
                            reply_markup=markup,
                            parse_mode=ParseMode.HTML,
                            disable_notification=True,
                        )
                    break  # success
                except Exception as exc:
                    err = str(exc)
                    if "FLOOD_WAIT" in err:
                        m = re.search(r"FLOOD_WAIT_(\d+)", err)
                        wait = int(m.group(1)) if m else FLOOD_WAIT_BASE * (2 ** attempt)
                        print(f"flood-wait {wait}s...", end=" ", flush=True)
                        await asyncio.sleep(wait + 2)
                    elif attempt < 2:
                        await asyncio.sleep(FLOOD_WAIT_BASE)
                    else:
                        print(f"FAILED: {err[:80]}")
                        break

            if sent is None:
                # Clean up and skip
                if photo_path:
                    try:
                        os.unlink(photo_path)
                    except OSError:
                        pass
                print()
                continue

            new_id = sent.id
            new_link = f"https://t.me/c/{_INTERNAL_MAIN}/{new_id}"
            print(f"msg {new_id}")

            # 6. Track mapping
            published.append({
                "old_id": old_id,
                "new_id": new_id,
                "title": title,
                "old_link": entry.get("old_link", ""),
                "new_link": new_link,
                "download_channels": [b["url"] for b in entry.get("download_channels", [])],
            })

            # 7. Save progress
            save_progress(published)

            # 8. Clean up temp photo
            if photo_path:
                try:
                    os.unlink(photo_path)
                except OSError:
                    pass

            # 9. Delay to avoid flood-wait
            await asyncio.sleep(POST_DELAY)

    finally:
        await bot.stop()
        await pool.close()
        await container.shutdown()

    # Final summary
    print(f"\n{'='*50}")
    print(f"Done! Published {len(published)}/{total_count} entries")
    print(f"Progress saved to: {PROGRESS_PATH}")
    print(f"Main channel: https://t.me/c/{_INTERNAL_MAIN}/")

    # Print mapping for index update
    print(f"\nMapping for index channel update:")
    print(f"(old_id → new_id)")
    for p in published:
        print(f"  {p['old_id']} → {p['new_id']}  ({p['title']})")


if __name__ == "__main__":
    asyncio.run(main())
