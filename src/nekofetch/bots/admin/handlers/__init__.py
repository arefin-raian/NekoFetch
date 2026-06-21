"""Admin-bot handler registration.

Each feature module exposes ``register(client, container)``; ``register_all`` wires
them in order. The auth middleware runs first so every handler sees a resolved user.
"""

from __future__ import annotations

from pyrogram import Client

from nekofetch.core.container import Container


def register_all(client: Client, container: Container) -> None:
    from nekofetch.bots.admin.handlers import approvals, requests, settings, start
    from nekofetch.bots.middleware import install_auth_middleware

    install_auth_middleware(client, container)
    start.register(client, container)
    requests.register(client, container)
    settings.register(client, container)
    approvals.register(client, container)
