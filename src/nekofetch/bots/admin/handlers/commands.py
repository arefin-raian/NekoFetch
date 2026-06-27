from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.typography import bq, bqx

ADMIN_COMMANDS = [
    BotCommand("start", "Open the main panel"),
    BotCommand("help", "Show commands & how the bot works"),
    BotCommand("cancel", "Cancel the current action"),
]


async def publish_admin_commands(client: Client) -> None:
    await client.set_bot_commands(ADMIN_COMMANDS)


def register(client: Client, container: Container) -> None:
    fsm = FSM(container.redis, bot="admin")

    def _role(message: Message) -> Role:
        user = getattr(message, "nf_user", None)
        return Role(user.role) if user else Role.USER

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        role = _role(message)
        blocks = [
            bq("<b>◆ /start</b> — open the main panel"),
            bq("<b>◆ /help</b> — show this message"),
            bq("<b>◆ /cancel</b> — abort whatever you're in the middle of"),
        ]
        everyone_blocks = [
            bq(f"<b>◆ request anime</b> — search a title, pick a season/scope, submit"),
            bq(f"<b>◆ my requests</b> — track the status of what you asked for"),
        ]
        text_blocks = [
            bq("<b>help</b>"),
            bq("most of the bot is button-driven: send /start and tap your way through."),
            bq("<b>commands</b>"),
            *blocks,
            bq("<b>everyone can</b>"),
            *everyone_blocks,
        ]
        if role in (Role.STAFF, Role.ADMIN):
            text_blocks.extend([
                bq("<b>staff can also</b>"),
                bq("<b>◆ review requests</b> — approve a pending request into the queue, or reject it"),
                bq("<b>◆ downloads queue</b> — watch live download progress"),
                bq("<b>◆ approvals</b> — publish / reprocess / cancel finished content"),
            ])
        if role is Role.ADMIN:
            text_blocks.extend([
                bq("<b>admins can also</b>"),
                bq("<b>◆ admin panel</b> — settings · analytics · staff · bots · storage · broadcast"),
            ])
        await message.reply("\n\n".join(text_blocks), parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("cancel"))
    async def _cancel(_: Client, message: Message) -> None:
        await fsm.clear(message.from_user.id)
        await message.reply(
            bq("cancelled. send /start to open the menu."),
            parse_mode=ParseMode.HTML,
        )
