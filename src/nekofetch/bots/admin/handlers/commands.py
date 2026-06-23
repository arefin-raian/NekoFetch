from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.ui.components import cb, keyboard
from nekofetch.ui.typography import bq, bqx, small_caps

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
            bq("<b>◆ /sᴛᴀʀᴛ</b> — ᴏᴘᴇɴ ᴛʜᴇ ᴍᴀɪɴ ᴘᴀɴᴇʟ"),
            bq("<b>◆ /ʜᴇʟᴘ</b> — sʜᴏᴡ ᴛʜɪs ᴍᴇssᴀɢᴇ"),
            bq("<b>◆ /ᴄᴀɴᴄᴇʟ</b> — ᴀʙᴏʀᴛ ᴡʜᴀᴛᴇᴠᴇʀ ʏᴏᴜ'ʀᴇ ɪɴ ᴛʜᴇ ᴍɪᴅᴅʟᴇ ᴏꜰ"),
        ]
        everyone_blocks = [
            bq(f"<b>◆ ʀᴇǫᴜᴇsᴛ ᴀɴɪᴍᴇ</b> — sᴇᴀʀᴄʜ ᴀ ᴛɪᴛʟᴇ, ᴘɪᴄᴋ ᴀ sᴇᴀsᴏɴ/sᴄᴏᴘᴇ, sᴜʙᴍɪᴛ"),
            bq(f"<b>◆ ᴍʏ ʀᴇǫᴜᴇsᴛs</b> — ᴛʀᴀᴄᴋ ᴛʜᴇ sᴛᴀᴛᴜs ᴏꜰ ᴡʜᴀᴛ ʏᴏᴜ ᴀsᴋᴇᴅ ꜰᴏʀ"),
        ]
        text_blocks = [
            bq("<b>ʜᴇʟᴘ</b>"),
            bq("ᴍᴏsᴛ ᴏꜰ ᴛʜᴇ ʙᴏᴛ ɪs ʙᴜᴛᴛᴏɴ-ᴅʀɪᴠᴇɴ: sᴇɴᴅ /sᴛᴀʀᴛ ᴀɴᴅ ᴛᴀᴘ ʏᴏᴜʀ ᴡᴀʏ ᴛʜʀᴏᴜɢʜ."),
            bq("<b>ᴄᴏᴍᴍᴀɴᴅs</b>"),
            *blocks,
            bq("<b>ᴇᴠᴇʀʏᴏɴᴇ ᴄᴀɴ</b>"),
            *everyone_blocks,
        ]
        if role in (Role.STAFF, Role.ADMIN):
            text_blocks.extend([
                bq("<b>sᴛᴀꜰꜰ ᴄᴀɴ ᴀʟsᴏ</b>"),
                bq("<b>◆ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs</b> — ᴀᴘᴘʀᴏᴠᴇ ᴀ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛ ɪɴᴛᴏ ᴛʜᴇ ǫᴜᴇᴜᴇ, ᴏʀ ʀᴇᴊᴇᴄᴛ ɪᴛ"),
                bq("<b>◆ ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ</b> — ᴡᴀᴛᴄʜ ʟɪᴠᴇ ᴅᴏᴡɴʟᴏᴀᴅ ᴘʀᴏɢʀᴇss"),
                bq("<b>◆ ᴀᴘᴘʀᴏᴠᴀʟs</b> — ᴘᴜʙʟɪsʜ / ʀᴇᴘʀᴏᴄᴇss / ᴄᴀɴᴄᴇʟ ꜰɪɴɪsʜᴇᴅ ᴄᴏɴᴛᴇɴᴛ"),
            ])
        if role is Role.ADMIN:
            text_blocks.extend([
                bq("<b>ᴀᴅᴍɪɴs ᴄᴀɴ ᴀʟsᴏ</b>"),
                bq("<b>◆ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b> — sᴇᴛᴛɪɴɢs · ᴀɴᴀʟʏᴛɪᴄs · sᴛᴀꜰꜰ · ʙᴏᴛs · sᴛᴏʀᴀɢᴇ · ʙʀᴏᴀᴅᴄᴀsᴛ"),
            ])
        await message.reply("\n\n".join(text_blocks), parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("cancel"))
    async def _cancel(_: Client, message: Message) -> None:
        await fsm.clear(message.from_user.id)
        await message.reply(
            bq("ᴄᴀɴᴄᴇʟʟᴇᴅ. sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ᴏᴘᴇɴ ᴛʜᴇ ᴍᴇɴᴜ."),
            parse_mode=ParseMode.HTML,
        )
