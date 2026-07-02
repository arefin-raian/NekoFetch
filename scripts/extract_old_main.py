"""Full extraction of all anime posts from the old main channel.

Old Main Channel: -1002176961000
Saves extracted entries to: C:\\Users\\Admin\\Documents\\old_main_export.json

Usage:
    PYTHONIOENCODING=utf-8 python scripts/extract_old_main.py
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

OUTPUT_PATH = os.path.expanduser("~/Documents/old_main_export.json")

OLD_CHANNEL = -1002176961000
# Strip -100 prefix for internal link format
_INTERNAL = str(OLD_CHANNEL).replace("-100", "", 1)
INDEX_PREFIX = "https://t.me/ani_weebs_index/"


def _extract_buttons(msg) -> list[dict]:
    """Extract button info from a message."""
    kb = getattr(msg, "reply_markup", None)
    rows = getattr(kb, "inline_keyboard", None)
    if not rows:
        return []
    out = []
    for row in rows:
        for b in row:
            btn = {"text": b.text}
            url = getattr(b, "url", None)
            if url:
                btn["url"] = url
            out.append(btn)
    return out


def _get_photo_info(msg) -> dict | None:
    """Extract photo file_id and basic info."""
    if not msg.photo:
        return None
    return {
        "file_id": msg.photo.file_id,
        "file_unique_id": msg.photo.file_unique_id,
        "width": msg.photo.width,
        "height": msg.photo.height,
        "file_size": msg.photo.file_size,
    }


async def extract_all():
    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    all_entries = []
    stats = {"photo_posts": 0, "text_posts": 0, "other": 0, "empty": 0}

    try:
        client = await pool.acquire()
        print(f"connected to {OLD_CHANNEL}")

        # Iterate ALL messages
        total = 0
        async for msg in client.get_chat_history(OLD_CHANNEL, limit=0):
            total = total or 1  # just iterate to count
            _ = msg

        print(f"total_messages: {total}")

        # Now iterate properly and extract
        count = 0
        async for msg in client.get_chat_history(OLD_CHANNEL):
            body = (msg.text or msg.caption or "").strip()
            btns = _extract_buttons(msg)
            kind = "unknown"
            if msg.photo:
                kind = "photo"
            elif msg.text:
                kind = "text"
            elif msg.sticker:
                kind = "sticker"
            elif msg.video:
                kind = "video"
            elif msg.document:
                kind = "document"

            stats[kind] = stats.get(kind, 0) + 1

            if kind == "photo" and btns:
                # This is an anime post
                photo_info = _get_photo_info(msg)
                entry = {
                    "id": msg.id,
                    "date": str(msg.date),
                    "kind": "anime_post",
                    "caption": body,
                    "photo": photo_info,
                    "buttons": btns,
                    "old_channel_id": OLD_CHANNEL,
                    "old_link": f"https://t.me/c/{_INTERNAL}/{msg.id}",
                }
                all_entries.append(entry)
                count += 1
                if count % 10 == 0:
                    print(f"  extracted {count}...")

        print(f"\nextraction complete: {count} anime posts")
        print(f"stats: {json.dumps(stats, indent=2)}")

        # Save to output file
        output = {
            "source_channel": OLD_CHANNEL,
            "source_channel_internal": _INTERNAL,
            "total_messages": total,
            "entries_extracted": count,
            "entries": all_entries,
        }

        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\nsaved to {OUTPUT_PATH}")

    except Exception as exc:
        print(f"error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(extract_all())
