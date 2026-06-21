"""Shortlink provider selection (by ``shortlink.provider`` in config)."""

from __future__ import annotations

from nekofetch.core.config import ShortlinkConfig
from nekofetch.providers.shortlink.base import NullShortlinkProvider, ShortlinkProvider


def build_shortlink_provider(cfg: ShortlinkConfig) -> ShortlinkProvider:
    if not cfg.enabled:
        return NullShortlinkProvider()
    if cfg.provider == "linkvertise":
        from nekofetch.providers.shortlink.linkvertise import LinkvertiseProvider

        return LinkvertiseProvider(user_id=cfg.linkvertise_user_id)
    # Unknown provider name -> no-op (returns target unchanged).
    return NullShortlinkProvider()
