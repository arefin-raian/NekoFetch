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
        rows.append([("▸ review requests", cb("staff", "requests", 0)),
                     ("▸ downloads queue", cb("queue", "view", 0))])
    if role is Role.ADMIN:
        rows.append([("◈ admin panel", cb("admin", "home"))])
    return keyboard(*rows)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return keyboard(
        [("▸ queue", cb("queue", "view", 0)), ("▸ analytics", cb("admin", "analytics"))],
        [("▸ staff", cb("admin", "staff")), ("▸ bots", cb("admin", "bots"))],
        [("▸ settings", cb("settings", "home")), ("▸ storage", cb("admin", "storage"))],
        [("▸ approvals", cb("approve", "panel")), ("▸ broadcast", cb("admin", "broadcast"))],
    )
