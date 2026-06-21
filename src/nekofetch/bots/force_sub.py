"""Force-subscribe gate.

When ``security.force_subscribe`` is on, public users must be members of the configured
channels before using a bot. Returns the channels a user still needs to join (with join
buttons), or an empty list when satisfied / disabled.
"""

from __future__ import annotations

from pyrogram import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)

_NOT_MEMBER = {"LEFT", "BANNED", "RESTRICTED"}


async def channels_to_join(
    client: Client, container: Container, user_id: int
) -> list[tuple[str, str | None]]:
    sec = container.config.security
    if not sec.force_subscribe or not sec.force_subscribe_channels:
        return []

    missing: list[int] = []
    for channel in sec.force_subscribe_channels:
        try:
            member = await client.get_chat_member(channel, user_id)
            status = getattr(member.status, "name", str(member.status)).upper()
            if status in _NOT_MEMBER:
                missing.append(channel)
        except Exception:  # noqa: BLE001 - USER_NOT_PARTICIPANT etc. => not a member
            missing.append(channel)

    out: list[tuple[str, str | None]] = []
    for channel in missing:
        try:
            chat = await client.get_chat(channel)
            url = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
            out.append((chat.title or str(channel), url))
        except Exception:  # noqa: BLE001
            out.append((str(channel), None))
    return out


def join_keyboard(channels: list[tuple[str, str | None]], retry_callback: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"➜ Join {title}", url=url)]
        for title, url in channels
        if url
    ]
    rows.append([InlineKeyboardButton("✓ I've Joined", callback_data=retry_callback)])
    return InlineKeyboardMarkup(rows)
