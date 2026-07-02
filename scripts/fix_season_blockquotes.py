"""
Fix season/movie/episode card messages to have proper blockquote structure.

The Eminence in Shadow reference format for season cards:
  <blockquote expandable><b>Anime Title | Romaji</b></blockquote><b>
  ────────────────────
  ➥ Season: XX
  ➤ Episode: XX
  ➥ Quality: XX [Dual]
  ────────────────────
  </b><blockquote expandable><b>➥ Synopsis: ...</b></blockquote><b>
  </b><blockquote expandable><b>‣ Powered By ~ </b><a href="..."><b>@channel</b></a></blockquote>

This script replaces ALL formatting on season/movie cards with the proper structure.
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
DRY_RUN = False  # Set True to scan only

POWERED_BY_RE = re.compile(r'‣?\s*Powered\s*By\s*[~:]\s*@(\w+)', re.IGNORECASE)
BORDER_RE = re.compile(r'^[─—━]+$')  # dashed border line


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


def has_blockquote(entities: list) -> bool:
    for e in entities:
        if e.type in (MessageEntityType.BLOCKQUOTE, MessageEntityType.EXPANDABLE_BLOCKQUOTE):
            return True
    return False


def is_footer_message(caption: str) -> bool:
    return "ANIME WEEBS" in caption.upper() or "feel the story" in caption.lower()


def is_season_card(caption: str) -> bool:
    """Detect a season/movie card by looking for content patterns."""
    has_arrows = "➥" in caption or "➤" in caption or "🔹" in caption
    has_powered = bool(POWERED_BY_RE.search(caption))
    has_synopsis = "Synopsis" in caption
    has_season = bool(re.search(r'Season\s+\d|Movie|Prelude|Film|OVA|Special', caption, re.IGNORECASE))
    has_watch_guide = "How to Watch" in caption
    return (has_arrows or has_powered or has_synopsis or has_season or has_watch_guide)


def find_border_index(lines: list[str], start: int = 0) -> int | None:
    """Find index of the next dashed border line, starting from `start`."""
    for i in range(start, len(lines)):
        if BORDER_RE.match(lines[i].strip()):
            return i
    return None


def build_season_card_html(caption: str) -> str:
    """
    Rebuild a season/movie card with proper blockquote + bold structure.
    
    Structure (matching Eminence in Shadow format):
    <blockquote expandable><b>title</b></blockquote><b>
    ── border ──
    ➥ metadata
    ➤ metadata
    ➥ metadata
    ── border ──
    </b><blockquote expandable><b>➥ Synopsis: text</b></blockquote><b>
    </b><blockquote expandable><b>‣ Powered By ~ </b><a href="..."><b>@channel</b></a></blockquote>
    """
    lines = caption.split("\n")
    
    # ── Find the two borders ──
    b1 = find_border_index(lines, 0)      # first border
    if b1 is None:
        # No borders found — simple case: just wrap in blockquotes
        return _simple_blockquote_wrap(caption)
    
    b2 = find_border_index(lines, b1 + 1)  # second border
    if b2 is None:
        b2 = len(lines)  # no second border, rest is content
    
    # ── Split into sections ──
    title_lines = lines[:b1]                      # before first border
    meta_lines = lines[b1:b2 + 1]                 # first border + metadata + second border
    content_lines = lines[b2 + 1:] if b2 < len(lines) else []  # after second border
    
    # ── Build title blockquote ──
    title_text = "\n".join(line for line in title_lines if line.strip()).strip()
    if title_text:
        title_html = f'<blockquote expandable><b>{_escape_html(title_text)}</b></blockquote>'
    else:
        title_html = ""
    
    # ── Build metadata section (bold) ──
    meta_text = "\n".join(meta_lines)
    # Trim dashes but keep the structure
    meta_html = f'<b>{_escape_html(meta_text)}</b>'
    
    # ── Build synopsis blockquote ──
    content_text = "\n".join(content_lines)
    synopsis_html = ""
    footer_html = ""
    
    # Check for "Powered By" in content
    pb_match = POWERED_BY_RE.search(content_text)
    
    if pb_match:
        # Split content into synopsis + footer
        # Find the line where "‣ Powered By" appears
        pb_line_idx = None
        content_lines2 = content_lines if content_lines else []
        for i, line in enumerate(content_lines2):
            if POWERED_BY_RE.search(line):
                pb_line_idx = i
                break
        
        if pb_line_idx is not None:
            # Synopsis = lines before "Powered By"
            synopsis_lines = content_lines2[:pb_line_idx]
            footer_line = content_lines2[pb_line_idx]
        else:
            synopsis_lines = content_lines2
            footer_line = ""
    else:
        synopsis_lines = content_lines if content_lines else []
        footer_line = ""
    
    # Build synopsis html
    synopsis_text = "\n".join(line for line in synopsis_lines if line.strip()).strip()
    if synopsis_text:
        synopsis_html = f'<blockquote expandable><b>{_escape_html(synopsis_text)}</b></blockquote>'
    
    # Build footer html
    if footer_line:
        fb_match = POWERED_BY_RE.search(footer_line)
        if fb_match:
            username = fb_match.group(1)
            link = f"https://t.me/{username}"
            before_at = footer_line[:footer_line.index("@")]
            at_part = footer_line[footer_line.index("@"):]
            # Check if there's more after the @username
            after_at = at_part[len(username) + 1:] if len(at_part) > len(username) + 1 else ""
            footer_html = (
                f'<blockquote expandable><b>{_escape_html(before_at)}</b>'
                f'<a href="{link}"><b>@{username}</b></a>'
                f'{_escape_html(after_at)}</blockquote>'
            )
        else:
            footer_html = f'<blockquote expandable><b>{_escape_html(footer_line)}</b></blockquote>'
    
    # ── Assemble ──
    parts = [title_html, meta_html]
    if synopsis_html:
        parts.append(synopsis_html)
    if footer_html:
        parts.append(footer_html)
    
    final = "\n".join(p for p in parts if p)
    return final


def _escape_html(text: str) -> str:
    """Escape HTML special chars but preserve Telegram emoji and unicode."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _simple_blockquote_wrap(caption: str) -> str:
    """Fallback: wrap entire caption in blockquote + bold."""
    return f'<blockquote expandable><b>{_escape_html(caption.strip())}</b></blockquote>'


def fix_watch_guide_html(caption: str) -> str:
    """Rebuild watch guide with proper blockquote around tip."""
    lines = caption.split("\n")
    result_lines = []
    tip_lines = []
    in_tip = False
    
    for line in lines:
        stripped = line.strip()
        
        # Detect tip/blockquote lines
        if "streaming" in stripped.lower() or "performance" in stripped.lower() or "player" in stripped.lower():
            in_tip = True
            tip_lines.append(stripped)
            continue
        
        if in_tip:
            in_tip = False
            tip_text = " ".join(tip_lines)
            result_lines.append(f'<blockquote expandable><b>{_escape_html(tip_text.rstrip("!"))}</b>!</blockquote>')
            tip_lines = []
        
        result_lines.append(line)
    
    # Handle tip at end
    if tip_lines:
        tip_text = " ".join(tip_lines)
        result_lines.append(f'<blockquote expandable><b>{_escape_html(tip_text.rstrip("!"))}</b>!</blockquote>')
    
    return "\n".join(result_lines)


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
        has_bq = has_blockquote(entities)

        # ── FOOTER MESSAGE ──
        if is_footer_message(cap):
            if has_bq:
                print(f"    msg {msg_id}: footer ✅ (blockquotes present)")
                continue
            # Footer already handled by previous script — skip
            print(f"    msg {msg_id}: footer ⚠️  (no blockquotes) — SKIP (handled separately)")
            continue

        # ── SEASON/MOVIE/WATCH GUIDE CARD ──
        if is_season_card(cap):
            if has_bq:
                # Force re-edit to fix extra line breaks between synopsis and footer
                print(f"    msg {msg_id}: ✅ has blockquotes (re-fixing line breaks)")

            # Determine card type
            is_watch = "How to Watch" in cap
            if is_watch:
                new_html = fix_watch_guide_html(cap)
                print(f"    msg {msg_id}: watch guide ❌ → fixing blockquotes")
            else:
                new_html = build_season_card_html(cap)
                print(f"    msg {msg_id}: season/movie card ❌ → rebuilding with blockquotes")

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
                print(f"      [DRY RUN] Would fix")
                fixed += 1
        else:
            first_line = cap.split("\n")[0][:60]
            if has_bq:
                print(f"    msg {msg_id}: other ✅ ({first_line!r})")
            else:
                print(f"    msg {msg_id}: other ❌ ({first_line!r}) — no pattern match — SKIP")

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
        print(f"  ⚠️  No edits will be made.")
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
    print(f"  Fixed:           {totals['fixed']}")
    print(f"  Channels fixed:  {len(fixed_channels)}")
    for ch in sorted(fixed_channels):
        print(f"    → @{ch}")
    if not DRY_RUN:
        print(f"  ✅ Edits applied!")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
