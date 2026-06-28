"""The log channel as an operational **control center**.

The channel is a fixed, ordered layout of persistent messages — a sticker
divider before each of: dashboard, pending, active, completed, activity stream,
catalog — every section edited in place rather than re-posted. Growth-prone
sections (pending / completed / catalog) trail a couple of reserved placeholder
messages for future overflow; static panels reserve none.

The layout is **self-healing**: on every startup we verify each section message
still exists. If the channel was wiped (or the target channel changed), the whole
layout is torn down and rebuilt in order, the pinned sections re-pinned, and
Telegram's "pinned message" service notices swept away so the channel stays clean.

Public surface kept stable for callers:
  * ``event(category, action, **fields)`` — feeds the rolling activity stream.
  * ``ensure_pins()`` / ``refresh()`` — startup self-heal + periodic refresh.
Plus control-center extras: ``post_request_card()`` and ``ask_clarification()``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.localization.messages import M, t
from nekofetch.ui import log_sections as S
from nekofetch.ui.components import cb
from nekofetch.ui.screens import MESSAGE_LIMIT, _truncate_html

log = get_logger(__name__)

# ── Redis keys ──
_K_CHANNEL = "nf:logcc:channel_id"
_K_NOTICES = "nf:logcc:notices"
_K_STICKERS = "nf:logcc:stickers"      # ordered list of layout message ids (cover/intro/dividers)
_K_LAST_BOT = "nf:logcc:last_bot"      # set when the last channel post was bot-managed
_K_DISCUSSION = "nf:logcc:discussion"  # {ids: [...], last: epoch} — temp human thread


def _sec_key(name: str) -> str:
    return f"nf:logcc:sec:{name}"


def _reserved_key(name: str) -> str:
    return f"nf:logcc:reserved:{name}"


@dataclass(frozen=True)
class _Section:
    name: str
    title_key: str
    pinned: bool = False
    # Growth-prone sections (lists that can outgrow one message) reserve extra
    # slots; static panels (dashboard/active/notices) reserve none.
    growth: bool = False


# Canonical section order. A sticker divider is posted before each one.
_SECTIONS: tuple[_Section, ...] = (
    _Section("dashboard", M.CC_DASHBOARD_TITLE, pinned=True),
    _Section("pending", M.CC_PENDING_TITLE, growth=True),
    _Section("active", M.CC_ACTIVE_TITLE),
    _Section("completed", M.CC_COMPLETED_TITLE, growth=True),
    _Section("notices", M.CC_NOTICES_TITLE),
    _Section("catalog", M.CC_CATALOG_TITLE, pinned=True, growth=True),
)


class LogChannelService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self.cfg = container.config.log_channel

    # ── availability ──────────────────────────────────────────────────────────
    @property
    def _client(self):
        return getattr(self._c, "admin_client", None)

    def _active(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.channel_id != 0 and self._client is not None)

    def _sectioned(self) -> bool:
        return bool(self._active() and self.cfg.sections and self._c.redis)

    def _wants(self, category: str) -> bool:
        return "all" in self.cfg.events or category in self.cfg.events

    @staticmethod
    def _ts() -> str:
        return datetime.now(UTC).strftime("%H:%M:%S UTC")

    # ── low-level message helpers ───────────────────────────────────────────────
    async def _send(self, text: str, **kw):
        return await self._client.send_message(
            self.cfg.channel_id, text, parse_mode=ParseMode.HTML, **kw
        )

    async def _edit(self, mid: int, text: str) -> None:
        await self._client.edit_message_text(
            self.cfg.channel_id, mid, _truncate_html(text, MESSAGE_LIMIT),
            parse_mode=ParseMode.HTML,
        )

    async def _section_id(self, name: str) -> int | None:
        raw = await self._c.redis.get(_sec_key(name)) if self._c.redis else None
        return int(raw) if raw else None

    async def _exists(self, mid: int) -> bool:
        """True if message ``mid`` still exists in the channel (not deleted)."""
        try:
            msg = await self._client.get_messages(self.cfg.channel_id, mid)
        except Exception:
            return False
        return bool(msg) and not getattr(msg, "empty", False)

    async def _edit_or_resend(self, name: str, text: str) -> None:
        """Edit a section in place; if its message is gone, resend and re-store."""
        mid = await self._section_id(name)
        if mid is not None:
            try:
                await self._edit(mid, text)
                return
            except Exception as exc:
                if "MESSAGE_NOT_MODIFIED" in str(exc):
                    return
                log.debug("logcc.edit.failed", section=name, error=str(exc))
        msg = await self._send(text)
        await self._c.redis.set(_sec_key(name), msg.id)

    # ── startup / self-healing ──────────────────────────────────────────────────
    async def ensure_pins(self) -> None:
        """Backwards-compatible entry point used by the bot manager at startup."""
        await self.ensure_sections()

    async def ensure_sections(self) -> None:
        """Bring the channel into a known-good state on every startup.

        If the configured channel changed, or *any* mandatory control message is
        missing (e.g. the channel was wiped by hand), tear everything down and
        rebuild the whole layout — stickers + sections + reserved slots — in order.
        Otherwise re-pin the pinned sections (in case a pin was lost) and refresh.
        """
        if not self._sectioned():
            return
        try:
            if await self._channel_changed() or not await self._layout_intact():
                await self._wipe_all()
                await self._build_layout()
            await self._reconcile_pins()
            await self.refresh()
        except Exception as exc:
            log.warning("logcc.ensure.failed", error=str(exc))

    async def _channel_changed(self) -> bool:
        stored = await self._c.redis.get(_K_CHANNEL)
        return stored is not None and int(stored) != self.cfg.channel_id

    async def _layout_intact(self) -> bool:
        """Every section message must still exist for the layout to be valid."""
        for sec in _SECTIONS:
            mid = await self._section_id(sec.name)
            if mid is None or not await self._exists(mid):
                return False
        return True

    async def _all_known_ids(self) -> list[int]:
        ids: list[int] = []
        for sec in _SECTIONS:
            mid = await self._section_id(sec.name)
            if mid:
                ids.append(mid)
            raw = await self._c.redis.get(_reserved_key(sec.name))
            ids += json.loads(raw) if raw else []
        raw = await self._c.redis.get(_K_STICKERS)
        ids += json.loads(raw) if raw else []
        return ids

    async def _wipe_all(self) -> None:
        """Delete every message we previously created and clear all stored ids."""
        for mid in await self._all_known_ids():
            try:
                await self._client.delete_messages(self.cfg.channel_id, mid)
            except Exception:
                pass
        keys = [_K_STICKERS, _K_NOTICES]
        for sec in _SECTIONS:
            keys += [_sec_key(sec.name), _reserved_key(sec.name)]
        for k in keys:
            await self._c.redis.delete(k)

    async def _build_layout(self) -> None:
        """Post the full layout, in order:

        1. a cover image (if configured),
        2. a formatted introduction explaining the channel,
        3. a divider, then each control section (reserved slots on growth-prone
           ones), every section preceded by a divider,
        4. a closing divider.

        Every non-section message id is tracked so a later wipe removes it too.
        """
        extras: list[int] = []  # cover/intro, dividers — everything but sections

        # Cover + description as a single message: the intro rides as the photo's
        # caption when a cover image is configured, else it's plain text.
        intro_text = t(M.CC_INTRO)
        if self.cfg.cover_image:
            try:
                cover = await self._client.send_photo(
                    self.cfg.channel_id, self.cfg.cover_image,
                    caption=_truncate_html(intro_text, 1000), parse_mode=ParseMode.HTML,
                )
                extras.append(cover.id)
            except Exception as exc:
                log.debug("logcc.cover.failed", error=str(exc))
                extras.append((await self._send(intro_text)).id)
        else:
            extras.append((await self._send(intro_text)).id)

        for sec in _SECTIONS:
            sid = await self._post_divider()
            if sid:
                extras.append(sid)
            placeholder = f"{t(sec.title_key)}\n{t(M.CC_INITIALIZING)}"
            msg = await self._send(placeholder)
            await self._c.redis.set(_sec_key(sec.name), msg.id)
            if sec.pinned:
                await self._pin_silently(msg.id)
            if sec.growth and self.cfg.reserved_slots > 0:
                reserved = []
                for i in range(self.cfg.reserved_slots):
                    r = await self._send(S.reserved_placeholder(i))
                    reserved.append(r.id)
                await self._c.redis.set(_reserved_key(sec.name), json.dumps(reserved))

        end = await self._post_divider()  # closing divider
        if end:
            extras.append(end)

        await self._c.redis.set(_K_STICKERS, json.dumps(extras))
        await self._c.redis.set(_K_CHANNEL, self.cfg.channel_id)

    async def _post_divider(self) -> int | None:
        if not self.cfg.divider_sticker_id:
            return None
        try:
            msg = await self._client.send_sticker(
                self.cfg.channel_id, self.cfg.divider_sticker_id
            )
            return msg.id
        except Exception as exc:
            log.debug("logcc.divider.failed", error=str(exc))
            return None

    async def _reconcile_pins(self) -> None:
        """Re-pin the pinned sections (idempotent) so a lost pin self-heals."""
        for sec in _SECTIONS:
            if not sec.pinned:
                continue
            mid = await self._section_id(sec.name)
            if mid:
                await self._pin_silently(mid)

    async def _pin_silently(self, message_id: int) -> None:
        """Pin a message and delete the "pinned this message" service notice
        Telegram auto-posts, so the channel stays clean."""
        try:
            await self._client.pin_chat_message(
                self.cfg.channel_id, message_id, disable_notification=True
            )
        except Exception:
            return
        # The service notice lands just after the pinned message; sweep a small
        # window to catch it regardless of the exact id assigned.
        for candidate in range(message_id + 1, message_id + 4):
            try:
                msg = await self._client.get_messages(self.cfg.channel_id, candidate)
                if msg and getattr(msg, "pinned_message", None) is not None:
                    await self._client.delete_messages(self.cfg.channel_id, candidate)
            except Exception:
                pass

    # ── periodic rebuild ────────────────────────────────────────────────────────
    async def refresh(self) -> None:
        if not self._sectioned():
            return
        ts = self._ts()
        for name, builder in (
            ("dashboard", self._build_dashboard),
            ("pending", self._build_pending),
            ("active", self._build_active),
            ("completed", self._build_completed),
            ("catalog", self._build_catalog),
        ):
            try:
                await self._edit_or_resend(name, await builder(ts))
            except Exception as exc:
                log.debug("logcc.refresh.section.failed", section=name, error=str(exc))
        # Tidy idle human discussion as part of the periodic tick.
        await self.sweep_discussions()

    async def _build_dashboard(self, ts: str) -> str:
        from nekofetch.services.analytics_service import AnalyticsService

        stats = await AnalyticsService(self._c).dashboard()
        return S.dashboard_section(stats, list(stats.most_requested), ts)

    async def _build_pending(self, ts: str) -> str:
        from nekofetch.services.request_service import RequestService

        reqs = await RequestService(self._c).list_pending(limit=10)
        rows = [{"code": r.code, "title": r.anime_title, "by": r.user_id} for r in reqs]
        return S.pending_section(rows, ts)

    async def _build_active(self, ts: str) -> str:
        from nekofetch.services.queue_service import QueueService

        qrows = await QueueService(self._c).dashboard(limit=8)
        rows = [
            {"title": r.anime_title, "stage": r.status, "progress": r.progress,
             "eta_seconds": r.eta_seconds}
            for r in qrows
        ]
        return S.active_section(rows, ts)

    async def _published_items(self, limit: int) -> list[dict]:
        from nekofetch.services.distribution_service import DistributionService

        dist = DistributionService(self._c)
        titles = await dist.published_titles(limit=limit)
        items = []
        for doc_id, title in titles:
            seasons = await dist.seasons_for(doc_id)
            items.append({"title": title,
                          "seasons": ", ".join(f"S{s}" for s in seasons) or "—"})
        return items

    async def _build_completed(self, ts: str) -> str:
        return S.completed_section(await self._published_items(6), ts)

    async def _build_catalog(self, ts: str) -> str:
        items = await self._published_items(40)
        return S.catalog_section([(it["title"], it["seasons"]) for it in items], ts)

    # ── activity stream ─────────────────────────────────────────────────────────
    async def event(self, category: str, action: str, **fields) -> None:
        if not self._active() or not self._wants(category):
            return
        ts = self._ts()
        line = S.notice_line(category, action, ts, fields)
        try:
            if self._sectioned():
                await self._push_notice(line)
            else:  # no sections — fall back to a standalone message per event
                await self._send(line)
        except Exception as exc:
            log.warning("logchannel.event.failed", error=str(exc))

    async def _push_notice(self, line: str) -> None:
        raw = await self._c.redis.get(_K_NOTICES)
        lines: list[str] = json.loads(raw) if raw else []
        lines.append(line)
        lines = lines[-self.cfg.notices_lines:]
        await self._c.redis.set(_K_NOTICES, json.dumps(lines))
        # The whole stream lives inside one expandable blockquote.
        body = S.notices_section(lines, self._ts())
        await self._edit_or_resend("notices", body)

    # ── control-center cards (standalone messages with actions) ─────────────────
    async def post_request_card(self, *, code: str, title: str, by: str, scope: str) -> None:
        """Post a new request with source-selection buttons (admins act inline)."""
        if not self._active():
            return
        def _btn(key: str, *parts: str) -> InlineKeyboardButton:
            return InlineKeyboardButton(t(key), callback_data=cb(*parts))

        kb = InlineKeyboardMarkup([
            [_btn(M.ADMIN_BTN_TELEGRAM, "staff", "rsource", code, "telegram"),
             _btn(M.ADMIN_BTN_WEBSITE, "staff", "rsource", code, "website"),
             _btn(M.ADMIN_BTN_TORRENT, "staff", "rsource", code, "torrent")],
            [_btn(M.ADMIN_BTN_REJECT, "staff", "rreject", code)],
        ])
        try:
            await self._send(S.request_card(code, title, by, scope), reply_markup=kb)
            await self._post_divider()  # separate each request card from the next
            await self._c.redis.set(_K_LAST_BOT, "1")  # next human msg gets a divider
        except Exception as exc:
            log.warning("logcc.request_card.failed", error=str(exc))

    # ── human discussion: keep staff chatter out of the bot-managed flow ─────────
    async def note_discussion(self, message_id: int) -> None:
        """Record a human message posted in the log channel as part of a temporary
        discussion thread. If it's the first message after bot content, drop a
        divider so the conversation reads as its own section. The thread is swept
        after ``discussion_ttl_minutes`` of inactivity."""
        if not self._sectioned():
            return
        import time

        try:
            if await self._c.redis.get(_K_LAST_BOT):
                await self._post_divider()
                await self._c.redis.delete(_K_LAST_BOT)
            raw = await self._c.redis.get(_K_DISCUSSION)
            thread = json.loads(raw) if raw else {"ids": [], "last": 0}
            thread["ids"].append(message_id)
            thread["last"] = int(time.time())
            await self._c.redis.set(_K_DISCUSSION, json.dumps(thread))
        except Exception as exc:
            log.debug("logcc.note_discussion.failed", error=str(exc))

    async def sweep_discussions(self) -> None:
        """Delete a human discussion thread once it's been idle past its TTL."""
        if not self._sectioned():
            return
        import time

        raw = await self._c.redis.get(_K_DISCUSSION)
        if not raw:
            return
        thread = json.loads(raw)
        idle = int(time.time()) - int(thread.get("last", 0))
        if idle < self.cfg.discussion_ttl_minutes * 60:
            return
        for mid in thread.get("ids", []):
            try:
                await self._client.delete_messages(self.cfg.channel_id, mid)
            except Exception:
                pass
        await self._c.redis.delete(_K_DISCUSSION)

    async def ask_clarification(self, *, code: str, title: str, question: str,
                                options: list[tuple[str, str]]) -> None:
        """Ask admins to resolve an ambiguity (e.g. 'Is this Season 1 or a Movie?').

        ``options`` are (label, callback_data) pairs handled by the admin bot.
        """
        if not self._active():
            return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=data)]
                                   for lbl, data in options])
        try:
            await self._send(S.ambiguity_card(code, title, question), reply_markup=kb)
        except Exception as exc:
            log.warning("logcc.clarify.failed", error=str(exc))
