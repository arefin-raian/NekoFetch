"""Localization loader.

All user-facing text lives in ``resources/language/<code>.json`` — never hardcoded.
Editing a message is a JSON edit, no code change. Missing keys fall back to the
default language, then to the key itself (so gaps are visible, not crashes).
"""

from __future__ import annotations

import json
from pathlib import Path


class Localizer:
    def __init__(self, directory: str | Path, default: str = "en") -> None:
        self.directory = Path(directory)
        self.default = default
        self._catalogs: dict[str, dict[str, str]] = {}
        self.reload()

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

    def get(self, key: str, lang: str | None = None, **kwargs) -> str:
        lang = lang or self.default
        catalog = self._catalogs.get(lang) or self._catalogs.get(self.default) or {}
        template = catalog.get(key)
        if template is None and lang != self.default:
            template = self._catalogs.get(self.default, {}).get(key)
        if template is None:
            return key
        return template.format(**kwargs) if kwargs else template

    @property
    def languages(self) -> list[str]:
        return list(self._catalogs)
