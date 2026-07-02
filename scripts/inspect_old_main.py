"""Inspect the old main channel via userbot to analyze post structure.

Old Main Channel: -1002176961000
Entry point: message 285

Usage:
    PYTHONIOENCODING=utf-8 python scripts/inspect_old_main.py
"""

import asyncio
import json
import logging
import os
import sys

# Suppress all logging to avoid encoding issues
logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

from pyrogram.enums import ParseMode

# Late imports after log suppression
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nekofetch.core.container import Container
from nekofetch.core.config import get_env, get_app_config
from nekofetch.sources.telegram.userbot import UserbotPool


def _btn_debug(msg) -> list[dict]:
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


def _kind(msg) -> str:
    for k in ("photo", "video", "document", "sticker", "animation", "audio"):
        if getattr(msg, k, None):
            return k
    return "text"


async def main():
    container = Container.create()
    await container.startup()

    OLD_CHANNEL = -1002176961000
    ENTRY_POINT = 285

    # Build userbot pool manually to avoid logging issues
    import os
    from dotenv import load_dotenv
    load_dotenv()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    try:
        client = await pool.acquire()
        print("connected")

        # 1. Channel info
        try:
            chat = await client.get_chat(OLD_CHANNEL)
            print(f"channel: {chat.title!r} type={chat.type}")
        except Exception as exc:
            print(f"err_open: {exc}")
            return

        # 2. Entry point msg 285
        print(f"\n--- msg {ENTRY_POINT} ---")
        try:
            msg = await client.get_messages(OLD_CHANNEL, ENTRY_POINT)
            if msg:
                body = (msg.text or msg.caption or "")[:500]
                print(f"kind={_kind(msg)}")
                print(f"body={body!r}")
                for b in _btn_debug(msg):
                    print(f"  btn: [{b['text']}] -> {b.get('url', 'none')}")
        except Exception as exc:
            print(f"err_msg285: {exc}")

        # 3. Sample 30 recent anime posts
        print(f"\n--- recent posts ---")
        count = 0
        async for msg in client.get_chat_history(OLD_CHANNEL, limit=100):
            body = (msg.text or msg.caption or "")
            btns = _btn_debug(msg)
            kind = _kind(msg)
            if kind == "photo" or (kind == "text" and len(body) > 50):
                print(f"\nmsg {msg.id} [{kind}]")
                print(f"  {body[:300]!r}")
                for b in btns:
                    print(f"  [{b['text']}] -> {b.get('url', 'no-url')}")
                count += 1
                if count >= 20:
                    break

        # 4. Messages around entry point (285-300)
        print(f"\n--- msgs 285-300 ---")
        for mid in range(ENTRY_POINT, ENTRY_POINT + 15):
            try:
                msg = await client.get_messages(OLD_CHANNEL, mid)
                if msg:
                    body = (msg.text or msg.caption or "")[:200]
                    kind = _kind(msg)
                    btns = _btn_debug(msg)
                    print(f"msg {mid} [{kind}]: {body!r}")
                    for b in btns:
                        print(f"  [{b['text']}] -> {b.get('url', 'none')}")
            except Exception:
                pass

    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
