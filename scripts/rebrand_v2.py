"""REBRAND v2 — CORRECT approach.

Only wraps @mentions in HTML <a> links while keeping ALL existing text,
small caps unicode, formatting, and structure exactly as-is.

The display text shows the NEW brand name BUT with the same small-caps
styling pattern as the original.
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

from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import ChatType, ParseMode

from nekofetch.core.config import get_env
from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

RESULT_PATH = os.path.expanduser("~/Documents/rebrand_v2_results.json")

# ============================================================
# BRAND MAPPINGS: old username → new username + display pattern
# ============================================================
BRAND_MAP = {
    "ani_weebs":     ("AniXWeebs",     "AniXWeebs"),
    "weebs_server":  ("WeebsXServer",   "WeebsXServer"),
    "ongoing_ani_weebs": ("Ongoing_AniXWeebs", "Ongoing_AniXWeebs"),
    "animovie_weebs": ("AniMovieXWeebs", "AniMovieXWeebs"),
    "weebs_gc":      ("Weebs_GC",       "Weebs_GC"),
}

# Build regex to match @MENTIONS (with small caps unicode)
# The old usernames contained: Ani_Weebs, Weebs_Server, Ongoing_Ani_Weebs,
# AniMovie_Weebs, Weebs_GC
# Each can have regular OR small caps unicode characters

# Small caps → regular mapping for detection
_TO_REGULAR = {
    '\u1d00': 'a', '\u0299': 'b', '\u1d04': 'c', '\u1d05': 'd',
    '\u1d07': 'e', '\ua730': 'f', '\u0262': 'g', '\u029c': 'h',
    '\u026a': 'i', '\u1d0a': 'j', '\u1d0b': 'k', '\u029f': 'l',
    '\u1d0d': 'm', '\u0274': 'n', '\u1d0f': 'o', '\u1d18': 'p',
    '\u01eb': 'q', '\u0280': 'r', '\ua731': 's', '\u1d1b': 't',
    '\u1d1c': 'u', '\u1d20': 'v', '\u1d21': 'w', '\u028f': 'y',
    '\u1d22': 'z',
}

# Regular → small caps for display text generation
_TO_SMALL = {v: k for k, v in _TO_REGULAR.items()}

# Additional small caps chars used in the display (capital letters that aren't in the map)
_TO_SMALL['x'] = '×'  # special case

def normalize(text: str) -> str:
    """Convert small caps unicode to regular chars for detection."""
    for sc, reg in _TO_REGULAR.items():
        text = text.replace(sc, reg)
    return text


def detect_old_username(text: str) -> str | None:
    """Extract old username from @mention text (e.g. @Aɴɪ_Wᴇᴇʙs → ani_weebs)."""
    n = normalize(text).lower().lstrip('@')
    for key in BRAND_MAP:
        if key in n:
            return key
    return None


def gen_display_text(old_text: str, new_username: str) -> str:
    """Generate display text with new brand but keeping the same small-caps STYLE.
    
    The original pattern was: first letter of each word is regular uppercase,
    rest of letters are small caps. We mimic this for the new text.
    """
    # If the old text was regular (no small caps), just use @new_username
    has_sc = any(c in _TO_REGULAR for c in old_text)
    if not has_sc:
        return f"@{new_username}"
    
    # Apply the small-caps pattern: 1st letter regular, rest small-caps
    result_parts = []
    for part in new_username.split('_'):
        if not part:
            continue
        styled = part[0].upper()  # First letter: regular uppercase
        for c in part[1:].lower():
            styled += _TO_SMALL.get(c, c)
        result_parts.append(styled)
    
    return '@' + '_'.join(result_parts)


def replace_mentions(text: str) -> str:
    """Find all @old_username mentions and replace with HTML links.
    
    ONLY the @mention part is replaced. Everything else stays exactly as-is.
    """
    if not text:
        return text
    
    # Regex to find @ mentions (word characters, underscores, and small caps)
    # We match @ followed by alphanumeric + underscore + small caps chars
    mention_re = re.compile(
        r'@[\w' + ''.join(_TO_REGULAR.keys()) + '_]+'
    )
    
    result = text
    matches = list(mention_re.finditer(text))
    
    # Process in reverse order so positions don't shift
    for m in reversed(matches):
        mention = m.group(0)
        old_brand = detect_old_username(mention)
        
        if old_brand and old_brand in BRAND_MAP:
            new_user, new_display_base = BRAND_MAP[old_brand]
            display_text = gen_display_text(mention, new_user)
            link = f'<a href="https://t.me/{new_user}">{display_text}</a>'
            
            start, end = m.start(), m.end()
            result = result[:start] + link + result[end:]
    
    return result


def has_old_footer(text: str) -> bool:
    """Check if text has any old @username pattern."""
    if not text:
        return False
    n = normalize(text).lower()
    for key in BRAND_MAP:
        if f"@{key}" in n:
            return True
    if 'feel the story' in n and 'anime weebs' in n:
        return True
    if 'powered by' in n and '@' in text:
        return True
    if 'brought to you by' in n and '@' in text:
        return True
    return False


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
        "channels_scanned": 0,
        "total_messages_checked": 0,
        "messages_edited": 0,
        "channels": {},
        "errors": [],
    }

    print("Getting all channel dialogs...")
    dialogs = []
    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.type in (ChatType.CHANNEL,):
                dialogs.append(dialog)
    except Exception as e:
        print(f"Error getting dialogs: {e}")

    print(f"Total channel dialogs: {len(dialogs)}")
    print()

    for ci, dialog in enumerate(dialogs):
        chat = dialog.chat
        cid = chat.id
        title = chat.title or ""
        username = chat.username or ""

        print(f"[{ci+1}/{len(dialogs)}] @{username} / {title[:40]}...", end=" ", flush=True)

        chan_result = {
            "title": title,
            "username": username,
            "checked": 0,
            "edited": 0,
            "ids": [],
        }

        try:
            msg_count = 0
            edit_count = 0
            async for msg in client.get_chat_history(cid, limit=200):
                text = msg.text or msg.caption or ""
                if not text:
                    continue
                msg_count += 1

                if has_old_footer(text):
                    new_text = replace_mentions(text)
                    if new_text != text:
                        try:
                            await client.edit_message_text(
                                cid, msg.id, new_text,
                                parse_mode=ParseMode.HTML,
                            )
                            edit_count += 1
                            chan_result["ids"].append(msg.id)
                            print("✏️", end="", flush=True)
                            await asyncio.sleep(3.5)
                        except FloodWait as fw:
                            wait = fw.value + 2
                            print(f"⏳({wait}s)", end="", flush=True)
                            await asyncio.sleep(wait)
                        except RPCError as e:
                            err = str(e)
                            if "MESSAGE_NOT_MODIFIED" in err:
                                pass
                            elif "CHAT_ADMIN_REQUIRED" in err:
                                print("🔒", end="", flush=True)
                                break
                            elif "MESSAGE_ID_INVALID" in err:
                                pass
                            else:
                                print(f"❌({err[:40]})", end="", flush=True)
                                await asyncio.sleep(3)

            chan_result["checked"] = msg_count
            chan_result["edited"] = edit_count
            print(f" {edit_count} edited / {msg_count} checked")

        except Exception as e:
            err = str(e)[:100]
            chan_result["error"] = err
            print(f"⚠️ {err}")

        results["channels"][str(cid)] = chan_result
        results["total_messages_checked"] += chan_result["checked"]
        results["messages_edited"] += chan_result["edited"]
        results["channels_scanned"] += 1

        await asyncio.sleep(2)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"  Channels: {results['channels_scanned']}")
    print(f"  Checked:  {results['total_messages_checked']}")
    print(f"  Edited:   {results['messages_edited']}")

    await pool.close()
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
