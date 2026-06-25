"""AnimeFair index integration + automatic channel entry.

Talks to @AnimeFair_Index_Bot through a user session: sends a title, reads the
bot's reply (inline buttons and/or text), and extracts ``(anime name → channel)``
entries. Title matching is Anilist-enriched and separator-agnostic. Once a
channel is chosen, we join it — requesting access for private channels and
reporting a "pending" state so the caller can retry after approval.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from nekofetch.core.logging import get_logger
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.sources.telegram.matching import (
    meaningful_variants,
    normalize_words,
    title_matches,
)
from nekofetch.sources.telegram.userbot import UserbotPool

log = get_logger(__name__)

INDEX_BOT = "AnimeFair_Index_Bot"

# t.me links in any shape: @user, t.me/user, t.me/+hash, t.me/joinchat/hash
_TME = re.compile(
    r"(?:https?://)?t\.me/(\+[\w-]+|joinchat/[\w-]+|[A-Za-z]\w{3,})", re.IGNORECASE
)
_USERNAME = re.compile(r"(?<![\w/])@([A-Za-z]\w{3,})")


@dataclass
class IndexEntry:
    name: str
    channel: str          # @username or invite link
    is_invite: bool       # True for t.me/+hash / joinchat links
    raw: str = ""


@dataclass
class ChannelState:
    channel: str
    status: str           # "joined" | "pending" | "public" | "failed"
    chat_id: int | None = None
    detail: str = ""


def _normalize_channel(link: str) -> tuple[str, bool]:
    """Return (channel_ref, is_invite). Usernames keep '@'; invites keep URL."""
    link = link.strip()
    m = _TME.search(link)
    if m:
        tail = m.group(1)
        if tail.startswith(("+", "joinchat/")):
            return (link if link.startswith("http") else f"https://t.me/{tail}"), True
        return f"@{tail}", False
    if link.startswith("@"):
        return link, False
    return f"@{link}", False


class AnimeFairIndex:
    def __init__(self, pool: UserbotPool, anilist: AnilistClient | None = None) -> None:
        self.pool = pool
        self.anilist = anilist or AnilistClient()

    # ---- index query -------------------------------------------------------

    @staticmethod
    def _entries_from_message(msg) -> list[IndexEntry]:
        """Extract (name → channel) entries from one index message.

        AnimeFair's index is plain text with the channel links carried as
        TEXT_LINK **entities** on each anime name (📌 Name → t.me/...). We read
        the entities first, then fall back to inline buttons and bare links/usernames
        for other index formats.
        """
        entries: list[IndexEntry] = []
        text = msg.text or msg.caption or ""
        entities = getattr(msg, "entities", None) or getattr(msg, "caption_entities", None) or []

        # 1) TEXT_LINK / TEXT_MENTION entities — the AnimeFair shape.
        for e in entities:
            etype = getattr(e.type, "name", str(e.type))
            url = getattr(e, "url", None)
            if etype == "TEXT_LINK" and url and ("t.me/" in url or url.startswith("@")):
                name = text[e.offset:e.offset + e.length].strip(" 📌\n\t")
                if name:
                    ch, inv = _normalize_channel(url)
                    entries.append(IndexEntry(name=name, channel=ch, is_invite=inv, raw=url))

        # 2) inline keyboard buttons: text = anime name, url/username = channel
        markup = getattr(msg, "reply_markup", None)
        rows = getattr(markup, "inline_keyboard", None) or []
        for row in rows:
            for btn in row:
                url = getattr(btn, "url", None)
                if url and ("t.me/" in url or url.startswith("@")):
                    ch, inv = _normalize_channel(url)
                    entries.append(IndexEntry(name=btn.text or "", channel=ch,
                                              is_invite=inv, raw=url))

        # 3) bare links / @usernames in plain text (other index formats)
        if not entries:
            for line in text.splitlines():
                m = _TME.search(line) or _USERNAME.search(line)
                if not m:
                    continue
                ch, inv = _normalize_channel(m.group(0))
                name = re.sub(_TME, "", line)
                name = re.sub(_USERNAME, "", name)
                name = re.sub(r"[\-–—:|•·📌]+", " ", name).strip(" \t-–—:|") or ch
                entries.append(IndexEntry(name=name, channel=ch, is_invite=inv, raw=line))
        return entries

    async def _fetch_index(self) -> list[IndexEntry]:
        """Trigger /start and read the full multi-part index from the bot's chat.

        AnimeFair is menu-driven (it rejects free-text search), so we pull the
        whole index once and match locally against it.
        """
        async def run(client) -> list[IndexEntry]:
            await client.send_message(INDEX_BOT, "/start")
            await asyncio.sleep(4.0)
            entries: list[IndexEntry] = []
            seen: set[str] = set()
            async for msg in client.get_chat_history(INDEX_BOT, limit=20):
                if getattr(msg, "outgoing", False):
                    continue
                for e in self._entries_from_message(msg):
                    key = f"{e.name.lower()}|{e.channel}"
                    if key not in seen:
                        seen.add(key)
                        entries.append(e)
            return entries
        return await self.pool.execute(run)

    async def lookup(self, title: str) -> list[IndexEntry]:
        """Return index entries whose name matches ``title`` (Anilist-expanded)."""
        variants = meaningful_variants(await self.anilist.title_variants(title))
        index = await self._fetch_index()
        matches: list[IndexEntry] = []
        for e in index:
            if any(title_matches(v, e.name, threshold=0.85) for v in variants if v):
                matches.append(e)
        return matches

    async def find_channel(self, title: str) -> IndexEntry | None:
        """Best index entry whose name matches ``title`` via Anilist variants."""
        variants = meaningful_variants(await self.anilist.title_variants(title))
        entries = await self.lookup(title)
        if not entries:
            return None
        scored: list[tuple[float, int, IndexEntry]] = []
        for e in entries:
            score = max(
                (len(normalize_words(v) & normalize_words(e.name)) / max(1, len(normalize_words(v)))
                 for v in variants if normalize_words(v)),
                default=0.0,
            )
            scored.append((score, len(normalize_words(e.name)), e))
        # highest score, then the most specific (shortest) name
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][2]

    # ---- channel entry -----------------------------------------------------

    async def enter_channel(self, entry: IndexEntry) -> ChannelState:
        """Join the channel; request access if private, report pending state."""
        async def run(client) -> ChannelState:
            from pyrogram.errors import (
                InviteRequestSent,
                UserAlreadyParticipant,
            )
            target = entry.channel
            try:
                chat = await client.join_chat(target)
                return ChannelState(target, "joined", getattr(chat, "id", None))
            except UserAlreadyParticipant:
                chat = await client.get_chat(target)
                return ChannelState(target, "joined", getattr(chat, "id", None))
            except InviteRequestSent:
                # Private channel with admin approval — request queued.
                return ChannelState(target, "pending",
                                    detail="join request sent; retry after approval")
            except Exception as exc:  # noqa: BLE001
                # Some public channels just need get_chat to resolve membership.
                try:
                    chat = await client.get_chat(target)
                    return ChannelState(target, "public", getattr(chat, "id", None))
                except Exception:  # noqa: BLE001
                    return ChannelState(target, "failed", detail=str(exc))

        return await self.pool.execute(run)

    async def is_member(self, channel: str) -> bool:
        """Check whether the active account is now a member (post-approval retry)."""
        async def run(client) -> bool:
            try:
                await client.get_chat_history(channel, limit=1).__anext__()
                return True
            except Exception:  # noqa: BLE001
                return False
        try:
            return await self.pool.execute(run)
        except Exception:  # noqa: BLE001
            return False
