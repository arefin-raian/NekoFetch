"""Source registry — discovery and instantiation of authorized sources.

Only names listed in ``config.sources.enabled`` are activated. A pirate-site plugin,
even if present on disk, would still require explicit enabling — and none ship.
"""

from __future__ import annotations

from nekofetch.core.exceptions import ConfigError
from nekofetch.sources.base import AnimeSource


class SourceRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, type[AnimeSource]] = {}
        self._instances: dict[str, AnimeSource] = {}

    def register(self, source_cls: type[AnimeSource]) -> None:
        self._factories[source_cls.name] = source_cls

    def activate(self, enabled: list[str], **kwargs) -> None:
        """Instantiate the enabled sources. Extra kwargs are passed to constructors."""
        for name in enabled:
            cls = self._factories.get(name)
            if cls is None:
                raise ConfigError(f"Unknown or unavailable source: {name!r}")
            self._instances[name] = cls(**kwargs.get(name, {}))

    def get(self, name: str) -> AnimeSource:
        if name not in self._instances:
            raise ConfigError(f"Source not active: {name!r}")
        return self._instances[name]

    def available(self) -> list[str]:
        return list(self._instances)


def build_default_registry() -> SourceRegistry:
    """Register all built-in authorized sources."""
    from nekofetch.sources.anikoto import AnikotoSource
    from nekofetch.sources.kickassanime import KickAssAnimeSource
    from nekofetch.sources.local import LocalFileSource
    from nekofetch.sources.nyaa import NyaaSource
    from nekofetch.sources.telegram.source import TelegramSource

    registry = SourceRegistry()
    registry.register(LocalFileSource)
    registry.register(KickAssAnimeSource)
    registry.register(AnikotoSource)
    registry.register(NyaaSource)
    registry.register(TelegramSource)
    return registry
