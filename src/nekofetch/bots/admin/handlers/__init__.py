"""Admin-bot handler registration.

Each feature module exposes ``register(client, container)``; ``register_all`` wires
them in order. The auth middleware runs first so every handler sees a resolved user.
"""

from __future__ import annotations

from pyrogram import Client

from nekofetch.core.container import Container


def register_all(client: Client, container: Container) -> None:
    from nekofetch.bots.admin.handlers import (
        admin_tools,
        approvals,
        bots_admin,
        commands,
        requests,
        review,
        settings,
        staff_admin,
        start,
        storage_admin,
    )
    from nekofetch.bots.middleware import install_auth_middleware

    install_auth_middleware(client, container)
    # Registered before the stateful text routers so /help and /cancel win the match.
    commands.register(client, container)
    start.register(client, container)
    requests.register(client, container)
    review.register(client, container)
    settings.register(client, container)
    approvals.register(client, container)
    bots_admin.register(client, container)
    storage_admin.register(client, container)
    admin_tools.register(client, container)
    staff_admin.register(client, container)
