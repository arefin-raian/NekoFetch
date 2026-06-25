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
from nekofetch.sources.telegram.matching import normalize_words, title_matches
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

    async def _ask_bot(self, text: str, *, wait: float = 4.0) -> list:
        """Send ``text`` to the index bot and return its reply message(s)."""
        async def run(client):
            from pyrogram.enums import ChatType  # noqa: F401  (ensures pyrogram present)
            sent = await client.send_message(INDEX_BOT, text)
            # Poll for a bot reply newer than what we sent.
            for _ in range(int(wait / 0.5)):
                await asyncio.sleep(0.5)
                replies = []
                async for msg in client.get_chat_history(INDEX_BOT, limit=5):
                    if msg.id > sent.id and not msg.outgoing:
                        replies.append(msg)
                if replies:
                    return list(reversed(replies))
            return []
        return await self.pool.execute(run)

    @staticmethod
    def _entries_from_message(msg) -> list[IndexEntry]:
        """Extract (name → channel) entries from buttons and text of one message."""
        entries: list[IndexEntry] = []

        # 1) inline keyboard buttons: text = anime name, url/username = channel
        markup = getattr(msg, "reply_markup", None)
        rows = getattr(markup, "inline_keyboard", None) or []
        for row in rows:
            for btn in row:
                url = getattr(btn, "url", None)
                if url and ("t.me/" in url or url.startswith("@")):
                    ch, inv = _normalize_channel(url)
                    entries.append(IndexEntry(name=btn.text or "", channel=ch,
                                              is_invite=inv, raw=url))

        # 2) text links (entities) + inline @usernames / t.me links per line
        text = msg.text or msg.caption or ""
        for line in text.splitlines():
            m = _TME.search(line) or _USERNAME.search(line)
            if not m:
                continue
            ch, inv = _normalize_channel(m.group(0))
            # name = the line with the link stripped out
            name = re.sub(_TME, "", line)
            name = re.sub(_USERNAME, "", name)
            name = re.sub(r"[\-–—:|•·]+", " ", name).strip(" \t-–—:|") or ch
            entries.append(IndexEntry(name=name, channel=ch, is_invite=inv, raw=line))
        return entries

    async def lookup(self, title: str) -> list[IndexEntry]:
        """Query the index for ``title`` (Anilist-expanded) and return entries."""
        variants = await self.anilist.title_variants(title)
        # Query the bot with the most canonical names first.
        seen_ch: set[str] = set()
        found: list[IndexEntry] = []
        for q in variants[:4]:
            try:
                messages = await self._ask_bot(q)
            except Exception as exc:  # noqa: BLE001
                log.warning("animefair.ask.failed", query=q, error=str(exc))
                continue
            for msg in messages:
                for e in self._entries_from_message(msg):
                    if e.channel not in seen_ch:
                        seen_ch.add(e.channel)
                        found.append(e)
            if found:
                break
        return found

    async def find_channel(self, title: str) -> IndexEntry | None:
        """Best index entry whose name matches ``title`` via Anilist variants."""
        variants = await self.anilist.title_variants(title)
        entries = await self.lookup(title)
        if not entries:
            return None
        # Prefer entries whose name contains all meaningful words of any variant.
        scored: list[tuple[float, IndexEntry]] = []
        for e in entries:
            score = max(
                (len(normalize_words(v) & normalize_words(e.name)) / max(1, len(normalize_words(v)))
                 for v in variants if normalize_words(v)),
                default=0.0,
            )
            scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]
        if best_score >= 0.6 or any(
            title_matches(v, best.name, threshold=0.8) for v in variants
        ):
            return best
        return None

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
