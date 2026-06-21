"""Index channel service.

Maintains stylized, per-first-letter index posts in a dedicated channel, e.g.::

    •──────────•°• Z •°•──────────•
    ⦿ Zom 100: Bucket List Of The Dead
    ⦿ Zombieland Saga

Each letter is a single message the bot edits in place as titles are published. The
main-channel "Index" button deep-links to the relevant letter message.
"""

from __future__ import annotations

from sqlalchemy import distinct, select

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.infrastructure.database.postgres.models import StoragePack
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.ui import templates

log = get_logger(__name__)

_LETTER_KEY = "nf:index:letter:{letter}"


class IndexChannelService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self.cfg = container.config.index_channel

    def _active(self) -> bool:
        client = getattr(self._c, "admin_client", None)
        return bool(self.cfg.enabled and self.cfg.channel_id != 0 and client is not None)

    @staticmethod
    def letter_of(title: str) -> str:
        for ch in title:
            if ch.isalpha():
                return ch.upper()
            if ch.isdigit():
                return "#"
        return "#"

    async def _titles_for_letter(self, letter: str) -> list[str]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (
                await session.execute(select(distinct(StoragePack.anime_title)))
            ).scalars().all()
        return sorted({t for t in rows if self.letter_of(t) == letter})

    async def refresh_letter(self, letter: str) -> int | None:
        """Create/edit the message for ``letter``; return its message id."""
        if not self._active():
            return None
        titles = await self._titles_for_letter(letter)
        if not titles:
            return None
        entries = "\n".join(templates.render(self.cfg.entry_template, title=t) for t in titles)
        text = templates.render(self.cfg.letter_header_template, letter=letter) + "\n" + entries

        client = self._c.admin_client
        key = _LETTER_KEY.format(letter=letter)
        mid = await self._c.redis.get(key) if self._c.redis else None
        try:
            if mid:
                await client.edit_message_text(self.cfg.channel_id, int(mid), text)
                return int(mid)
            msg = await client.send_message(self.cfg.channel_id, text)
            if self._c.redis:
                await self._c.redis.set(key, msg.id)
            return msg.id
        except Exception as exc:  # noqa: BLE001
            if "MESSAGE_NOT_MODIFIED" in str(exc) and mid:
                return int(mid)
            log.warning("index.refresh.failed", letter=letter, error=str(exc))
            return int(mid) if mid else None

    async def entry_link(self, title: str) -> str | None:
        """Ensure the title's letter post is current and return a link to it."""
        if not self._active():
            return None
        letter = self.letter_of(title)
        mid = await self.refresh_letter(letter)
        if mid is None:
            return None
        try:
            chat = await self._c.admin_client.get_chat(self.cfg.channel_id)
            if chat.username:
                return f"https://t.me/{chat.username}/{mid}"
        except Exception:  # noqa: BLE001
            pass
        internal = str(self.cfg.channel_id).replace("-100", "", 1)
        return f"https://t.me/c/{internal}/{mid}"
