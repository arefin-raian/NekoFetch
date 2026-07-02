"""Publish My Little Monster (msg 325) to the new main channel.

Channel: My_Little_Monster_Ani_Weebs — ACTIVE ✅
This was the only unpublished anime with an active channel.
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

OLD_CHANNEL = -1002176961000
MAIN_CHANNEL = -1002026477147
_INTERNAL = str(MAIN_CHANNEL).replace("-100", "", 1)
TRACKING_PATH = os.path.expanduser("~/Documents/new_main_posts_v2.json")
MSG_ID = 325


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
    return (
        f"<blockquote><b>{esc(data['title'])}『 </b>#{esc(data['tag'])} <b>』</b></blockquote>\n\n"
        f"<b>⌬ EPISODES :</b> {esc(data['episodes'])}\n"
        f"<b>⌬ QUALITY :</b> {esc(data['qualities'])}\n"
        f"<b>⌬ LANGUAGE :</b> {esc(data['languages'])}\n"
        f"<b>⌬ GENRE :</b> {esc(data['genres'])}\n\n"
        f"<blockquote expandable><b>‣ OverView :</b> {esc(data['overview'])}</blockquote>"
    )


async def main():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()

    import time
    bot = Client(
        name=f"pub-mlm-{int(time.time())}",
        api_id=container.env.telegram_api_id,
        api_hash=container.env.telegram_api_hash,
        bot_token=container.env.admin_bot_token,
        workdir=str(container.env.session_path),
        in_memory=True,
        plugins=None,
    )
    await bot.start()

    try:
        print(f"Fetching msg {MSG_ID} from old channel...")
        fresh = await userbot.get_messages(OLD_CHANNEL, MSG_ID)
        if not fresh:
            print("ERROR: Could not get message from old channel")
            return

        caption_raw = fresh.caption or ""
        print(f"Caption length: {len(caption_raw)} chars")

        # Download photo
        photo_path = None
        if fresh.photo:
            try:
                tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                tmp.close()
                dl = await userbot.download_media(fresh, file_name=tmp.name)
                if dl and Path(dl).exists():
                    photo_path = dl
                    print(f"Photo downloaded: {dl}")
                else:
                    os.unlink(tmp.name)
            except Exception as e:
                print(f"Photo download failed: {e}")

        # Parse + build HTML
        parsed = parse_caption(caption_raw)
        html_caption = build_html_caption(parsed)
        print(f"\nHTML caption:\n{html_caption}\n")

        # Buttons
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310"),
             InlineKeyboardButton("DOWNLOAD", url="https://t.me/My_Little_Monster_Ani_Weebs")]
        ])

        # Send — SILENT
        print("Sending to main channel...")
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

        print(f"\n✅ Published: msg {sent.id}")
        print(f"   https://t.me/c/{_INTERNAL}/{sent.id}")

        # Save to tracking
        new_entry = {
            "title": "My Little Monster",
            "old_id": MSG_ID,
            "new_id": sent.id,
            "old_link": f"https://t.me/c/2176961000/{MSG_ID}",
            "new_link": f"https://t.me/c/{_INTERNAL}/{sent.id}",
        }

        all_posts = []
        if os.path.exists(TRACKING_PATH):
            with open(TRACKING_PATH, encoding="utf-8") as f:
                existing = json.load(f)
            all_posts = existing.get("posts", [])
        all_posts.append(new_entry)
        with open(TRACKING_PATH, "w", encoding="utf-8") as f:
            json.dump({"main_channel": MAIN_CHANNEL, "total": len(all_posts),
                       "published": len(all_posts), "posts": all_posts},
                      f, indent=2, ensure_ascii=False)

        # Cleanup photo
        if photo_path:
            try:
                os.unlink(photo_path)
            except OSError:
                pass

        # Verify
        print("\nVerifying...")
        verify_msg = await bot.get_messages(MAIN_CHANNEL, sent.id)
        if verify_msg:
            print(f"  photo: {bool(verify_msg.photo)}")
            print(f"  caption: {bool(verify_msg.caption or verify_msg.text)}")
            print(f"  buttons: {bool(verify_msg.reply_markup)}")
        print("\n✅ Done!")

    finally:
        await bot.stop()
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
