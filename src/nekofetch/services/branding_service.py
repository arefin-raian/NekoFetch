"""Centralized branding engine.

Single source of truth for branding applied across file names, captions, metadata,
descriptions, and bot pages. Reads from config (and, later, runtime MongoDB overrides),
and is a no-op when ``branding.enabled`` is false.
"""

from __future__ import annotations

from nekofetch.core.config import BrandingConfig
from nekofetch.core.container import Container
from nekofetch.ui import templates


class BrandingService:
    def __init__(self, container: Container) -> None:
        self._c = container

    @property
    def cfg(self) -> BrandingConfig:
        return self._c.config.branding

    @property
    def enabled(self) -> bool:
        return self.cfg.enabled

    @property
    def group(self) -> str:
        return self.cfg.channel_name if self.enabled else ""

    def caption(self, body: str) -> str:
        """Append the configured footer to a caption/description."""
        if not self.enabled or not self.cfg.footer_text:
            return body
        return f"{body}\n\n{self.cfg.footer_text}"

    def metadata_fields(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        out = {}
        if self.cfg.metadata_author:
            out["author"] = self.cfg.metadata_author
        if self.cfg.metadata_comment:
            out["comment"] = self.cfg.metadata_comment
        return out

    def apply_template(self, template: str, **context) -> str:
        """Render a template with branding variables auto-injected."""
        return templates.render(
            template,
            group=self.group,
            channel=self.cfg.channel_name if self.enabled else "",
            website=self.cfg.website,
            **context,
        )
