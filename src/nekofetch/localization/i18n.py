"""Localization loader.

All user-facing text lives in ``resources/language/<code>.json`` — never hardcoded.
Editing a message is a JSON edit, no code change. Missing keys fall back to the
default language, then to the key itself (so gaps are visible, not crashes).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

# How often (seconds) to stat the catalog files for live edits. Cheap enough to do
# off the hot path but throttled so a busy bot doesn't stat on every single lookup.
_RELOAD_THROTTLE = 2.0


class _SafeFormat(dict):
    """Format mapping that leaves unknown placeholders intact instead of raising.

    Lets en.json be edited freely: a template that references a ``{placeholder}``
    the call site doesn't supply renders the literal ``{placeholder}`` rather than
    crashing the whole message with a ``KeyError``.
    """

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Localizer:
    def __init__(self, directory: str | Path, default: str = "en") -> None:
        self.directory = Path(directory)
        self.default = default
        self._catalogs: dict[str, dict[str, str]] = {}
        self._loaded_mtime: float = 0.0    # newest catalog mtime seen at last load
        self._next_check: float = 0.0      # monotonic gate for maybe_reload()
        self.reload()

    def _newest_mtime(self) -> float:
        """Newest modification time across all catalog files (0 if none/missing)."""
        if not self.directory.exists():
            return 0.0
        newest = 0.0
        for file in self.directory.glob("*.json"):
            try:
                newest = max(newest, file.stat().st_mtime)
            except OSError:
                continue
        return newest

    def reload(self) -> None:
        self._catalogs.clear()
        if not self.directory.exists():
            return
        for file in self.directory.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            self._catalogs[file.stem] = {
                k: v for k, v in data.items() if not k.startswith("_")
            }
        self._loaded_mtime = self._newest_mtime()

    def maybe_reload(self) -> None:
        """Reload the catalogs if any file changed on disk since the last load.

        Throttled to once per ``_RELOAD_THROTTLE`` seconds so an edit to en.json
        shows up within a couple of seconds with no ``/reload`` or restart, while
        keeping per-lookup cost negligible on a busy bot.
        """
        now = time.monotonic()
        if now < self._next_check:
            return
        self._next_check = now + _RELOAD_THROTTLE
        if self._newest_mtime() > self._loaded_mtime:
            self.reload()

    def get(self, key: str, lang: str | None = None, **kwargs) -> str:
        self.maybe_reload()
        lang = lang or self.default
        catalog = self._catalogs.get(lang) or self._catalogs.get(self.default) or {}
        template = catalog.get(key)
        if template is None and lang != self.default:
            template = self._catalogs.get(self.default, {}).get(key)
        if template is None:
            return key
        if not kwargs:
            return template
        try:
            return template.format_map(_SafeFormat(kwargs))
        except (ValueError, IndexError):
            # Malformed template (e.g. a stray brace) — show it raw rather than crash.
            return template

    @property
    def languages(self) -> list[str]:
        return list(self._catalogs)
