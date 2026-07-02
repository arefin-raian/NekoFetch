"""Verify all download-channel links from the old main channel export.

Checks each unique t.me link to determine if the channel/chat is still
accessible (not banned, not deleted). Results saved alongside the export.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/verify_channels.py
"""

import asyncio
import json
import logging
import os
import re
import sys

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

EXPORT_PATH = os.path.expanduser("~/Documents/old_main_export.json")
RESULT_PATH = os.path.expanduser("~/Documents/channel_verification.json")


def extract_channel_ref(url: str) -> str | None:
    """Extract a channel/chat reference from a t.me URL."""
    # Handle https://t.me/username or t.me/username
    # Handle https://t.me/c/12345 or t.me/c/12345
    # Handle https://t.me/+invitehash
    m = re.match(r"https?://t\.me/(.+)", url)
    if not m:
        return None
    path = m.group(1).split("/")
    if not path:
        return None
    first = path[0]
    # Skip index links like "ani_weebs_index/310" — just verify the channel part
    if first in ("ani_weebs_index",):
        return None
    return first


async def main():
    # Load export
    with open(EXPORT_PATH, encoding="utf-8") as f:
        export = json.load(f)

    entries = export.get("entries", [])
    print(f"Loaded {len(entries)} entries from export")

    # Collect unique download URLs
    all_urls: set[str] = set()
    for e in entries:
        for b in e.get("buttons", []):
            url = b.get("url", "")
            if url and "t.me/" in url:
                all_urls.add(url)

    print(f"Total unique t.me URLs: {len(all_urls)}")

    # Extract channel references
    refs: dict[str, list[str]] = {}  # ref -> [urls]
    for url in sorted(all_urls):
        ref = extract_channel_ref(url)
        if ref:
            refs.setdefault(ref, []).append(url)

    print(f"Unique channel references to verify: {len(refs)}")
    for r in sorted(refs):
        print(f"  {r}")

    # Connect userbot and verify each reference
    container = Container.create()
    await container.startup()

    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )

    results: dict[str, dict] = {}

    try:
        client = await pool.acquire()
        print("\nVerifying channels...")

        for i, (ref, urls) in enumerate(sorted(refs.items())):
            print(f"  [{i+1}/{len(refs)}] {ref}...", end=" ", flush=True)
            try:
                chat = await client.get_chat(ref)
                results[ref] = {
                    "status": "active",
                    "title": getattr(chat, "title", None),
                    "type": str(getattr(chat, "type", "")),
                    "members": getattr(chat, "members_count", None),
                    "username": getattr(chat, "username", None),
                    "urls": urls,
                }
                print(f"ACTIVE: {getattr(chat, 'title', '?')}")
            except Exception as exc:
                err = str(exc)
                if "USERNAME_NOT_OCCUPIED" in err or "USERNAME_INVALID" in err:
                    results[ref] = {"status": "banned_deleted", "error": err, "urls": urls}
                    print("BANNED/DELETED")
                elif "CHANNEL_PRIVATE" in err or "CHAT_NOT_FOUND" in err:
                    results[ref] = {"status": "private_unreachable", "error": err, "urls": urls}
                    print("PRIVATE/UNREACHABLE")
                else:
                    results[ref] = {"status": "error", "error": err, "urls": urls}
                    print(f"ERROR: {err[:80]}")

            # Small delay to avoid flood-wait
            await asyncio.sleep(0.5)

        # Save results
        output = {
            "total_refs_checked": len(refs),
            "active": sum(1 for v in results.values() if v["status"] == "active"),
            "banned_deleted": sum(1 for v in results.values() if v["status"] == "banned_deleted"),
            "private_unreachable": sum(1 for v in results.values() if v["status"] == "private_unreachable"),
            "errors": sum(1 for v in results.values() if v["status"] == "error"),
            "results": results,
        }

        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n\nVerification complete:")
        print(f"  Active: {output['active']}")
        print(f"  Banned/Deleted: {output['banned_deleted']}")
        print(f"  Private/Unreachable: {output['private_unreachable']}")
        print(f"  Errors: {output['errors']}")
        print(f"Saved to: {RESULT_PATH}")

    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
