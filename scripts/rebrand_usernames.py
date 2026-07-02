"""Replace all @Ani_Weebs → @AniXWeebs with HTML links across all channels.

ONLY changes the @usernames — wraps them in <a href> links and updates
the brand name. EVERYTHING ELSE stays exactly as-is.

Old → New mappings:
  @Ani_Weebs    → <a href="https://t.me/AniXWeebs">@AniXWeebs</a>
  @Weebs_Server → <a href="https://t.me/WeebsXServer">@WeebsXServer</a>
  @Ongoing_Ani_Weebs → <a href="https://t.me/Ongoing_AniXWeebs">@Ongoing_AniXWeebs</a>
  @AniMovie_Weebs    → <a href="https://t.me/AniMovieXWeebs">@AniMovieXWeebs</a>
  @Weebs_GC    → <a href="https://t.me/Weebs_GC">@Weebs_GC</a>
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import ChatType, ParseMode

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

RESULT_PATH = os.path.expanduser("~/Documents/rebrand_results.json")

# @username replacements: old_username → (new_username, new_url_path)
REPLACEMENTS = [
    ("Ani_Weebs", "AniXWeebs"),
    ("Weebs_Server", "WeebsXServer"),
    ("Ongoing_Ani_Weebs", "Ongoing_AniXWeebs"),
    ("AniMovie_Weebs", "AniMovieXWeebs"),
    ("Weebs_GC", "Weebs_GC"),  # GC stays same but gets HTML link
]

# Build replacement patterns for both regular text and small-caps unicode
# Small caps → regular mapping for the old username part
SC = {
    '\u1d00': 'a',  # ᴀ
    '\u0299': 'b',  # ʙ
    '\u1d04': 'c',  # ᴄ
    '\u1d05': 'd',  # ᴅ
    '\u1d07': 'e',  # ᴇ
    '\ua730': 'f',  # ꜰ
    '\u0262': 'g',  # ɢ
    '\u029c': 'h',  # ʜ
    '\u026a': 'i',  # ɪ
    '\u1d0a': 'j',  # ᴊ
    '\u1d0b': 'k',  # ᴋ
    '\u029f': 'l',  # ʟ
    '\u1d0d': 'm',  # ᴍ
    '\u0274': 'n',  # ɴ
    '\u1d0f': 'o',  # ᴏ
    '\u1d18': 'p',  # ᴘ
    '\u01eb': 'q',  # ǫ
    '\u0280': 'r',  # ʀ
    '\ua731': 's',  # ꜱ
    '\u1d1b': 't',  # ᴛ
    '\u1d1c': 'u',  # ᴜ
    '\u1d20': 'v',  # ᴠ
    '\u1d21': 'w',  # ᴡ
    '\u028f': 'y',  # ʏ
    '\u1d22': 'z',  # ᴢ
}

def normalize_sc(text: str) -> str:
    """Convert small caps to regular ascii for pattern matching."""
    for sc_char, reg in SC.items():
        text = text.replace(sc_char, reg)
    return text

def build_regex(old_username: str) -> re.Pattern:
    """Build regex matching @old_username with any mix of regular/small-caps letters."""
    pattern = '@'
    for c in old_username:
        if c == '_':
            pattern += '_'
        elif c.isalpha():
            cl = c.lower()
            sc_chars = [k for k, v in SC.items() if v == cl]
            group = c + cl.upper() + ''.join(sc_chars)
            pattern += f'[{group}]'
        else:
            pattern += re.escape(c)
    return re.compile(pattern, re.IGNORECASE)

# Pre-compile all regex patterns
PATTERNS = []
for old_uname, new_uname in REPLACEMENTS:
    pattern = build_regex(old_uname)
    url_path = new_uname
    replacement = f'<a href="https://t.me/{url_path}">@{new_uname}</a>'
    PATTERNS.append((pattern, replacement, old_uname, new_uname))

def replace_usernames(text: str) -> tuple[str, bool]:
    """Replace @old_usernames with HTML links. Returns (new_text, changed)."""
    if not text:
        return text, False

    changed = False
    for pattern, replacement, old_uname, new_uname in PATTERNS:
        if pattern.search(text):
            text = pattern.sub(replacement, text)
            changed = True
    return text, changed

async def main():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    results = {
        "timestamp": datetime.now().isoformat(),
        "total_edited": 0,
        "channels": {},
    }

    # 1. Get all dialogs
    print("Getting dialogs...")
    dialogs = []
    async for dialog in client.get_dialogs():
        if dialog.chat.type in (ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP):
            dialogs.append(dialog)
    print(f"Found {len(dialogs)} channel/group dialogs\n")

    chat_infos = []
    for d in dialogs:
        chat = d.chat
        chat_infos.append({
            "id": chat.id,
            "title": chat.title or "",
            "username": chat.username or "",
        })

    for ci, info in enumerate(chat_infos):
        cid = info["id"]
        title = info["title"]
        username = info["username"]

        print(f"[{ci+1}/{len(chat_infos)}] {title} (@{username})...", end=" ", flush=True)

        ch_result = {"edited": 0, "ids": []}
        try:
            async for msg in client.get_chat_history(cid, limit=200):
                text = msg.text or msg.caption or ""
                if not text:
                    continue

                new_text, changed = replace_usernames(text)
                if changed and new_text != text:
                    try:
                        await client.edit_message_text(
                            cid, msg.id, new_text,
                            parse_mode=ParseMode.HTML,
                        )
                        ch_result["edited"] += 1
                        ch_result["ids"].append(msg.id)
                        print("✏️", end="", flush=True)
                        await asyncio.sleep(2.5)
                    except FloodWait as fw:
                        wait = fw.value + 1
                        print(f"⏳", end="", flush=True)
                        await asyncio.sleep(wait)
                    except RPCError as e:
                        if "CHAT_ADMIN_REQUIRED" in str(e):
                            print(f"🔒", end="", flush=True)
                            break
                        elif "MESSAGE_NOT_MODIFIED" not in str(e):
                            print(f"❌", end="", flush=True)
                            await asyncio.sleep(2)

        except Exception as e:
            print(f"⚠️", end="", flush=True)

        print(f" {ch_result['edited']} edited")
        results["channels"][str(cid)] = ch_result
        results["total_edited"] += ch_result["edited"]
        await asyncio.sleep(1.5)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nDone! Edited {results['total_edited']} messages across {len(results['channels'])} channels")
    print(f"Saved to: {RESULT_PATH}")

    await pool.close()
    await container.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
