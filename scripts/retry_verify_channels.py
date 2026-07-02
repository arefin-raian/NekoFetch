"""Retry flood-wait blocked channels from the previous verification.

Reads the existing verification results, finds all channels with "error" status
(flood-wait), and retries them with proper delays.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/retry_verify_channels.py
"""

import asyncio
import json
import logging
import os
import re
import sys
import time

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

EXPORT_PATH = os.path.expanduser("~/Documents/old_main_export.json")
VERIFY_PATH = os.path.expanduser("~/Documents/channel_verification.json")
RESULT_PATH = os.path.expanduser("~/Documents/channel_verification_v2.json")


def extract_channel_ref(url: str) -> str | None:
    m = re.match(r"https?://t\.me/(.+)", url)
    if not m:
        return None
    path = m.group(1).split("/")
    if not path:
        return None
    first = path[0]
    if first in ("ani_weebs_index",):
        return None
    return first


async def main():
    # Load existing verification results
    with open(VERIFY_PATH, encoding="utf-8") as f:
        existing = json.load(f)

    # Find all error/flood-wait channels
    error_refs = []
    for ref, info in existing.get("results", {}).items():
        if info.get("status") in ("error",):
            error_refs.append(ref)

    print(f"Channels to retry: {len(error_refs)}")
    for r in error_refs:
        print(f"  {r}")

    if not error_refs:
        print("Nothing to retry!")
        return

    # Connect userbot
    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    retry_results: dict[str, dict] = {}
    base_delay = 5  # Start with 5s between checks

    try:
        client = await pool.acquire()
        print(f"\nRetrying {len(error_refs)} flood-wait channels...")

        for i, ref in enumerate(error_refs):
            delay = base_delay + (i * 2)  # gradually increase delay
            if delay > 30:
                delay = 30  # cap at 30s

            print(f"  [{i+1}/{len(error_refs)}] {ref} (waiting {delay}s)...", end=" ", flush=True)
            await asyncio.sleep(delay)

            try:
                chat = await client.get_chat(ref)
                retry_results[ref] = {
                    "status": "active",
                    "title": getattr(chat, "title", None),
                    "type": str(getattr(chat, "type", "")),
                    "members": getattr(chat, "members_count", None),
                    "username": getattr(chat, "username", None),
                }
                print(f"ACTIVE: {getattr(chat, 'title', '?')}")
            except Exception as exc:
                err = str(exc)
                if "FLOOD_WAIT" in err:
                    # Parse the wait time
                    import re as re2
                    m = re2.search(r"FLOOD_WAIT_(\d+)", err)
                    wait = int(m.group(1)) if m else 60
                    print(f"FLOOD_WAIT ({wait}s) — skipping, will retry later")
                    retry_results[ref] = {"status": "flood_wait", "error": err, "wait_seconds": wait}
                    # Actually wait the full flood-wait time
                    print(f"     waiting {wait}s...")
                    await asyncio.sleep(wait + 2)
                elif "USERNAME_NOT_OCCUPIED" in err or "USERNAME_INVALID" in err:
                    retry_results[ref] = {"status": "banned_deleted", "error": err}
                    print("BANNED/DELETED")
                elif "CHANNEL_PRIVATE" in err or "CHAT_NOT_FOUND" in err:
                    retry_results[ref] = {"status": "private_unreachable", "error": err}
                    print("PRIVATE/UNREACHABLE")
                else:
                    retry_results[ref] = {"status": "error", "error": err}
                    print(f"ERROR: {err[:80]}")

        # Merge with existing results
        all_results = dict(existing.get("results", {}))
        for ref, info in retry_results.items():
            if info["status"] != "flood_wait":  # Only update if we got a definitive result
                all_results[ref] = info
            else:
                all_results[ref] = info  # Keep the flood_wait status

        # Count final statuses
        counts = {}
        for info in all_results.values():
            s = info.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        output = {
            "total_refs_checked": len(all_results),
            "summary": counts,
            "results": all_results,
        }

        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n\n=== FINAL RESULTS ===")
        for k, v in sorted(counts.items()):
            print(f"  {k}: {v}")
        print(f"\nSaved to: {RESULT_PATH}")

    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
