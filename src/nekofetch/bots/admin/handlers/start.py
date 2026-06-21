"""/start — the premium welcome screen.

Demonstrates the house style: elegant typography, design glyphs, no emoji spam, and
message editing for the staged loading animation.
"""

from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message

from nekofetch.bots.admin.keyboards import welcome_keyboard
from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.domain.enums import Role
from nekofetch.localization.i18n import Localizer
from nekofetch.ui import progress


def _welcome_text(localizer: Localizer, role: Role, lang: str = "en") -> str:
    g = localizer.get
    features = [
        g("welcome_feature_requests", lang),
        g("welcome_feature_tracking", lang),
        g("welcome_feature_notifications", lang),
        g("welcome_feature_resolution", lang),
        g("welcome_feature_subtitles", lang),
    ]
    feature_lines = "\n".join(f"{DIAMOND_FILLED} {f}" for f in features)
    role_label = g(f"role_{role.value}", lang)
    return (
        f"**{g('welcome_title', lang)}**\n"
        f"{g('welcome_subtitle', lang)}\n\n"
        f"{g('welcome_features_header', lang)}:\n"
        f"{feature_lines}\n\n"
        f"{g('welcome_access_level', lang)}:\n"
        f"{role_label}"
    )


def register(client: Client, container: Container) -> None:
    localizer = container.localizer

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        user = getattr(message, "nf_user", None)
        role = Role(user.role) if user else Role.USER
        lang = user.language if user else "en"

        # Staged loading animation via message editing (premium feel).
        msg = await message.reply(progress.labeled(localizer.get("status_searching_db", lang), 20))
        for label_key, pct in (
            ("status_searching_db", 50),
            ("status_retrieving_seasons", 80),
            ("status_complete", 100),
        ):
            await asyncio.sleep(0.4)
            await msg.edit_text(progress.labeled(localizer.get(label_key, lang), pct))

        await asyncio.sleep(0.3)
        await msg.edit_text(
            _welcome_text(localizer, role, lang),
            reply_markup=welcome_keyboard(localizer, role, lang),
        )
