"""Distribution-bot auto-branding.

When a bot is bound to a title, set its **name**, **about**, and **descriptions** from the
title's facts (qualities, languages, Japanese title). This uses the bot's own client (a bot
can only edit its own profile).

Note: a bot's **profile photo/video** can only be set via @BotFather, not the Bot API, so
that stays a manual step. Name/about/description are best-effort and version-tolerant — if a
given Pyrogram build doesn't expose a method, it's logged and skipped, not fatal.
"""

from __future__ import annotations

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)

# Candidate Pyrogram/Kurigram method names per field (first that exists wins).
_NAME_METHODS = ("set_bot_name",)
_DESC_METHODS = ("set_bot_info_description", "set_bot_description")
_SHORT_METHODS = ("set_bot_info_short_description", "set_bot_short_description")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def apply_bot_branding(container: Container, client, anime_doc_id: str) -> None:
    from nekofetch.services.main_channel_service import MainChannelService

    facts = await MainChannelService(container).gather_facts(anime_doc_id)

    # e.g. "Naruto Shippuden | 480p 720p 1080p | English & Japanese"
    qualities = facts.qualities.replace(", ", " ")
    name = _truncate(f"{facts.title} | {qualities} | {facts.languages}", 64)
    short = _truncate(f"{facts.title} — {facts.languages} — {facts.qualities}", 120)
    description = _truncate(
        facts.overview if facts.overview and facts.overview != "—"
        else f"{facts.title}\nQuality: {facts.qualities}\nLanguage: {facts.languages}",
        512,
    )

    await _try(client, _NAME_METHODS, name)
    await _try(client, _SHORT_METHODS, short)
    await _try(client, _DESC_METHODS, description)
    log.info("bot.branding.applied", anime=anime_doc_id, name=name)


async def _try(client, method_names, value: str) -> None:
    for method in method_names:
        fn = getattr(client, method, None)
        if fn is None:
            continue
        try:
            await fn(value)
            return
        except Exception as exc:  # noqa: BLE001 - version/permission differences
            log.debug("bot.branding.method_failed", method=method, error=str(exc))
            return
    log.debug("bot.branding.unsupported", methods=str(method_names))
