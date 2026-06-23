from __future__ import annotations

from pyrogram.types import InlineKeyboardMarkup

from nekofetch.domain.enums import Role
from nekofetch.localization.i18n import Localizer
from nekofetch.ui.components import cb, keyboard


def welcome_keyboard(localizer: Localizer, role: Role, lang: str = "en") -> InlineKeyboardMarkup:
    rows = [
        [
            (localizer.get("btn_request_anime", lang), cb("req", "new")),
            (localizer.get("btn_my_requests", lang), cb("req", "mine", 0)),
        ]
    ]
    if role in (Role.STAFF, Role.ADMIN):
        rows.append([("▸ ʀᴇᴠɪᴇᴡ ʀᴇǫᴜᴇsᴛs", cb("staff", "requests", 0)),
                     ("▸ ᴅᴏᴡɴʟᴏᴀᴅs ǫᴜᴇᴜᴇ", cb("queue", "view", 0))])
    if role is Role.ADMIN:
        rows.append([("◈ ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", cb("admin", "home"))])
    return keyboard(*rows)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return keyboard(
        [("▸ ǫᴜᴇᴜᴇ", cb("queue", "view", 0)), ("▸ ᴀɴᴀʟʏᴛɪᴄs", cb("admin", "analytics"))],
        [("▸ sᴛᴀꜰꜰ", cb("admin", "staff")), ("▸ ʙᴏᴛs", cb("admin", "bots"))],
        [("▸ sᴇᴛᴛɪɴɢs", cb("settings", "home")), ("▸ sᴛᴏʀᴀɢᴇ", cb("admin", "storage"))],
        [("▸ ᴀᴘᴘʀᴏᴠᴀʟs", cb("approve", "panel")), ("▸ ʙʀᴏᴀᴅᴄᴀsᴛ", cb("admin", "broadcast"))],
    )
