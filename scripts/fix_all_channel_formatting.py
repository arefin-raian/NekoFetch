"""
Fix all download channel messages that lost their formatting entities.

Earlier script edited messages with plain text replacement, stripping BOLD and
BLOCKQUOTE entities. Only TEXT_LINK survived.

Strategy:
1. For footer messages (contain "ANIME WEEBS"): replace entire caption with
   proper HTML footer matching Eminence in Shadow format exactly.
2. For season/movie cards (contain "Powered By", arrows, season patterns):
   detect common structure and add BOLD to titles, proper link to footer.
3. Always check if message already has BOLD/BLOCKQUOTE entities before editing.
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
from pyrogram.enums import MessageEntityType, ParseMode

# ── Config ───────────────────────────────────────────────────────────────────

CHANNELS_FILE = os.path.expanduser("~/Documents/publishable_entries.json")
DRY_RUN = False  # Actual fix mode

# Proper HTML footer — exact format from Eminence in Shadow (user-fixed reference).
# ⚠️  The small-caps unicode chars (ꜰ, ᴇ, etc.) are aesthetic — they must stay.
# ⚠️  BOLD + TEXT_LINK overlap on @usernames for clickable bold links.
# ⚠️  BLOCKQUOTE around title line and visit line.
PROPER_FOOTER_HTML = (
    '<blockquote expandable><b>ANIME WEEBS - ꜰᴇᴇʟ ᴛʜᴇ ꜱᴛᴏʀʏ, ʟɪᴠᴇ ᴛʜᴇ ᴀʀᴛ</b></blockquote>\n'
    '─────────────────────\n'
    '<b>⬥ Aɴɪᴍᴇ: </b><a href="https://t.me/AniXWeebs"><b>@AɴɪXWᴇᴇʙs</b></a><b>\n'
    '⬥ Nᴇᴛᴡᴏʀᴋ: </b><a href="https://t.me/WeebsXServer"><b>@WᴇᴇʙsXSᴇʀᴠᴇʀ</b></a><b>\n'
    '⬥ Oɴɢᴏɪɴɢ: </b><a href="https://t.me/Ongoing_AniXWeebs"><b>@Oɴɢᴏɪɴɢ_AɴɪXWᴇᴇʙs</b></a><b>\n'
    '⬥ Aɴɪᴍᴇ Mᴏᴠɪᴇs: </b><a href="https://t.me/AniMovieXWeebs"><b>@AɴɪMᴏᴠɪᴇXWᴇᴇʙs</b></a>\n'
    '─────────────────────\n'
    '<blockquote expandable><b>Vɪsɪᴛ </b><a href="https://t.me/WeebsXGC">@WᴇᴇʙsXGC</a> <b>ғᴏʀ ᴍᴏʀᴇ ɪɴғᴏ</b></blockquote>'
)

POWERED_BY_RE = re.compile(r'‣?\s*Powered\s*By\s*[~:]\s*@(\w+)', re.IGNORECASE)


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_channels() -> list[dict]:
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    seen = set()
    result = []
    for e in data.get("publishable_entries", []):
        for dl in e.get("download_channels", []):
            ch = dl.get("channel", "")
            if ch and ch not in seen:
                seen.add(ch)
                result.append({"title": e.get("title", "?"), "channel": ch})
    return result


def has_bold_or_blockquote(entities: list) -> bool:
    for e in entities:
        if e.type in (MessageEntityType.BOLD, MessageEntityType.BLOCKQUOTE,
                      MessageEntityType.EXPANDABLE_BLOCKQUOTE):
            return True
    return False


def is_footer_message(caption: str) -> bool:
    """Detect the ANIME WEEBS branding footer message."""
    return "ANIME WEEBS" in caption.upper() and ("feel the story" in caption.lower() or "ꜰᴇᴇʟ" in caption)


def is_season_card(caption: str) -> bool:
    """Detect a season/movie card message by looking for expected patterns."""
    has_arrows = "➥" in caption or "➤" in caption or "🔹" in caption
    has_powered = bool(POWERED_BY_RE.search(caption))
    has_synopsis = "Synopsis" in caption
    has_season = bool(re.search(r'Season\s+\d|Movie|Prelude|Film', caption, re.IGNORECASE))
    # Also detect "How to Watch" guides
    has_watch_guide = "How to Watch" in caption
    return (has_arrows or has_powered or has_synopsis or has_season or has_watch_guide)


def fix_season_card_html(caption: str) -> str:
    """Convert a broken plain-text season/movie card to proper HTML.

    Rules:
    - First non-empty line (anime title) → BOLD
    - Lines with ➥/➤/🔹 followed by title keywords → BOLD the title part
    - "Powered By ~ @username" → proper <a> link
    - Tip/blockquote lines → <blockquote expandable>
    """
    lines = caption.split("\n")
    result = []
    title_done = False  # first meaningful line gets bolded

    for line in lines:
        stripped = line.strip()

        # ── First non-empty, non-border line → BOLD (anime title) ──
        if not title_done and stripped and not stripped.startswith("─") and not stripped.startswith("➥") and not stripped.startswith("➤") and not stripped.startswith("🔹") and not stripped.startswith("‣") and not stripped.startswith("⬥"):
            result.append(f"<b>{stripped}</b>")
            title_done = True
            continue

        # ── "Powered By ~ @username" → proper link ──
        m = POWERED_BY_RE.search(stripped)
        if m:
            username = m.group(1)
            link = f"https://t.me/{username}"
            # Replace just the @username part with a link
            before = stripped[:stripped.index("@")]
            result.append(f'<b>{before}</b><a href="{link}"><b>@{username}</b></a>')
            continue

        # ── Season/movie title lines with arrows ──
        # Keep the arrow character, bold the rest
        if stripped.startswith("➥") or stripped.startswith("➤") or stripped.startswith("🔹"):
            arrow = stripped[0]
            rest = stripped[1:].strip()
            # Title lines typically have "Season", "Movie", "Film", etc.
            if any(kw in rest for kw in ["Season", "Movie", "Film", "Episode", "Arc", "Part", "Special", "OVA", "Prelude"]):
                result.append(f"{arrow} <b>{rest}</b>")
            elif rest.startswith("["):  # Button like [Click Here]
                # Keep as-is — we don't know the URL
                result.append(line)
            else:
                result.append(line)
            continue

        # ── Tip/blockquote lines ──
        if "streaming" in stripped.lower() or ("For the best" in stripped and "performance" in stripped.lower()):
            text = stripped.rstrip("!")
            result.append(f'<blockquote expandable><b>{text}</b>!</blockquote>')
            continue

        # ── Everything else ──
        result.append(line)

    return "\n".join(result)


async def fix_channel_messages(client, channel: str):
    """Fix all broken messages in one channel."""
    try:
        chat = await client.get_chat(channel)
    except Exception as e:
        print(f"  ⚠️  Cannot access @{channel}: {e}")
        return 0, 0

    cid = chat.id
    total = 0
    fixed = 0

    print(f"\n📡 @{channel}")

    # Collect messages with captions
    messages = []
    async for msg in client.get_chat_history(cid, limit=30):
        cap = msg.caption or ""
        if not cap:
            continue
        messages.append((msg.id, cap, msg.caption_entities or []))
        total += 1

    if total == 0:
        print(f"    0 messages with captions")
        return 0, 0

    for msg_id, cap, entities in messages:
        has_fmt = has_bold_or_blockquote(entities)

        # ── FOOTER MESSAGE ──
        if is_footer_message(cap):
            if has_fmt:
                print(f"    msg {msg_id}: footer ✅ (already formatted)")
                continue

            print(f"    msg {msg_id}: footer ❌ → replacing with proper HTML")
            if not DRY_RUN:
                try:
                    await client.edit_message_caption(
                        chat_id=cid,
                        message_id=msg_id,
                        caption=PROPER_FOOTER_HTML,
                        parse_mode=ParseMode.HTML,
                    )
                    print(f"      ✅ Done")
                    fixed += 1
                except Exception as e:
                    print(f"      ❌ {e}")
            else:
                print(f"      [DRY RUN] Would replace footer")
                fixed += 1

        # ── SEASON/MOVIE CARD ──
        elif is_season_card(cap):
            if has_fmt:
                print(f"    msg {msg_id}: season card ✅ (already formatted)")
                continue

            print(f"    msg {msg_id}: season card ❌ → fixing formatting")
            new_html = fix_season_card_html(cap)
            if not DRY_RUN:
                try:
                    await client.edit_message_caption(
                        chat_id=cid,
                        message_id=msg_id,
                        caption=new_html,
                        parse_mode=ParseMode.HTML,
                    )
                    print(f"      ✅ Done")
                    fixed += 1
                except Exception as e:
                    print(f"      ❌ {e}")
            else:
                print(f"      [DRY RUN] Would fix season card")
                fixed += 1

        else:
            # Unknown message type — log it
            first_line = cap.split("\n")[0][:60]
            if has_fmt:
                print(f"    msg {msg_id}: other ✅ ({first_line!r})")
            else:
                print(f"    msg {msg_id}: other ❌ ({first_line!r}) — no pattern match, no formatting — SKIP")

    return total, fixed


async def main():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    channels = load_channels()
    print(f"{'='*60}")
    print(f"  Channels to check: {len(channels)}")
    print(f"  DRY_RUN = {DRY_RUN}")
    if DRY_RUN:
        print(f"  ⚠️  No edits will be made. Set DRY_RUN=False to actually fix.")
    print(f"{'='*60}")

    totals = {"total": 0, "fixed": 0}
    fixed_channels = []

    for ch in channels:
        t, f = await fix_channel_messages(client, ch["channel"])
        totals["total"] += t
        totals["fixed"] += f
        if f > 0:
            fixed_channels.append(ch["channel"])

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"  Total messages:  {totals['total']}")
    print(f"  Would fix:       {totals['fixed']}")
    print(f"  Channels to fix: {len(fixed_channels)}")
    for ch in sorted(fixed_channels):
        print(f"    → @{ch}")
    if not DRY_RUN:
        print(f"  ✅ Edits applied!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
