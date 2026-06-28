from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.localization import messages as messages_mod
from nekofetch.localization.messages import LANG_DIR, M, t
from nekofetch.ui.typography import bq, rule

# Slash commands registered with Telegram. Descriptions come from the catalog so
# editing en.json updates the in-app command menu too.
_COMMAND_KEYS = (
    ("start", M.CMD_START),
    ("help", M.CMD_HELP),
    ("cancel", M.CMD_CANCEL),
    ("reload", M.CMD_RELOAD),
    ("resetoverrides", M.CMD_RESETOVERRIDES),
)


def admin_commands() -> list[BotCommand]:
    return [BotCommand(name, t(key)) for name, key in _COMMAND_KEYS]


# Back-compat constant + helper (older imports referenced these).
ADMIN_COMMANDS = admin_commands()


async def publish_admin_commands(client: Client) -> None:
    await client.set_bot_commands(admin_commands())


def _help_text(role: Role) -> str:
    blocks = [
        t(M.HELP_TITLE),
        t(M.HELP_INTRO),
        f"<i>{rule()}</i>",
        t(M.HELP_H_COMMANDS),
        bq(t(M.HELP_CMD_START)),
        bq(t(M.HELP_CMD_HELP)),
        bq(t(M.HELP_CMD_CANCEL)),
        t(M.HELP_H_EVERYONE),
        bq(t(M.HELP_CAP_REQUEST)),
        bq(t(M.HELP_CAP_MYREQ)),
    ]
    if role in (Role.STAFF, Role.ADMIN):
        blocks += [
            t(M.HELP_H_STAFF),
            bq(t(M.HELP_CAP_REVIEW)),
            bq(t(M.HELP_CAP_QUEUE)),
            bq(t(M.HELP_CAP_APPROVALS)),
        ]
    if role is Role.ADMIN:
        blocks += [t(M.HELP_H_ADMIN), bq(t(M.HELP_CAP_ADMIN))]
    return "\n\n".join(blocks)


def register(client: Client, container: Container) -> None:
    fsm = FSM(container.redis, bot="admin")

    def _role(message: Message) -> Role:
        user = getattr(message, "nf_user", None)
        return Role(user.role) if user else Role.USER

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        await message.reply(_help_text(_role(message)), parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("cancel"))
    async def _cancel(_: Client, message: Message) -> None:
        await fsm.clear(message.from_user.id)
        await message.reply(t(M.CANCELLED), parse_mode=ParseMode.HTML)

    @client.on_message(filters.command("reload"))
    async def _reload(_: Client, message: Message) -> None:
        # Admin-only: re-read en.json from disk so text edits apply without a
        # restart. Shows the exact file path + key count so you can confirm the
        # bot is reading the file you think it is.
        if _role(message) is not Role.ADMIN:
            await message.reply(t(M.ACCESS_DENIED), parse_mode=ParseMode.HTML)
            return
        messages_mod.reload()
        count = len(messages_mod.localizer._catalogs.get("en", {}))
        await message.reply(
            t(M.RELOAD_DONE, count=count, path=str(LANG_DIR / "en.json")),
            parse_mode=ParseMode.HTML,
        )

    @client.on_message(filters.command("resetoverrides"))
    async def _reset_overrides(_: Client, message: Message) -> None:
        # Admin-only: clear Mongo runtime overrides that shadow config.yaml.
        if _role(message) is not Role.ADMIN:
            await message.reply(t(M.ACCESS_DENIED), parse_mode=ParseMode.HTML)
            return
        from nekofetch.services.settings_service import SettingsService

        cleared = await SettingsService(container).clear_overrides()
        await message.reply(t(M.OVERRIDES_CLEARED, count=cleared), parse_mode=ParseMode.HTML)
