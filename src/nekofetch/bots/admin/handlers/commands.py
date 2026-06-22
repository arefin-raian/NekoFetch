"""Bot command menu + the commands behind it (admin bot).

Telegram shows a tappable command menu (the ``/`` list / "Menu" button) built from
whatever we publish via ``set_bot_commands``. Every command listed here is backed by a
real handler so nothing in the menu is dead:

    /start  -> the main panel (handled in start.py)
    /help   -> a role-aware cheatsheet of commands + button flows
    /cancel -> clear any in-progress flow (search, add-staff, indexing, …)

This module is registered **before** the stateful text routers so ``/help`` and
``/cancel`` are matched here first instead of being mistaken for flow input.
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import BotCommand, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role

# Published to Telegram's command menu. Keep in sync with the handlers below.
ADMIN_COMMANDS = [
    BotCommand("start", "Open the main panel"),
    BotCommand("help", "Show commands & how the bot works"),
    BotCommand("cancel", "Cancel the current action"),
]


async def publish_admin_commands(client: Client) -> None:
    """Push the command menu to Telegram. Call once, after the client has started."""
    await client.set_bot_commands(ADMIN_COMMANDS)


def register(client: Client, container: Container) -> None:
    fsm = FSM(container.redis, bot="admin")

    def _role(message: Message) -> Role:
        user = getattr(message, "nf_user", None)
        return Role(user.role) if user else Role.USER

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        role = _role(message)
        lines = [
            "**◈ NekoFetch — Help**",
            "",
            "Most of the bot is button-driven: send /start and tap your way through.",
            "",
            "**Commands**",
            f"{DIAMOND_FILLED} /start — open the main panel",
            f"{DIAMOND_FILLED} /help — show this message",
            f"{DIAMOND_FILLED} /cancel — abort whatever you're in the middle of",
            "",
            "**Everyone can**",
            f"{DIAMOND_FILLED} Request Anime — search a title, pick a season/scope, submit",
            f"{DIAMOND_FILLED} My Requests — track the status of what you asked for",
        ]
        if role in (Role.STAFF, Role.ADMIN):
            lines += [
                "",
                "**Staff can also**",
                f"{DIAMOND_FILLED} Review Requests — approve a pending request into the queue, or reject it",
                f"{DIAMOND_FILLED} Downloads Queue — watch live download progress",
                f"{DIAMOND_FILLED} Approvals — publish / reprocess / cancel finished content",
            ]
        if role is Role.ADMIN:
            lines += [
                "",
                "**Admins can also**",
                f"{DIAMOND_FILLED} Admin Panel — Settings · Analytics · Staff · Bots · Storage · Broadcast",
            ]
        await message.reply("\n".join(lines))

    @client.on_message(filters.command("cancel"))
    async def _cancel(_: Client, message: Message) -> None:
        await fsm.clear(message.from_user.id)
        await message.reply("Cancelled. Send /start to open the menu.")
