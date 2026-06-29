"""Regression guards for localization reload and log-channel self-healing."""

from __future__ import annotations

import asyncio
import json
import types

from nekofetch.localization.i18n import Localizer
from nekofetch.services.log_channel_service import _SECTIONS, LogChannelService

# ── localization: an edit on disk is picked up after reload() ──────────────────

def test_localizer_reload_picks_up_edits(tmp_path):
    f = tmp_path / "en.json"
    f.write_text(json.dumps({"greeting": "Hello"}), encoding="utf-8")
    loc = Localizer(tmp_path, default="en")
    assert loc.get("greeting") == "Hello"
    f.write_text(json.dumps({"greeting": "Hi there"}), encoding="utf-8")
    loc.reload()
    assert loc.get("greeting") == "Hi there"  # propagates without a new instance


def test_localizer_auto_reloads_on_disk_change(tmp_path):
    import os
    import time

    f = tmp_path / "en.json"
    f.write_text(json.dumps({"greeting": "Hello"}), encoding="utf-8")
    loc = Localizer(tmp_path, default="en")
    assert loc.get("greeting") == "Hello"
    # Edit on disk and bump mtime unambiguously into the future.
    f.write_text(json.dumps({"greeting": "Hi there"}), encoding="utf-8")
    future = time.time() + 10
    os.utime(f, (future, future))
    loc._next_check = 0.0  # bypass the stat throttle for the test
    assert loc.get("greeting") == "Hi there"  # auto-reloaded — no explicit reload()


# ── log channel self-heal: fakes for client + redis ───────────────────────────

class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v):
        self.store[k] = str(v)

    async def delete(self, k):
        self.store.pop(k, None)


class _Msg:
    def __init__(self, mid, kind="text"):
        self.id = mid
        self.empty = False
        self.kind = kind
        self.pinned_message = None
        # Conversation-section fields the discussion handler reads off a human msg.
        self.text = None
        self.caption = None
        self.author_signature = None
        self.from_user = None


class _FakeClient:
    def __init__(self):
        self.mid = 0
        self.live: dict[int, _Msg] = {}
        self.pinned: set[int] = set()
        self.order: list[tuple[str, int]] = []  # (kind, id) in send order

    async def send_message(self, chat_id, text, **kw):
        self.mid += 1
        m = _Msg(self.mid, "text")
        self.live[self.mid] = m
        self.order.append(("text", self.mid))
        return m

    async def send_sticker(self, chat_id, sticker):
        self.mid += 1
        m = _Msg(self.mid, "sticker")
        self.live[self.mid] = m
        self.order.append(("sticker", self.mid))
        return m

    async def edit_message_text(self, chat_id, mid, text, **kw):
        if mid not in self.live:
            raise RuntimeError("MESSAGE_ID_INVALID")

    async def get_messages(self, chat_id, mid):
        return self.live.get(mid)

    async def pin_chat_message(self, chat_id, mid, **kw):
        self.pinned.add(mid)

    async def delete_messages(self, chat_id, mid):
        self.live.pop(mid, None)


def _svc():
    client = _FakeClient()
    redis = _FakeRedis()
    cfg = types.SimpleNamespace(
        enabled=True, channel_id=-100123, sections=True, reserved_slots=2,
        notices_lines=12, refresh_seconds=60, events=["all"],
        divider_sticker_id="STICKER", pinned_dashboard=True, pinned_catalog=True,
        cover_image="", discussion_ttl_minutes=5,
    )
    container = types.SimpleNamespace(
        config=types.SimpleNamespace(log_channel=cfg), redis=redis,
        admin_client=client,
    )
    svc = LogChannelService(container)
    # Stub the data-driven refresh so the test stays offline.
    async def _noop():
        return None
    svc.refresh = _noop  # type: ignore[assignment]
    return svc, client, redis


def test_build_layout_order_and_pins():
    svc, client, _ = _svc()
    asyncio.run(svc.ensure_sections())
    kinds = [k for k, _ in client.order]
    # Layout: intro text, then a divider before each section. No closing divider —
    # the catalog + its reserved slots are the final messages so request cards
    # append into clean space.
    assert kinds[0] == "text"          # the intro comes first (no cover configured)
    assert kinds[1] == "sticker"       # divider before the first section
    assert kinds[-1] == "text"         # ends on the catalog's reserved slots, not a sticker
    assert kinds.count("sticker") == len(_SECTIONS)  # one divider per section, none trailing
    # Pinned sections (dashboard, catalog) actually got pinned.
    assert len(client.pinned) == sum(1 for s in _SECTIONS if s.pinned)
    # Text msgs = intro + one per section + reserved slots on growth sections.
    growth = sum(1 for s in _SECTIONS if s.growth)
    assert kinds.count("text") == 1 + len(_SECTIONS) + growth * 2


def test_self_heal_after_wipe():
    svc, client, redis = _svc()
    asyncio.run(svc.ensure_sections())
    first_ids = dict(client.live)
    # Simulate a full manual wipe of the channel.
    client.live.clear()
    client.order.clear()
    client.pinned.clear()
    # Restart: ensure_sections must detect the gap and rebuild everything in order.
    asyncio.run(svc.ensure_sections())
    kinds = [k for k, _ in client.order]
    assert kinds.count("sticker") == len(_SECTIONS)
    assert len(client.pinned) == sum(1 for s in _SECTIONS if s.pinned)
    assert set(client.live) != set(first_ids)  # genuinely new messages


def _human_msg(mid, text, name="Rai Yan"):
    m = _Msg(mid)
    m.text = text
    m.author_signature = name
    return m


def test_discussion_reformats_and_sweeps_after_ttl():
    svc, client, redis = _svc()
    asyncio.run(svc.ensure_sections())
    # Two human text messages: each original is deleted and reposted as a signed
    # line; the first opens the thread with a divider.
    asyncio.run(svc.note_discussion(_human_msg(5001, "hi")))
    asyncio.run(svc.note_discussion(_human_msg(5002, "yo")))
    assert 5001 not in client.live and 5002 not in client.live  # originals removed
    thread = json.loads(redis.store["nf:logcc:discussion"])
    assert thread["ids"]                       # reposted line (+divider) ids tracked
    assert 5001 not in thread["ids"]           # raw ids are not what we track now
    # Fresh thread is NOT swept.
    asyncio.run(svc.sweep_discussions())
    assert "nf:logcc:discussion" in redis.store
    # Backdate beyond the TTL → swept away entirely.
    thread["last"] = 0
    redis.store["nf:logcc:discussion"] = json.dumps(thread)
    asyncio.run(svc.sweep_discussions())
    assert "nf:logcc:discussion" not in redis.store
