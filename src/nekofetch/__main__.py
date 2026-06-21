"""NekoFetch entry point.

Boots the container (DB/cache connections), configures logging, and starts the
bot manager (admin bot + any registered distribution bots) on a single event loop.
"""

from __future__ import annotations

import asyncio
import signal

from nekofetch.core.config import get_env
from nekofetch.core.container import Container
from nekofetch.core.logging import configure_logging, get_logger


async def _run() -> None:
    env = get_env()
    configure_logging(level=env.log_level, json=env.log_json)
    log = get_logger("nekofetch")

    container = Container.create()
    await container.startup()
    log.info("nekofetch.starting", version=_version())

    # Bot manager is wired in the bots layer; imported lazily so core stays standalone.
    from nekofetch.bots.manager import BotManager

    manager = BotManager(container)
    stop = asyncio.Event()

    def _signal_handler() -> None:
        log.info("nekofetch.stopping")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:  # Windows
            pass

    try:
        await manager.start()
        await stop.wait()
    finally:
        await manager.stop()
        await container.shutdown()


def _version() -> str:
    from nekofetch import __version__

    return __version__


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
