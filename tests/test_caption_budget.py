"""Regression guards: a franchise card can never exceed Telegram's caption limit,
and send_screen always splits/truncates overflow instead of crashing."""

from __future__ import annotations

import asyncio

from nekofetch.ui import screens
from nekofetch.ui.screens import CAPTION_LIMIT, Screen, confirm_franchise, visible_len


def _huge_media() -> dict:
    return {
        "english": "Attack on Titan", "romaji": "Shingeki no Kyojin", "year": 2013,
        "format": "TV", "status": "FINISHED", "score": 8.5, "studio": "WIT STUDIO",
        "genres": ["Action", "Drama", "Fantasy", "Mystery", "Horror"],
        "synopsis": "Humans were nearly exterminated by titans. " * 60,
        "synopsis_url": "https://www.themoviedb.org/tv/1429",
        "franchise_episodes": 94, "franchise_seasons": 4, "franchise_movies": 3,
        "franchise_ovas": 3, "franchise_onas": 0, "franchise_specials": 2,
        "relations": [
            {"relation": "SEQUEL", "format": "TV", "episodes": 12,
             "titles": [f"Attack on Titan Extended Edition Part {i}"]}
            for i in range(2, 30)
        ],
        "anilist_id": "16498",
    }


def test_confirm_card_within_caption_budget():
    scr = confirm_franchise(_huge_media(), backdrop_path="https://img/bd.jpg")
    assert visible_len(scr.caption) <= CAPTION_LIMIT


def test_confirm_card_has_read_more_when_truncated():
    scr = confirm_franchise(_huge_media(), backdrop_path="https://img/bd.jpg")
    urls = [getattr(b, "url", None) for row in scr.keyboard.inline_keyboard for b in row]
    assert any(urls), "a Read More url button should appear when the synopsis is clipped"


class _FakeMessage:
    def __init__(self, mid=1):
        self.id = mid


class _FakeClient:
    """Records calls so we can assert send_screen never exceeds caption limits."""

    def __init__(self):
        self.photos: list[dict] = []
        self.messages: list[dict] = []
        self._mid = 100

    async def send_photo(self, chat_id, photo=None, caption=None, **kw):
        # The real Telegram raises MEDIA_CAPTION_TOO_LONG past 1024 — emulate it.
        assert visible_len(caption or "") <= 1024, "caption exceeded Telegram limit"
        self._mid += 1
        self.photos.append({"caption": caption})
        return _FakeMessage(self._mid)

    async def send_message(self, chat_id, text, **kw):
        assert visible_len(text or "") <= 4096
        self._mid += 1
        self.messages.append({"text": text})
        return _FakeMessage(self._mid)


def test_send_screen_splits_overflow_to_followup():
    client = _FakeClient()
    over = Screen(caption="A" * 3000, image="https://img/x.jpg")
    asyncio.run(screens.send_screen(client, 123, over))
    # Photo sent without the giant caption; full body moved to a follow-up message.
    assert client.photos and not client.photos[0]["caption"]
    assert client.messages, "overflow should land in a follow-up text message"
