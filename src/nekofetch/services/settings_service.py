"""Runtime settings service.

Bridges the in-Telegram settings panel to durable storage. Feature toggles and branding
edits are persisted to the Mongo ``settings`` collection and applied live by mutating the
in-memory ``AppConfig`` (pydantic models are mutable), so most changes take effect without
a restart. On startup, ``apply_overrides`` re-applies persisted overrides over config.yaml.
"""

from __future__ import annotations

from typing import Any

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)

_OVERRIDES_KEY = "runtime_overrides"


class SettingsService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def _load_doc(self) -> dict:
        if self._c.collections is None:
            return {}
        doc = await self._c.collections.settings.find_one({"key": _OVERRIDES_KEY})
        return (doc or {}).get("value", {})

    async def _save_doc(self, value: dict) -> None:
        if self._c.collections is None:
            return
        await self._c.collections.settings.update_one(
            {"key": _OVERRIDES_KEY}, {"$set": {"value": value}}, upsert=True
        )

    async def apply_overrides(self) -> None:
        """Apply persisted overrides onto the live config (called at startup)."""
        overrides = await self._load_doc()
        for section, values in overrides.items():
            target = getattr(self._c.config, section, None)
            if target is None:
                continue
            for field, val in values.items():
                if hasattr(target, field):
                    setattr(target, field, val)
        if overrides:
            log.info("settings.overrides.applied", sections=list(overrides))

    async def set_value(self, section: str, field: str, value: Any) -> None:
        target = getattr(self._c.config, section, None)
        if target is None or not hasattr(target, field):
            raise KeyError(f"{section}.{field}")
        setattr(target, field, value)  # live
        doc = await self._load_doc()
        doc.setdefault(section, {})[field] = value
        await self._save_doc(doc)
        log.info("settings.updated", section=section, field=field, value=value)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "admin", "setting_changed", section=section, field=field, value=value
        )

    async def toggle_feature(self, feature: str) -> bool:
        current = bool(getattr(self._c.config.features, feature))
        await self.set_value("features", feature, not current)
        return not current

    def feature_map(self) -> dict[str, bool]:
        return self._c.config.features.model_dump()
