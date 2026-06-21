"""Shortlink provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ShortlinkProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def create_short_link(self, target_url: str) -> str:
        """Return a shortened/monetized URL that ultimately redirects to ``target_url``."""

    async def close(self) -> None:  # pragma: no cover - optional
        return None


class NullShortlinkProvider(ShortlinkProvider):
    """No-op provider: returns the target unchanged (used when shortlink is disabled)."""

    name = "null"

    async def create_short_link(self, target_url: str) -> str:
        return target_url
