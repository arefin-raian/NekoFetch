"""AcuteBot metadata provider — fetches anime info cards from @acutebot.

Primary data source for the bot's first message (info card). Sends /anime <title>
to @acutebot via the userbot pool and parses the resulting info card into a
structured dict. Falls back gracefully to AniList/TMDB when the bot is unavailable.

@acutebot response format:

  <Title> | <Alternative Title>          ← bold
    
  ‣ Genres : <value>                        ← label bold
  ‣ Type : <value>
  ‣ Average Rating : <value>
  ‣ Status : <value>
  ‣ First aired : <value>
  ‣ Last aired : <value>
  ‣ Runtime : <value> minutes
  ‣ No of episodes : <value>
    
  ‣ Synopsis : <text> …read more         ← synopsis italic, "read more" is a link
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from nekofetch.core.logging import get_logger

if TYPE_CHECKING:
    from pyrogram import Client

log = get_logger(__name__)

_BOT_USERNAME = "acutebot"
_CMD_PREFIX = "/anime "
# The field labels @acutebot uses — maps to our internal keys
_FIELD_LABELS: dict[str, str] = {
    "genres": "genres",
    "type": "format",
    "average rating": "score",
    "status": "status",
    "first aired": "first_aired",
    "last aired": "last_aired",
    "runtime": "runtime",
    "no of episodes": "episode_count",
    "synopsis": "synopsis",
}

_LABEL_RE = re.compile(r"^‣\s*(.+?)\s*:\s*(.*)")


async def fetch_from_acutebot(
    title_query: str,
    pool: object,  # UserbotPool, typing imported lazily
    photo_dir: str | None = None,  # persistent directory to save the photo
) -> dict | None:
    """Fetch anime metadata from @acutebot for the given title.

    Returns a flat dict with keys matching BotContentService._gather_metadata()
    output, or None if the bot is unreachable or doesn't know the title.

    When ``photo_dir`` is provided the AcuteBot photo is downloaded to
    ``{photo_dir}/{sanitized_query}.jpg`` so it can be used as the info-card
    image.  The path is stored in ``poster_url``.
    """
    try:
        from nekofetch.sources.telegram.userbot import UserbotPool

        assert isinstance(pool, UserbotPool)
        return await pool.execute(lambda c: _do_fetch(c, title_query, photo_dir))
    except Exception as exc:
        log.warning("acutebot.fetch.failed", title=title_query, error=str(exc))
        return None


async def _do_fetch(client: "Client", title_query: str, photo_dir: str | None = None) -> dict | None:
    """Execute the /anime command and parse the response."""
    # Send the command
    await client.send_message(_BOT_USERNAME, f"{_CMD_PREFIX}{title_query}")
    await asyncio.sleep(3.5)  # wait for bot to respond

    # Fetch recent messages from the bot and find the info card
    # (one with a photo + text containing "‣ Genres")
    async for msg in client.get_chat_history(_BOT_USERNAME, limit=5):
        text = msg.text or msg.caption or ""

        # Skip messages that don't look like info cards
        if "‣ Genres" not in text:
            continue

        # Found the info card — parse it
        # Download the photo to a persistent path so it can be reused
        photo_path: str | None = None
        if photo_dir and msg.photo:
            from pathlib import Path

            out = Path(photo_dir)
            out.mkdir(parents=True, exist_ok=True)
            # Sanitize the query to a safe filename
            safe = "".join(c for c in title_query if c.isalnum() or c in (" ", "-", "_")).strip()
            safe = safe.replace(" ", "_")[:64] or "anime"
            dest = out / f"{safe}.jpg"
            try:
                downloaded = await client.download_media(msg.photo.file_id, file_path=str(dest))
                if downloaded:
                    photo_path = str(Path(downloaded))
                    log.info("acutebot.photo.saved", path=photo_path)
            except Exception as exc:
                log.warning("acutebot.photo.download.failed", error=str(exc))

        return _parse_card(text, msg, photo_path=photo_path)

    return None


def _parse_card(text: str, msg: object, photo_path: str | None = None) -> dict:
    """Parse @acutebot's info card text + photo into a structured dict."""
    from pyrogram.types import Message

    assert isinstance(msg, Message)

    meta: dict = {
        "title": None,
        "romaji": None,
        "format": None,
        "status": None,
        "score": None,
        "genres": [],
        "synopsis": None,
        "episode_count": None,
        "first_aired": None,
        "last_aired": None,
        "runtime": None,
        "poster_url": photo_path,
        "_source": "acutebot",
    }

    # Parse the header: "Title | Alternative Title"
    lines = text.split("\n")
    header = lines[0].strip() if lines else ""
    if "|" in header:
        parts = header.split("|", 1)
        meta["title"] = parts[0].strip()
        meta["romaji"] = parts[1].strip()
    else:
        meta["title"] = header
        meta["romaji"] = header

    # Parse field lines: "‣ Genres : Action, Drama"
    current_synopsis: list[str] = []
    in_synopsis = False

    for line in lines:
        m = _LABEL_RE.match(line)
        if m:
            label = m.group(1).strip().lower()
            value = m.group(2).strip()
            key = _FIELD_LABELS.get(label)

            if key == "synopsis":
                in_synopsis = True
                current_synopsis.append(value)
            elif key == "genres":
                meta["genres"] = [g.strip() for g in value.split(",") if g.strip()]
            elif key == "score":
                try:
                    meta["score"] = str(round(float(value), 1))
                except (ValueError, TypeError):
                    meta["score"] = value
            elif key == "episode_count":
                try:
                    meta["episode_count"] = int(value)
                except (ValueError, TypeError):
                    meta["episode_count"] = value
            elif key == "runtime":
                # "24 minutes per episode" -> extract number
                rt_match = re.search(r"(\d+)", value)
                meta["runtime"] = f"{rt_match.group(1)} min/ep" if rt_match else value
            elif key:
                meta[key] = value
        elif in_synopsis:
            # Continuation of synopsis
            current_synopsis.append(line.strip())

    # Clean up synopsis — remove the "…read more" link suffix
    if current_synopsis:
        raw = " ".join(current_synopsis)
        # Remove the trailing "read more" or "…read more" link text
        raw = re.sub(r"\s*…?\s*read\s+more\s*$", "", raw, flags=re.IGNORECASE).strip()
        meta["synopsis"] = raw or None

    return meta
