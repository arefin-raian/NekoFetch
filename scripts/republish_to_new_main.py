"""Republish all valid anime entries to the new main channel.

Reads the publishable entries list, posts each one to the new main channel
(-1002026477147) preserving the original structure:
- Same photo (using file_id)
- Same caption (HTML preserved)
- Same INDEX + DOWNLOAD buttons
- Tracks new message IDs for index channel update

Usage:
    PYTHONIOENCODING=utf-8 python scripts/republish_to_new_main.py
"""

import asyncio
import json
import logging
import os
import sys

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PUBLISHABLE_PATH = os.path.expanduser("~/Documents/publishable_entries.json")
OUTPUT_PATH = os.path.expanduser("~/Documents/new_main_posts.json")

NEW_CHANNEL = -1002026477147
INTERNAL_NEW = str(NEW_CHANNEL).replace("-100", "", 1)


async def main():
    # Load publishable entries
    with open(PUBLISHABLE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("publishable_entries", [])
    print(f"Loaded {len(entries)} publishable entries")

    # Connect userbot
    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    new_posts = []  # {title, old_id, new_id, old_link, new_link}

    try:
        client = await pool.acquire()
        print(f"Connected. Republishing to {NEW_CHANNEL}...\n")

        for i, entry in enumerate(entries):
            title = entry.get("title", "?")
            caption = entry.get("caption", "")
            photo = entry.get("photo", {})
            file_id = photo.get("file_id") if photo else None
            btns = entry.get("download_channels", [])
            old_link = entry.get("old_link", "")

            # Build inline keyboard markup
            # INDEX button (preserve original INDEX link)
            index_btn = InlineKeyboardButton("INDEX", url="https://t.me/ani_weebs_index/310")

            # DOWNLOAD buttons
            dl_buttons = [
                InlineKeyboardButton(b["text"], url=b["url"])
                for b in btns
            ]

            # INDEX and DOWNLOAD in the same row (matching original layout)
            markup = InlineKeyboardMarkup([[index_btn] + dl_buttons])

            print(f"  [{i+1}/{len(entries)}] {title}...", end=" ", flush=True)

            try:
                if file_id:
                    sent = await client.send_photo(
                        NEW_CHANNEL,
                        photo=file_id,
                        caption=caption,
                        reply_markup=markup,
                    )
                else:
                    sent = await client.send_message(
                        NEW_CHANNEL,
                        caption,
                        reply_markup=markup,
                    )

                new_id = sent.id
                new_link = f"https://t.me/c/{INTERNAL_NEW}/{new_id}"
                print(f"msg {new_id}")

                new_posts.append({
                    "title": title,
                    "old_id": entry.get("id"),
                    "new_id": new_id,
                    "old_link": old_link,
                    "new_link": new_link,
                })

                # Save progress after each post
                with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                    json.dump({
                        "new_channel": NEW_CHANNEL,
                        "total": len(entries),
                        "published_so_far": len(new_posts),
                        "posts": new_posts,
                    }, f, indent=2, ensure_ascii=False)

                # Delay between posts to avoid flood-wait
                await asyncio.sleep(3)

            except Exception as exc:
                err = str(exc)
                print(f"FAILED: {err[:80]}")
                if "FLOOD_WAIT" in err:
                    import re
                    m = re.search(r"FLOOD_WAIT_(\d+)", err)
                    wait = int(m.group(1)) if m else 30
                    print(f"  flood-wait {wait}s, waiting...")
                    await asyncio.sleep(wait + 2)
                    # Retry once
                    try:
                        if file_id:
                            sent = await client.send_photo(
                                NEW_CHANNEL, photo=file_id, caption=caption, reply_markup=markup
                            )
                        else:
                            sent = await client.send_message(
                                NEW_CHANNEL, caption, reply_markup=markup
                            )
                        new_posts.append({
                            "title": title,
                            "old_id": entry.get("id"),
                            "new_id": sent.id,
                            "old_link": old_link,
                            "new_link": f"https://t.me/c/{INTERNAL_NEW}/{sent.id}",
                        })
                        print(f"  retry success: msg {sent.id}")
                    except Exception as exc2:
                        print(f"  retry failed: {str(exc2)[:60]}")

        print(f"\n\nDone! Published {len(new_posts)}/{len(entries)} entries")
        print(f"Results saved to: {OUTPUT_PATH}")

    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
