"""
Phase 1: Discovery — find ALL channels containing the ANIME WEEBS footer text.

1. Get all userbot dialogs
2. For each channel/supergroup, search for messages with the footer
3. Check admin access
4. Output a report of findings
"""

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, "C:/Users/Admin/Documents/NekoFetch")
os.chdir("C:/Users/Admin/Documents/NekoFetch")

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.enums import ChatType, ChatMemberStatus
from pyrogram.parser.html import HTML

FOOTER_SIGNATURE = "ANIME WEEBS"
OUTPUT_FILE = os.path.expanduser("~/Documents/footer_discovery.json")

# We'll compare against the en.json footer template
with open("resources/language/en.json", encoding="utf-8") as f:
    EN_JSON = json.load(f)
TARGET_FOOTER = EN_JSON.get("bot_footer", "")


async def discover():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()
    me = await client.get_me()
    
    print(f"Userbot: @{me.username} (ID: {me.id})")
    print(f"Target footer (from en.json): {TARGET_FOOTER[:80]}...")
    print()
    
    # Get all dialogs
    dialogs = []
    async for d in client.get_dialogs():
        dialogs.append(d)
    
    print(f"Total dialogs: {len(dialogs)}")
    
    # Filter to channels and supergroups
    channels = [d for d in dialogs if d.chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP)]
    print(f"Channels/supergroups: {len(channels)}")
    
    results = []
    checked = 0
    
    for d in channels:
        chat = d.chat
        checked += 1
        
        # Quick skip: check if the chat title or username suggests it might have footer
        # Actually, we need to check messages for the footer signature
        
        try:
            # Search recent messages for footer text
            found_msgs = []
            async for msg in client.get_chat_history(chat.id, limit=30):
                cap = msg.caption or msg.text or ""
                if not cap:
                    continue
                if FOOTER_SIGNATURE in cap.upper():
                    found_msgs.append({
                        "msg_id": msg.id,
                        "has_caption": bool(msg.caption),
                        "is_pinned": getattr(msg, "is_pinned", False),
                    })
            
            if found_msgs:
                # Check admin access
                is_admin = False
                admin_status = "unknown"
                try:
                    member = await chat.get_member(me.id)
                    is_admin = member.status in (
                        ChatMemberStatus.OWNER,
                        ChatMemberStatus.ADMINISTRATOR,
                    )
                    admin_status = str(member.status).split(".")[-1]
                except Exception:
                    admin_status = "error checking"
                
                # Extract the footer text from the first found message
                footer_text = ""
                footer_html = ""
                for msg_info in found_msgs:
                    msg = await client.get_messages(chat.id, msg_info["msg_id"])
                    cap = msg.caption or msg.text or ""
                    ents = msg.caption_entities or msg.entities or []
                    
                    # Find just the footer portion
                    # The footer contains "ANIME WEEBS" — find it and extract from there
                    footer_start = cap.upper().find(FOOTER_SIGNATURE)
                    if footer_start >= 0:
                        footer_text = cap[footer_start:].strip()
                        # Get HTML for just the footer portion
                        # We need to find entities that overlap with the footer portion
                        footer_entities = [
                            e for e in ents
                            if e.offset >= footer_start
                            or (e.offset + e.length) > footer_start
                        ]
                        # Adjust offsets relative to footer start
                        adjusted = []
                        for e in footer_entities:
                            new_e = type(e)(
                                offset=max(0, e.offset - footer_start),
                                length=min(e.length, len(footer_text) - max(0, e.offset - footer_start)),
                            )
                            # Copy extra fields
                            if hasattr(e, 'url'):
                                new_e.url = e.url
                            if hasattr(e, 'language'):
                                new_e.language = e.language
                            adjusted.append(new_e)
                        
                        html_parser = HTML(client)
                        try:
                            footer_html = html_parser.unparse(footer_text, adjusted)
                        except Exception:
                            footer_html = footer_text
                        break
                
                channel_info = {
                    "id": chat.id,
                    "title": chat.title or "",
                    "username": chat.username or "",
                    "type": str(chat.type).split(".")[-1],
                    "is_admin": is_admin,
                    "admin_status": admin_status,
                    "footer_messages": found_msgs,
                    "footer_text": footer_text[:500],
                    "footer_html": footer_html[:500],
                }
                results.append(channel_info)
                
                print(f"  ✅ @{chat.username or chat.title}: {len(found_msgs)} footer msgs, admin={is_admin}")
            else:
                pass  # no footer found
                
        except Exception as e:
            # Skip inaccessible channels (banned, deleted, flood wait)
            error_str = str(e)[:80]
            if "FLOOD" in error_str.upper():
                print(f"  ⏳ @{chat.username or chat.title}: FLOOD WAIT — skipping")
            elif "BANNED" in error_str.upper() or "KICKED" in error_str.upper():
                pass  # silently skip banned
            else:
                print(f"  ⚠️  @{chat.username or chat.title}: {error_str}")
    
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"  Channels checked: {checked}")
    print(f"  Channels with footer: {len(results)}")
    print(f"  Admin access: {sum(1 for r in results if r['is_admin'])}")
    print(f"  Non-admin: {sum(1 for r in results if not r['is_admin'])}")
    
    # Save results
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    return results


if __name__ == "__main__":
    asyncio.run(discover())
