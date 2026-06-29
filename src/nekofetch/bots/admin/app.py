"""Admin / management bot — Pyrogram client factory.

The container is attached to the client so handlers can reach services without global
state. Handlers are registered by feature module to keep things modular.
"""

from __future__ import annotations

from pyrogram import Client

from nekofetch.core.container import Container


def build_admin_bot(container: Container) -> Client:
    env = container.env
    client = Client(
        name="nekofetch-admin",
        api_id=env.telegram_api_id,
        api_hash=env.telegram_api_hash,
        bot_token=env.admin_bot_token,
        workdir=str(env.session_path),
        plugins=None,
        # This client uploads the processed packs to the storage channel. Pyrogram
        # defaults to a single in-flight file transmission, which makes large
        # uploads crawl; raising it lets chunks transfer in parallel.
        max_concurrent_transmissions=4,
    )
    # Make shared services reachable from handlers.
    client.container = container  # type: ignore[attr-defined]

    from nekofetch.bots.admin.handlers import register_all

    register_all(client, container)
    return client
