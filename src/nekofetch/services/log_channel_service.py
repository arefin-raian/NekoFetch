"""Log channel service.

Posts every notable event to one configurable Telegram channel and maintains two pinned,
auto-updated messages: a live stats dashboard and a published-catalog index (both edited
in place rather than reposted).

``event()`` is called from across the app at lifecycle points (requests, queue, downloads,
processing, publishing, deliveries, admin actions). It is fire-and-forget and never raises
into the caller — logging must not break the operation it describes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from nekofetch.core.constants import ARROW, DIAMOND_FILLED, TRIANGLE
from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger

log = get_logger(__name__)

_PIN_DASHBOARD = "nf:logpin:dashboard"
_PIN_CATALOG = "nf:logpin:catalog"

# Category glyphs for quick visual scanning in the channel.
_CATEGORY_GLYPH = {
    "request": "◆",
    "queue": "▸",
    "download": "▰",
    "processing": "◈",
    "publish": "✦",
    "delivery": "➜",
    "admin": "◇",
    "bot": "◆",
    "error": "✕",
    "system": "│",
}


class LogChannelService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self.cfg = container.config.log_channel

    @property
    def _client(self):
        return getattr(self._c, "admin_client", None)

    def _active(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.channel_id != 0 and self._client is not None)

    def _wants(self, category: str) -> bool:
        return "all" in self.cfg.events or category in self.cfg.events

    async def event(self, category: str, action: str, **fields) -> None:
        """Post a single event line. Never raises into the caller."""
        if not self._active() or not self._wants(category):
            return
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            glyph = _CATEGORY_GLYPH.get(category, DIAMOND_FILLED)
            detail = "  ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
            text = f"{glyph} `{ts}`  **{category}.{action}**" + (f"\n{detail}" if detail else "")
            await self._client.send_message(self.cfg.channel_id, text)
        except Exception as exc:  # noqa: BLE001
            log.warning("logchannel.event.failed", error=str(exc))

    # ── pinned messages ──
    async def ensure_pins(self) -> None:
        """Create + pin the dashboard and catalog messages on startup if missing."""
        if not self._active():
            return
        if self.cfg.pinned_dashboard:
            await self._ensure_pin(_PIN_DASHBOARD, "Initializing dashboard…")
        if self.cfg.pinned_catalog:
            await self._ensure_pin(_PIN_CATALOG, "Initializing catalog…")
        await self.refresh()

    async def _ensure_pin(self, redis_key: str, placeholder: str) -> None:
        try:
            existing = await self._c.redis.get(redis_key) if self._c.redis else None
            if existing:
                return
            msg = await self._client.send_message(self.cfg.channel_id, placeholder)
            try:
                await self._client.pin_chat_message(self.cfg.channel_id, msg.id, disable_notification=True)
            except Exception:  # noqa: BLE001 - pin may be restricted; keep the message anyway
                pass
            if self._c.redis:
                await self._c.redis.set(redis_key, msg.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("logchannel.pin.failed", key=redis_key, error=str(exc))

    async def refresh(self) -> None:
        """Scheduler job: re-render both pinned messages in place."""
        if not self._active():
            return
        if self.cfg.pinned_dashboard:
            await self._edit_pin(_PIN_DASHBOARD, await self._dashboard_text())
        if self.cfg.pinned_catalog:
            await self._edit_pin(_PIN_CATALOG, await self._catalog_text())

    async def _edit_pin(self, redis_key: str, text: str) -> None:
        try:
            mid = await self._c.redis.get(redis_key) if self._c.redis else None
            if not mid:
                return
            await self._client.edit_message_text(self.cfg.channel_id, int(mid), text)
        except Exception as exc:  # noqa: BLE001 - "message not modified" etc.
            if "MESSAGE_NOT_MODIFIED" not in str(exc):
                log.debug("logchannel.editpin.skip", key=redis_key, error=str(exc))

    async def _dashboard_text(self) -> str:
        from nekofetch.services.analytics_service import AnalyticsService

        s = await AnalyticsService(self._c).dashboard()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        top = "\n".join(
            f"  {i + 1}. {t} ({c})" for i, (t, c) in enumerate(s.most_requested)
        ) or "  —"
        return (
            f"**◈ NekoFetch — Live Dashboard**\n_updated {ts}_\n\n"
            f"{DIAMOND_FILLED} Total Users: {s.total_users}\n"
            f"{DIAMOND_FILLED} Total Downloads: {s.total_downloads}\n"
            f"{DIAMOND_FILLED} Queue Size: {s.queue_size}\n"
            f"{DIAMOND_FILLED} Failed Tasks: {s.failed_tasks}\n"
            f"{DIAMOND_FILLED} Published: {s.published}\n\n"
            f"{TRIANGLE} Most Requested:\n{top}"
        )

    async def _catalog_text(self) -> str:
        from nekofetch.services.distribution_service import DistributionService

        dist = DistributionService(self._c)
        titles = await dist.published_titles()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        if not titles:
            return f"**◈ NekoFetch — Catalog**\n_updated {ts}_\n\nNo published content yet."
        lines = []
        for doc_id, title in titles[:40]:
            seasons = await dist.seasons_for(doc_id)
            season_str = ", ".join(f"S{s}" for s in seasons) or "—"
            lines.append(f"{DIAMOND_FILLED} {title}  {ARROW}  {season_str}")
        return f"**◈ NekoFetch — Catalog** ({len(titles)})\n_updated {ts}_\n\n" + "\n".join(lines)
