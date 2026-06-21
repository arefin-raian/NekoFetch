"""Distribution bot — Pyrogram client factory for a generated, public-facing bot.

Each distribution bot is a searchable content library bound (optionally) to a single
title. It presents banner → synopsis → seasons → resolution → language → episodes,
and serves season packages via the distribution service.

The handler set is intentionally minimal here; the full anime-bot interface and
season-package delivery are implemented in the distribution service + handlers
(task: Distribution bot generation + multi-bot manager).
"""

from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from nekofetch.core.container import Container
from nekofetch.infrastructure.database.postgres.models import DistributionBot


def build_distribution_bot(
    container: Container, record: DistributionBot, token: str
) -> Client:
    client = Client(
        name=f"nf-dist-{record.id}",
        api_id=container.env.telegram_api_id,
        api_hash=container.env.telegram_api_hash,
        bot_token=token,
        workdir=str(container.env.session_path),
    )
    client.container = container          # type: ignore[attr-defined]
    client.bot_record = record            # type: ignore[attr-defined]

    localizer = container.localizer

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        # Placeholder welcome; replaced by the rich anime-bot interface.
        await message.reply(
            f"**{record.name}**\n{localizer.get('welcome_subtitle')}"
        )

    return client
