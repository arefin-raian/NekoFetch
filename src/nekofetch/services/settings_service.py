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
        """Apply persisted overrides onto the live config (called at startup).

        These come from the in-bot Settings panel and **shadow config.yaml**. We
        log every shadowed field so a "config.yaml edit isn't taking effect" is
        immediately explained by the log (the override wins until it's cleared).
        """
        overrides = await self._load_doc()
        applied: list[str] = []
        for section, values in overrides.items():
            target = getattr(self._c.config, section, None)
            if target is None:
                continue
            for field, val in values.items():
                if hasattr(target, field):
                    setattr(target, field, val)
                    applied.append(f"{section}.{field}={val!r}")
        if applied:
            log.warning("settings.overrides.shadowing_config_yaml", overrides=applied)

    async def clear_overrides(self) -> int:
        """Drop all runtime overrides so config.yaml becomes authoritative again.

        Returns the number of fields cleared. Note: values already applied to the
        live config persist until the next restart re-reads config.yaml.
        """
        doc = await self._load_doc()
        count = sum(len(v) for v in doc.values() if isinstance(v, dict))
        await self._save_doc({})
        log.info("settings.overrides.cleared", fields=count)
        return count

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

    # ── generic config introspection (drives the Settings control center) ──────
    # Sections that hold secrets/connection ids we never expose in-chat.
    _HIDDEN_FIELDS = {"channel_id", "owner_id", "api_token", "linkvertise_user_id",
                      "end_sticker_id", "start_sticker_id", "force_subscribe_channels"}

    def section(self, name: str):
        return getattr(self._c.config, name, None)

    def section_fields(self, name: str) -> list[tuple[str, object, str]]:
        """Return ``(field, value, kind)`` for each editable field in a section.

        ``kind`` is ``"bool"`` for toggles or ``"value"`` for free text/number,
        used by the panel to decide between a switch and an edit prompt. Hidden
        and complex (list/dict) fields are skipped.
        """
        target = self.section(name)
        if target is None:
            return []
        out: list[tuple[str, object, str]] = []
        for field, value in target.model_dump().items():
            if field in self._HIDDEN_FIELDS:
                continue
            if isinstance(value, bool):
                out.append((field, value, "bool"))
            elif isinstance(value, (str, int, float)):
                out.append((field, value, "value"))
            # lists/dicts are skipped — edited via dedicated flows, not free text
        return out

    async def toggle(self, section: str, field: str) -> bool:
        current = bool(getattr(self.section(section), field))
        await self.set_value(section, field, not current)
        return not current

    async def set_typed(self, section: str, field: str, raw: str) -> object:
        """Coerce ``raw`` text to the field's current type, then persist it."""
        current = getattr(self.section(section), field, None)
        if isinstance(current, bool):
            value: object = raw.strip().lower() in ("1", "true", "yes", "on")
        elif isinstance(current, int):
            value = int(raw.strip())
        elif isinstance(current, float):
            value = float(raw.strip())
        else:
            value = raw.strip()
        await self.set_value(section, field, value)
        return value
