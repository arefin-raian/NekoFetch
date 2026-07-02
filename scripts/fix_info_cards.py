"""
Fix info/profile cards that were incorrectly wrapped in a single blockquote.

Reference format (from user):
  <blockquote><b>Anime Title | Romaji</b></blockquote>

  <b>‣ Genres :</b> Action, Comedy, Fantasy
  <b>‣ Type :</b> TV
  <b>‣ Average Rating :</b> 82
  <b>‣ Status :</b> FINISHED
  <b>‣ First aired :</b> 2023-10-7
  <b>‣ Last aired :</b> 2024-3-23
  <b>‣ Runtime :</b> 24 minutes
  <b>‣ No of episodes :</b> 24

  <blockquote expandable><b>‣ Synopsis :</b>text text text (Source: Media)</blockquote>
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

CHANNELS_FILE = os.path.expanduser("~/Documents/publishable_entries.json")
DRY_RUN = False

# Lines that are info fields (start with ‣)
INFO_FIELD_RE = re.compile(r'^‣\s*\w+\s*:')


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


def is_info_card(caption: str) -> bool:
    """Detect an anime info/profile card by looking for info fields."""
    return bool(re.search(r'^‣\s*(?:Genres|Type|Rating|Status)', caption, re.MULTILINE))


def has_bad_blockquote(html: str) -> bool:
    """Check if the entire caption is wrapped in a single blockquote (bad)."""
    open_bq = html.count("<blockquote")
    close_bq = html.count("</blockquote>")
    # Bad if exactly 1 blockquote pair at the very start/end of the content
    # This catches both expandable and non-expandable single blockquote wraps
    return open_bq == 1 and close_bq == 1 and html.strip().startswith("<blockquote")


def _escape_html(text: str) -> str:
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def build_info_card_html(caption: str) -> str:
    """
    Rebuild info card with proper format.
    
    Reference:
      <blockquote><b>Anime Title | Romaji</b></blockquote>
      (blank line)
      <b>‣ Genres :</b> values
      <b>‣ Type :</b> value
      ...
      (blank line)
      <blockquote expandable><b>‣ Synopsis :</b>text...</blockquote>
    """
    lines = caption.split("\n")
    
    # Find where info fields start and where synopsis starts
    info_start = None
    synopsis_line_idx = None
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if INFO_FIELD_RE.match(stripped):
            if info_start is None:
                info_start = i
        if stripped.startswith("‣ Synopsis") or stripped.startswith("‣Synopsis"):
            synopsis_line_idx = i
    
    if info_start is None:
        # No info fields found, fallback — just fix title blockquote
        return _fallback_fix(caption)
    
    # Title = lines before info fields
    title_lines = lines[:info_start]
    title_text = "\n".join(l for l in title_lines if l.strip()).strip()
    
    # Info fields = from info_start to synopsis (or end)
    if synopsis_line_idx is not None:
        info_lines = lines[info_start:synopsis_line_idx]
        synopsis_lines = lines[synopsis_line_idx:]
    else:
        info_lines = lines[info_start:]
        synopsis_lines = []
    
    # Build HTML
    parts = []
    
    # Title — plain blockquote (NOT expandable)
    if title_text:
        parts.append(f'<blockquote><b>{_escape_html(title_text)}</b></blockquote>')
    else:
        parts.append("")
    
    parts.append("")  # blank line after title
    
    # Info fields: each line starts with ‣ — bold the label, plain for value
    for line in info_lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Find the colon separator
        colon_idx = stripped.find(":")
        if colon_idx > 0:
            label = stripped[:colon_idx + 1].strip()
            value = stripped[colon_idx + 1:].strip()
            parts.append(f'<b>{_escape_html(label)}</b> {_escape_html(value)}')
        else:
            parts.append(f'<b>{_escape_html(stripped)}</b>')
    
    parts.append("")  # blank line before synopsis
    
    # Synopsis — only the label is bold, text follows directly after </b>
    if synopsis_lines:
        syn_text = "\n".join(synopsis_lines).strip()
        # Split synopsis into label ("‣ Synopsis :") and text
        syn_label = ""
        syn_body = syn_text
        colon_idx = syn_text.find(":")
        if colon_idx > 0 and colon_idx < 30:
            syn_label = syn_text[:colon_idx + 1].strip()
            syn_body = syn_text[colon_idx + 1:].strip()
            # Remove leading/trailing whitespace from body
            parts.append(f'<blockquote expandable><b>{_escape_html(syn_label)}</b>{_escape_html(syn_body)}</blockquote>')
        else:
            parts.append(f'<blockquote expandable><b>{_escape_html(syn_text)}</b></blockquote>')
    
    return "\n".join(parts)


def _fallback_fix(caption: str) -> str:
    """Fallback: just wrap title in blockquote, rest as-is."""
    lines = caption.split("\n")
    if lines and lines[0].strip():
        first_line = lines[0].strip()
        rest = "\n".join(lines[1:])
        return f'<blockquote><b>{_escape_html(first_line)}</b></blockquote>\n\n{rest}'
    return f'<blockquote><b>{_escape_html(caption.strip())}</b></blockquote>'


async def fix_channel_messages(client, channel: str):
    """Fix info cards in one channel."""
    try:
        chat = await client.get_chat(channel)
    except Exception as e:
        print(f"  ⚠️  Cannot access @{channel}: {e}")
        return 0

    cid = chat.id
    fixed = 0

    print(f"\n📡 @{channel}")

    async for msg in client.get_chat_history(cid, limit=20):
        cap = msg.caption or ""
        if not cap:
            continue
        if 'ANIME WEEBS' in cap.upper():
            continue  # Skip footer messages
        
        if is_info_card(cap):
            ents = msg.caption_entities or []
            # Check if it's broken (has blockquotes already but might be wrong)
            has_bq = any(e.type in (MessageEntityType.BLOCKQUOTE, MessageEntityType.EXPANDABLE_BLOCKQUOTE) for e in ents)
            
            if has_bq:
                print(f"    msg {msg.id}: info card ⚠️ (re-fixing with correct format)")
            else:
                print(f"    msg {msg.id}: info card ❌ (no blockquotes — fixing)")
            
            new_html = build_info_card_html(cap)
            
            if not DRY_RUN:
                try:
                    await client.edit_message_caption(
                        chat_id=cid,
                        message_id=msg.id,
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

    return fixed


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
    print(f"{'='*60}")

    totals = 0
    fixed_channels = []

    for ch in channels:
        f = await fix_channel_messages(client, ch["channel"])
        totals += f
        if f > 0:
            fixed_channels.append(ch["channel"])

    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"  Messages fixed:  {totals}")
    print(f"  Channels fixed:  {len(fixed_channels)}")
    for ch in sorted(fixed_channels):
        print(f"    → @{ch}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
