from __future__ import annotations

from datetime import datetime, timezone

from pyrogram.enums import ParseMode

from nekofetch.core.constants import ARROW, DIAMOND_FILLED, TRIANGLE
from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.ui.typography import bq, heading

log = get_logger(__name__)

_PIN_DASHBOARD = "nf:logpin:dashboard"
_PIN_CATALOG = "nf:logpin:catalog"

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
        if not self._active() or not self._wants(category):
            return
        try:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            glyph = _CATEGORY_GLYPH.get(category, DIAMOND_FILLED)
            detail_parts = []
            for k, v in fields.items():
                if v is not None:
                    detail_parts.append(f"<b>{k}:</b> <code>{v}</code>")
            detail = "<br/>".join(detail_parts) if detail_parts else ""
            text = (
                f"<b>{glyph} {category}.{action}</b>\n"
                f"<code>{ts}</code>"
            )
            if detail:
                text += f"\n{bq(detail)}"
            await self._client.send_message(
                self.cfg.channel_id, text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:
            log.warning("logchannel.event.failed", error=str(exc))

    async def ensure_pins(self) -> None:
        if not self._active():
            return
        await self._clean_stale_pins()
        if self.cfg.pinned_dashboard:
            await self._ensure_pin(_PIN_DASHBOARD, bq(heading("📊 ᴅᴀsʜʙᴏᴀʀᴅ") + "\n\nɪɴɪᴛɪᴀʟɪᴢɪɴɢ…"))
        if self.cfg.pinned_catalog:
            await self._ensure_pin(_PIN_CATALOG, bq(heading("📚 ᴄᴀᴛᴀʟᴏɢ") + "\n\nɪɴɪᴛɪᴀʟɪᴢɪɴɢ…"))
        await self.refresh()

    async def _clean_stale_pins(self) -> None:
        if not self._c.redis:
            return
        stored_channel = await self._c.redis.get("nf:logpin:channel_id")
        if stored_channel is not None and int(stored_channel) != self.cfg.channel_id:
            old_cid = int(stored_channel)
            for rk in (_PIN_DASHBOARD, _PIN_CATALOG):
                mid = await self._c.redis.get(rk)
                if mid:
                    try:
                        await self._client.delete_messages(old_cid, int(mid))
                    except Exception:
                        pass
                    await self._c.redis.delete(rk)
        await self._c.redis.set("nf:logpin:channel_id", self.cfg.channel_id)

    async def _ensure_pin(self, redis_key: str, placeholder: str) -> None:
        try:
            existing = await self._c.redis.get(redis_key) if self._c.redis else None
            if existing:
                return
            msg = await self._client.send_message(
                self.cfg.channel_id, placeholder, parse_mode=ParseMode.HTML
            )
            try:
                await self._client.pin_chat_message(
                    self.cfg.channel_id, msg.id, disable_notification=True
                )
            except Exception:
                pass
            if self._c.redis:
                await self._c.redis.set(redis_key, msg.id)
        except Exception as exc:
            log.warning("logchannel.pin.failed", key=redis_key, error=str(exc))

    async def refresh(self) -> None:
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
            await self._client.edit_message_text(
                self.cfg.channel_id, int(mid), text, parse_mode=ParseMode.HTML
            )
        except Exception as exc:
            if "MESSAGE_NOT_MODIFIED" not in str(exc):
                log.debug("logchannel.editpin.skip", key=redis_key, error=str(exc))

    async def _dashboard_text(self) -> str:
        from nekofetch.services.analytics_service import AnalyticsService

        s = await AnalyticsService(self._c).dashboard()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        top = "\n".join(
            f"  {i + 1}. <b>{t}</b> ({c})" for i, (t, c) in enumerate(s.most_requested)
        ) or "  —"
        return bq(
            heading("📊 ɴᴇᴋᴏꜰᴇᴛᴄʜ — ʟɪᴠᴇ ᴅᴀsʜʙᴏᴀʀᴅ")
            + f"\n<code>{ts}</code>\n\n"
            + f"{DIAMOND_FILLED} ᴛᴏᴛᴀʟ ᴜsᴇʀs: <code>{s.total_users}</code>\n"
            + f"{DIAMOND_FILLED} ᴛᴏᴛᴀʟ ᴅᴏᴡɴʟᴏᴀᴅs: <code>{s.total_downloads}</code>\n"
            + f"{DIAMOND_FILLED} ǫᴜᴇᴜᴇ sɪᴢᴇ: <code>{s.queue_size}</code>\n"
            + f"{DIAMOND_FILLED} ꜰᴀɪʟᴇᴅ ᴛᴀsᴋs: <code>{s.failed_tasks}</code>\n"
            + f"{DIAMOND_FILLED} ᴘᴜʙʟɪsʜᴇᴅ: <code>{s.published}</code>\n\n"
            + f"{TRIANGLE} <b>ᴍᴏsᴛ ʀᴇǫᴜᴇsᴛᴇᴅ</b>:\n{top}"
        )

    async def _catalog_text(self) -> str:
        from nekofetch.services.distribution_service import DistributionService

        dist = DistributionService(self._c)
        titles = await dist.published_titles()
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        if not titles:
            return bq(
                heading("📚 ᴄᴀᴛᴀʟᴏɢ")
                + f"\n<code>{ts}</code>\n\nɴᴏ ᴘᴜʙʟɪsʜᴇᴅ ᴄᴏɴᴛᴇɴᴛ ʏᴇᴛ."
            )
        lines = []
        for doc_id, title in titles[:40]:
            seasons = await dist.seasons_for(doc_id)
            season_str = ", ".join(f"S{s}" for s in seasons) or "—"
            lines.append(f"{DIAMOND_FILLED} {title}  {ARROW}  {season_str}")
        return bq(
            heading(f"📚 ᴄᴀᴛᴀʟᴏɢ ({len(titles)})")
            + f"\n<code>{ts}</code>\n\n"
            + "\n".join(lines)
        )
