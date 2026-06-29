"""Keep human chatter in the log channel tidy.

When a staff member posts an ordinary message in the log channel, we tag it as a
temporary discussion thread: a divider is dropped in front of it (so it reads as
its own section, separate from bot-managed cards) and the whole thread is deleted
after a few idle minutes. Commands and the bot's own posts are ignored.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from nekofetch.core.container import Container


def register(client: Client, container: Container) -> None:
    cfg = container.config.log_channel
    if not (cfg.enabled and cfg.channel_id):
        return  # nothing to watch

    @client.on_message(filters.chat(cfg.channel_id), group=9)
    async def _discussion(_: Client, message: Message) -> None:
        # Ignore everything bot-managed or non-conversational:
        #  • our own posts (cards, sections, dividers) are ``outgoing``
        #  • pin/join service notices
        #  • slash commands
        if getattr(message, "outgoing", False) or getattr(message, "service", None):
            return
        if message.from_user and getattr(message.from_user, "is_self", False):
            return
        if message.text and message.text.startswith("/"):
            return
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(container).note_discussion(message)
