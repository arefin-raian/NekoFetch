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
_K_REQ_MARKERS = "nf:logcc:reqmarkers"  # {code: {divider, card}} — per-request card+divider ids
_K_SIGNED = "nf:logcc:signed"          # set once the channel's "Sign Messages" is enabled
_K_STUCK = "nf:stuck:{code}"           # per-request stuck-episode state for the attention card
_K_HANDLING = "nf:logcc:handling:{code}"  # a request currently being assigned (drops off the inbox)


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
        from nekofetch.core.timefmt import now_label
        return now_label()

    # ── low-level message helpers ───────────────────────────────────────────────
    async def _send(self, text: str, **kw):
        return await self._client.send_message(
            self.cfg.channel_id, text, parse_mode=ParseMode.HTML, **kw
        )

    async def _edit(self, mid: int, text: str, reply_markup=None) -> None:
        await self._client.edit_message_text(
            self.cfg.channel_id, mid, _truncate_html(text, MESSAGE_LIMIT),
            parse_mode=ParseMode.HTML, reply_markup=reply_markup,
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

    async def _edit_or_resend(self, name: str, text: str, reply_markup=None) -> None:
        """Edit a section in place; if its message is gone, resend and re-store."""
        mid = await self._section_id(name)
        if mid is not None:
            try:
                await self._edit(mid, text, reply_markup=reply_markup)
                return
            except Exception as exc:
                if "MESSAGE_NOT_MODIFIED" in str(exc):
                    return
                log.debug("logcc.edit.failed", section=name, error=str(exc))
        msg = await self._send(text, reply_markup=reply_markup)
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
           ones), every section preceded by a divider.

        The catalog (last section) and its reserved slots are the final layout
        messages — no trailing divider — so freshly posted request cards append
        into clean space. Every non-section message id is tracked so a later wipe
        removes it too.
        """
        extras: list[int] = []  # cover/intro, dividers — everything but sections

        # Post the whole structured layout UNSIGNED — bot-managed system messages
        # shouldn't carry an author signature (it just clutters them). Sign Messages
        # is restored at the end so human staff chatter is attributed normally.
        await self._set_signatures(False)

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

        await self._c.redis.set(_K_STICKERS, json.dumps(extras))
        await self._c.redis.set(_K_CHANNEL, self.cfg.channel_id)
        # All sections posted — restore Sign Messages so staff conversation is
        # attributed again (and keep the flag consistent for ensure_signatures()).
        await self._set_signatures(True)
        if self._c.redis:
            await self._c.redis.set(_K_SIGNED, "1")

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
        # NOTE: 'active' is intentionally absent — it's owned by refresh_active()
        # (the fast lane), which also attaches the per-job Stop keyboard. Editing it
        # here without that markup would strip the buttons every full refresh.
        for name, builder in (
            ("dashboard", self._build_dashboard),
            ("pending", self._build_pending),
            ("completed", self._build_completed),
            ("catalog", self._build_catalog),
        ):
            try:
                await self._edit_or_resend(name, await builder(ts))
            except Exception as exc:
                log.debug("logcc.refresh.section.failed", section=name, error=str(exc))
        # Keep the active panel + its Stop controls fresh on the full tick too.
        await self.refresh_active()
        # Tidy idle human discussion as part of the periodic tick.
        await self.sweep_discussions()

    async def refresh_active(self) -> None:
        """Fast-lane refresh of just the active-tasks panel.

        Re-renders only the live downloads/processing section so the progress bar
        tracks reality within seconds, without paying for a full rebuild of the
        dashboard/catalog/completed panels each tick. Identical content is a no-op
        (Telegram MESSAGE_NOT_MODIFIED is swallowed)."""
        if not self._sectioned():
            return
        try:
            from nekofetch.services.queue_service import QueueService

            qrows = await QueueService(self._c).dashboard(limit=8)
            text = S.active_section([self._active_row_dict(r) for r in qrows], self._ts())
            await self._edit_or_resend("active", text, reply_markup=self._active_keyboard(qrows))
        except Exception as exc:
            log.debug("logcc.refresh_active.failed", error=str(exc))
        # Keep the persistent request inbox current on the fast lane too, so it
        # re-appears within seconds after a card is consumed by source assignment.
        await self.refresh_inbox()

    @staticmethod
    def _active_row_dict(r) -> dict:
        return {
            "title": r.anime_title, "stage": r.stage or r.status, "progress": r.progress,
            "speed_bps": r.speed_bps, "eta_seconds": r.eta_seconds, "episode": r.current_episode,
            "season": r.season, "ep_index": r.episode_index, "ep_total": r.total_episodes,
            "done": r.downloaded_bytes, "total": r.total_bytes, "label": r.label,
            "resolution": r.resolution, "audio": r.audio,
        }

    def _active_keyboard(self, qrows):
        """Per in-flight job: a Stop button (skip just the current episode) and a
        Cancel button (terminate the whole series and remove it from the list)."""
        rows = []
        for r in qrows:
            running = str(getattr(r, "status", "")).lower() == "running" or (r.progress or 0) < 100
            if running:
                rows.append([
                    InlineKeyboardButton(t(M.CC_BTN_STOP_EP, ep=r.current_episode or "?"),
                                         callback_data=cb("staff", "jstop", r.job_id)),
                    InlineKeyboardButton(t(M.CC_BTN_CANCEL_JOB),
                                         callback_data=cb("staff", "jcancel", r.job_id)),
                ])
        return InlineKeyboardMarkup(rows) if rows else None

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
            {
                "title": r.anime_title,
                "stage": r.stage or r.status,
                "progress": r.progress,
                "speed_bps": r.speed_bps,
                "eta_seconds": r.eta_seconds,
                "episode": r.current_episode,
                "season": r.season,
                "ep_index": r.episode_index,
                "ep_total": r.total_episodes,
                "done": r.downloaded_bytes,
                "total": r.total_bytes,
                "label": r.label,
                "resolution": r.resolution,
                "audio": r.audio,
            }
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
        """A new request arrived — refresh the single persistent request inbox rather
        than posting a fresh card per request (the request is already in the DB)."""
        await self.refresh_inbox()

    # ── request being actively assigned (so it drops off the inbox head) ─────────
    async def mark_handling(self, code: str) -> None:
        if self._c.redis:
            await self._c.redis.set(_K_HANDLING.format(code=code), "1", ex=3600)
        await self.refresh_inbox()

    async def clear_handling(self, code: str) -> None:
        if self._c.redis:
            await self._c.redis.delete(_K_HANDLING.format(code=code))
        await self.refresh_inbox()

    async def _is_handling(self, code: str) -> bool:
        return bool(self._c.redis and await self._c.redis.get(_K_HANDLING.format(code=code)))

    async def refresh_inbox(self) -> None:
        """Maintain ONE persistent request-inbox message at the foot of the channel.

        It shows the oldest UNASSIGNED request as an actionable source-selection card,
        or a clean 'no pending requests' status when the queue is empty — edited in
        place, never a new message per request. A request being actively assigned is
        skipped (so the inbox advances to the next), and the rest stay visible in the
        PENDING section.
        """
        if not self._active():
            return
        try:
            from nekofetch.services.request_service import RequestService

            pending = await RequestService(self._c).list_pending(limit=20)
            head = None
            for r in pending:
                if not await self._is_handling(r.code):
                    head = r
                    break
            if head is not None:
                def _btn(key: str, *parts: str) -> InlineKeyboardButton:
                    return InlineKeyboardButton(t(key), callback_data=cb(*parts))

                kb = InlineKeyboardMarkup([
                    [_btn(M.ADMIN_BTN_TELEGRAM, "staff", "rsource", head.code, "telegram"),
                     _btn(M.ADMIN_BTN_WEBSITE, "staff", "rsource", head.code, "website"),
                     _btn(M.ADMIN_BTN_TORRENT, "staff", "rsource", head.code, "torrent")],
                    [_btn(M.ADMIN_BTN_REJECT, "staff", "rreject", head.code)],
                ])
                text = S.request_card(head.code, head.anime_title,
                                      str(head.user_id), str(getattr(head, "scope", "") or ""))
                await self._edit_or_resend("inbox", text, reply_markup=kb)
            else:
                await self._edit_or_resend("inbox", S.inbox_idle(), reply_markup=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("logcc.inbox.failed", error=str(exc))

    async def _remember_request_markers(
        self, code: str, divider_id: int | None, card_id: int
    ) -> None:
        if not self._c.redis:
            return
        raw = await self._c.redis.get(_K_REQ_MARKERS)
        markers = json.loads(raw) if raw else {}
        markers[code] = {"divider": divider_id, "card": card_id}
        await self._c.redis.set(_K_REQ_MARKERS, json.dumps(markers))

    async def clear_request_markers(self, code: str, *, delete_divider: bool = True) -> None:
        """Stop tracking a request card once it's consumed.

        The card message itself is removed by the screen that replaces it, so we
        only ever need to deal with the divider here:

        * source assigned (``delete_divider=False``) — keep the divider. It becomes
          the section separator that sits in front of the follow-up fetched card,
          so the layout stays ``Border → Card → Border → Card`` without the fetched
          card ever appearing naked.
        * rejected (``delete_divider=True``) — the request is gone entirely, so its
          divider goes with it, leaving no orphan sticker.
        """
        if not (self._active() and self._c.redis):
            return
        raw = await self._c.redis.get(_K_REQ_MARKERS)
        markers = json.loads(raw) if raw else {}
        entry = markers.pop(code, None)
        if entry is None:
            return
        if delete_divider and entry.get("divider"):
            try:
                await self._client.delete_messages(self.cfg.channel_id, entry["divider"])
            except Exception:
                pass
        await self._c.redis.set(_K_REQ_MARKERS, json.dumps(markers))

    async def post_attention_card(
        self, *, code: str, title: str, failures: list, source: str,
        alt_source: str | None,
    ) -> None:
        """Post an actionable card for episodes that couldn't be downloaded, with
        Retry / Switch-source / Provide-file controls. ``failures`` is a list of
        ``{"ep": n, "audio": "subbed"|"dubbed"|...}`` so the card names exactly which
        version failed. The stuck-state is persisted for the action handlers."""
        if not self._active():
            return
        episodes = sorted({f["ep"] for f in failures})
        audio_kinds = sorted({f["audio"] for f in failures if f.get("audio")})
        if self._c.redis:
            await self._c.redis.set(_K_STUCK.format(code=code), json.dumps({
                "episodes": episodes, "title": title, "source": source,
                "audio_kinds": audio_kinds, "alt_source": alt_source,
            }), ex=86400)

        def _btn(key: str, *parts: str) -> InlineKeyboardButton:
            return InlineKeyboardButton(t(key), callback_data=cb(*parts))

        buttons = [[_btn(M.CC_BTN_RETRY_EPS, "staff", "aretry", code)]]
        if alt_source:
            buttons.append([_btn(M.CC_BTN_SWITCH_SRC, "staff", "aswitch", code)])
        buttons.append([_btn(M.CC_BTN_PROVIDE, "staff", "aprovide", code)])
        try:
            await self._send(S.attention_card(code, title, failures),
                             reply_markup=InlineKeyboardMarkup(buttons))
            if self._c.redis:
                await self._c.redis.set(_K_LAST_BOT, "1")
        except Exception as exc:  # noqa: BLE001
            log.warning("logcc.attention_card.failed", error=str(exc))

    async def post_failure_card(
        self, *, code: str, title: str, stage: str, error: str
    ) -> None:
        """Post a prominent, standalone failure card so a failed download/processing
        job is impossible to miss — distinct from the easy-to-overlook rolling
        activity line, which we still emit alongside it."""
        if not self._active():
            return
        try:
            await self._send(S.failure_card(code or "—", title or "—", stage, (error or "")[:300]))
            if self._c.redis:
                await self._c.redis.set(_K_LAST_BOT, "1")
        except Exception as exc:
            log.warning("logcc.failure_card.failed", error=str(exc))

    # ── human discussion: keep staff chatter out of the bot-managed flow ─────────
    async def _set_signatures(self, enabled: bool) -> None:
        """Toggle the channel's 'Sign Messages' setting (best-effort)."""
        if not self._active():
            return
        try:
            from pyrogram.raw.functions.channels import ToggleSignatures

            peer = await self._client.resolve_peer(self.cfg.channel_id)
            await self._client.invoke(
                ToggleSignatures(channel=peer, signatures_enabled=enabled)
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("logcc.signatures.toggle.failed", enabled=enabled, error=str(exc))

    async def ensure_signatures(self) -> None:
        """Enable 'Sign Messages' once, so human posts carry an author signature we
        can attribute by name. Best-effort and idempotent — recorded either way so a
        failure doesn't retry every message."""
        if not (self._active() and self._c.redis):
            return
        if await self._c.redis.get(_K_SIGNED):
            return
        await self._set_signatures(True)
        await self._c.redis.set(_K_SIGNED, "1")

    @staticmethod
    def _discussion_name(message) -> str:
        """Best display name for a human poster: the channel author signature when
        present, else the sender's name, else a generic label."""
        sig = getattr(message, "author_signature", None)
        if sig:
            return sig
        user = getattr(message, "from_user", None)
        if user:
            full = " ".join(p for p in (user.first_name, user.last_name) if p)
            return full or getattr(user, "username", None) or "Staff"
        return "Staff"

    async def note_discussion(self, message) -> None:
        """Fold a human message into the conversation section.

        The raw message is deleted and reposted as a signed line —
        ``[<b>Name</b>]: text`` — with a divider sticker opening a fresh thread (or
        whenever it follows bot-managed content). Non-text messages are left as-is
        and merely tracked. The thread is swept after ``discussion_ttl_minutes`` idle.
        """
        if not self._sectioned():
            return
        import time

        try:
            await self.ensure_signatures()
            raw = await self._c.redis.get(_K_DISCUSSION)
            thread = json.loads(raw) if raw else {"ids": [], "last": 0}
            text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()

            if not text:
                # Non-text human content (sticker/photo): keep it, just track for sweep.
                thread["ids"].append(message.id)
                thread["last"] = int(time.time())
                await self._c.redis.set(_K_DISCUSSION, json.dumps(thread))
                return

            name = self._discussion_name(message)
            opening = not thread["ids"] or bool(await self._c.redis.get(_K_LAST_BOT))
            # Replace the raw message with the formatted conversation line.
            try:
                await self._client.delete_messages(self.cfg.channel_id, message.id)
            except Exception:
                pass
            if opening:
                div = await self._post_divider()
                if div:
                    thread["ids"].append(div)
                await self._c.redis.delete(_K_LAST_BOT)
            posted = await self._send(S.conversation_line(name, text))
            thread["ids"].append(posted.id)
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
