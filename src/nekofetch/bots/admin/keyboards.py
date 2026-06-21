"""Admin/user inline keyboards."""

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
        rows.append([("▸ Review Requests", cb("staff", "requests", 0)),
                     ("▸ Downloads Queue", cb("queue", "view", 0))])
    if role is Role.ADMIN:
        rows.append([("◈ Admin Panel", cb("admin", "home"))])
    return keyboard(*rows)


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return keyboard(
        [("▸ Queue", cb("queue", "view", 0)), ("▸ Analytics", cb("admin", "analytics"))],
        [("▸ Staff", cb("admin", "staff")), ("▸ Bots", cb("admin", "bots"))],
        [("▸ Settings", cb("settings", "home")), ("▸ Storage", cb("admin", "storage"))],
    )
