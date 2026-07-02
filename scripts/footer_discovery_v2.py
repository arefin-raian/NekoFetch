"""
Phase 1: Discovery — find ALL channels containing the ANIME WEEBS footer.
Optimized: parallel channel scanning.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, "C:/Users/Admin/Documents/NekoFetch")
os.chdir("C:/Users/Admin/Documents/NekoFetch")

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.enums import ChatType, ChatMemberStatus

FOOTER_SIGNATURE = "ANIME WEEBS"
OUTPUT_FILE = os.path.expanduser("~/Documents/footer_discovery.json")
BATCH_SIZE = 10


async def check_channel(client, me_id, chat):
    """Check one channel for footer text. Returns dict or None."""
    try:
        # Quick scan: check first few messages
        found = []
        async for msg in client.get_chat_history(chat.id, limit=10):
            cap = msg.caption or msg.text or ""
            if FOOTER_SIGNATURE in cap.upper():
                found.append(msg.id)
                break  # one is enough
        
        if not found:
            return None
        
        # Check admin status
        is_admin = False
        try:
            member = await chat.get_member(me_id)
            is_admin = member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
        except Exception:
            pass
        
        return {
            "id": chat.id,
            "title": chat.title or "",
            "username": chat.username or "",
            "is_admin": is_admin,
            "footer_msg_ids": found,
        }
    except Exception:
        return None


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
    
    print(f"Userbot: @{me.username}")
    
    # Step 1: Get all dialogs (fast, one call)
    dialogs = []
    async for d in client.get_dialogs():
        dialogs.append(d)
    
    channels = [d.chat for d in dialogs 
                if d.chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP)]
    
    print(f"Total dialogs: {len(dialogs)}, channels: {len(channels)}")
    
    # Step 2: Scan channels in parallel batches
    results = []
    total = len(channels)
    
    for batch_start in range(0, total, BATCH_SIZE):
        batch = channels[batch_start:batch_start + BATCH_SIZE]
        tasks = [check_channel(client, me.id, chat) for chat in batch]
        batch_results = await asyncio.gather(*tasks)
        
        for r in batch_results:
            if r:
                results.append(r)
                admin_str = "ADMIN" if r["is_admin"] else "member"
                print(f"  ✅ @{r['username'] or r['title'][:30]}: {admin_str}")
        
        # Brief pause between batches to avoid flood
        if batch_start + BATCH_SIZE < total:
            await asyncio.sleep(1)
    
    print(f"\n{'='*60}")
    print(f"  Channels scanned: {total}")
    print(f"  With footer:      {len(results)}")
    print(f"  Admin access:     {sum(1 for r in results if r['is_admin'])}")
    print(f"  No admin:         {sum(1 for r in results if not r['is_admin'])}")
    
    # Save results
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  Saved to: {OUTPUT_FILE}")
    print(f"{'='*60}")
    
    return results


if __name__ == "__main__":
    asyncio.run(discover())
