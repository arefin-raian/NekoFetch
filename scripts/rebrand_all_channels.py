"""Rebrand ALL download channels — replace old footer with new HTML-linked branding.

This script:
1. Gets all channels the userbot is a member of
2. Iterates through messages in each channel looking for old footer patterns
3. Replaces them with new branded HTML links (Ani_Weebs → AniXWeebs etc.)
4. Edits each message with parse_mode=HTML so @usernames become clickable

Uses 3-4s delays between edits to avoid flood-wait limits.
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

from pyrogram import Client, enums
from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import ChatType, ParseMode

from nekofetch.core.config import get_env
from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

RESULT_PATH = os.path.expanduser("~/Documents/rebrand_results.json")

# ============================================================
# NEW FOOTER TEXT (HTML with clickable @links)
# ============================================================
NEW_FOOTER = (
    "ANIME WEEBS - ꜰᴇᴇʟ ᴛʜᴇ ꜱᴛᴏʀʏ, ʟɪᴠᴇ ᴛʜᴇ ᴀʀᴛ\n"
    "────────────────────────\n"
    '⬥ Aɴɪᴍᴇ: <a href="https://t.me/AniXWeebs">@AniXWeebs</a>\n'
    '⬥ Nᴇᴛᴡᴏʀᴋ: <a href="https://t.me/WeebsXServer">@WeebsXServer</a>\n'
    '⬥ Oɴɢᴏɪɴɢ: <a href="https://t.me/Ongoing_AniXWeebs">@Ongoing_AniXWeebs</a>\n'
    '⬥ Aɴɪᴍᴇ Mᴏᴠɪᴇs: <a href="https://t.me/AniMovieXWeebs">@AniMovieXWeebs</a>\n'
    "────────────────────────\n"
    'Vɪsɪᴛ <a href="https://t.me/Weebs_GC">@Weebs_GC</a> ғᴏʀ ᴍᴏʀᴇ ɪɴғᴏ'
)

NEW_POWERED_BY = '‣ Powered By ~ <a href="https://t.me/AniXWeebs">@AniXWeebs</a>'
NEW_BROUGHT_BY = 'Brought to you by ~ <a href="https://t.me/AniXWeebs">@AniXWeebs</a>'

# ============================================================
# SMALL CAPS UNICODE NORMALIZATION
# ============================================================
# Map small caps unicode -> regular character for matching
_SMALL_CAPS = {
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

def normalize(text: str) -> str:
    """Convert small caps unicode to regular characters for easier matching."""
    for sc_char, regular in _SMALL_CAPS.items():
        text = text.replace(sc_char, regular)
    return text


def has_old_footer(text: str) -> bool:
    """Check if a message contains old footer patterns."""
    if not text:
        return False
    # Normalize small caps for reliable matching
    n = normalize(text)
    
    # Check for full footer by structural indicators
    if 'ANIME WEEBS' in text.upper() and ('feel the story' in n.lower() or 'feel' in n.lower()):
        return True
    
    # Check for any @Ani_Weebs mentions (regular or small caps)
    # The old usernames always contained one of these patterns
    old_usernames = ['ani_weebs', 'weebs_server', 'ongoing_ani_weebs', 'animovie_weebs', 'weebs_gc']
    for uname in old_usernames:
        if '@' + uname in n.lower():
            return True
    
    # Check for Powered By or Brought to you by lines
    if 'powered by' in n.lower() and '@' in text:
        return True
    if 'brought to you by' in n.lower() and '@' in text:
        return True
    
    return False


def build_new_text(old_text: str) -> str:
    """Build the new HTML text from old text, replacing footers with new branding."""
    if not old_text:
        return old_text

    text = old_text
    n_text = normalize(text)  # normalized version for pattern matching
    
    # 1. Check if this message IS (or contains) the full footer
    if 'ANIME WEEBS' in text.upper() and 'feel the story' in n_text.lower():
        lines = text.split('\n')
        footer_start = -1
        for i, line in enumerate(lines):
            nl = normalize(line).lower()
            if 'anime weebs' in nl and 'feel' in nl:
                footer_start = i
                break

        if footer_start >= 0:
            before = '\n'.join(lines[:footer_start]).rstrip()
            if before:
                text = before + '\n\n' + NEW_FOOTER
            else:
                text = NEW_FOOTER
            return text

    # 2. Replace specific lines
    lines = text.split('\n')
    new_lines = []
    changed = False
    
    for line in lines:
        nl = normalize(line).lower().strip()
        
        # Check: Powered By line
        if 'powered by' in nl and '@' in nl:
            new_lines.append(NEW_POWERED_BY)
            changed = True
        # Check: Brought to you by line
        elif 'brought to you by' in nl and '@' in nl:
            new_lines.append(NEW_BROUGHT_BY)
            changed = True
        # Check: standalone @Ani_Weebs line
        elif re.match(r'^@(?:' + '|'.join(['ani_weebs', 'aɴɪ_wᴇᴇʙs']) + r')$', line.strip(), re.IGNORECASE):
            new_lines.append('<a href="https://t.me/AniXWeebs">@AniXWeebs</a>')
            changed = True
        else:
            new_lines.append(line)

    if changed:
        text = '\n'.join(new_lines)

    return text


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

    # 1. Get all dialogs (channels the userbot is in)
    print("Getting all channel dialogs...")
    dialogs = []
    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.type in (ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP):
                dialogs.append(dialog)
    except Exception as e:
        print(f"Error getting dialogs: {e}")

    print(f"Total channel/group dialogs: {len(dialogs)}")
    print()

    # Filter to likely download channels (have anime-related names)
    # But first, get ALL channels and scan them all
    scan_chats = []
    for d in dialogs:
        chat = d.chat
        title = chat.title or ""
        username = chat.username or ""
        scan_chats.append({
            "id": chat.id,
            "title": title,
            "username": username,
            "type": str(chat.type).split(".")[-1],
        })

    print(f"Scanning {len(scan_chats)} channels for old footer messages...\n")

    for ci, chat_info in enumerate(scan_chats):
        cid = chat_info["id"]
        title = chat_info["title"]
        username = chat_info["username"]

        print(f"[{ci+1}/{len(scan_chats)}] Checking {title} (@{username})...", end=" ", flush=True)

        channel_result = {
            "title": title,
            "username": username,
            "messages_checked": 0,
            "messages_edited": 0,
            "edited_ids": [],
        }

        try:
            # Iterate through messages (last 200 messages to be efficient)
            msg_count = 0
            edit_count = 0
            async for msg in client.get_chat_history(cid, limit=200):
                text = msg.text or msg.caption or ""
                if not text:
                    continue

                msg_count += 1

                if has_old_footer(text):
                    new_text = build_new_text(text)
                    if new_text != text:
                        try:
                            await client.edit_message_text(
                                cid, msg.id, new_text,
                                parse_mode=ParseMode.HTML,
                            )
                            edit_count += 1
                            channel_result["edited_ids"].append(msg.id)
                            print(f"✏️", end="", flush=True)
                            await asyncio.sleep(3)  # delay to avoid flood
                        except FloodWait as fw:
                            wait = fw.value + 2
                            print(f"⏳({wait}s)", end="", flush=True)
                            await asyncio.sleep(wait)
                        except RPCError as e:
                            if "MESSAGE_NOT_MODIFIED" in str(e):
                                pass  # Already updated, skip
                            elif "CHAT_ADMIN_REQUIRED" in str(e):
                                print(f"🔒", end="", flush=True)
                                break  # Can't edit in this channel
                            else:
                                print(f"❌({str(e)[:40]})", end="", flush=True)
                                await asyncio.sleep(3)

            channel_result["messages_checked"] = msg_count
            channel_result["messages_edited"] = edit_count
            print(f" {edit_count} edited / {msg_count} checked")

        except Exception as e:
            err = str(e)[:100]
            channel_result["error"] = err
            print(f"⚠️ ERROR: {err}")

        results["channels"][str(cid)] = channel_result
        results["total_messages_checked"] += channel_result["messages_checked"]
        results["messages_edited"] += channel_result["messages_edited"]
        results["channels_scanned"] += 1

        # Small delay between channels
        await asyncio.sleep(2)

    # Save results
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"  REBRAND COMPLETE")
    print(f"{'='*50}")
    print(f"  Channels scanned:   {results['channels_scanned']}")
    print(f"  Messages checked:   {results['total_messages_checked']}")
    print(f"  Messages edited:    {results['messages_edited']}")
    print(f"\n  Saved to: {RESULT_PATH}")

    await pool.close()
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
