"""Regression guards for confident source title matching."""

from __future__ import annotations

import asyncio

from nekofetch.sources._match import find_verified_match, strong_title_match
from nekofetch.sources.base import AnimeStub


def test_strong_match_accepts_identical():
    assert strong_title_match("Naruto", "Naruto") is True
    assert strong_title_match("Hellsing Ultimate", "Hellsing Ultimate") is True


def test_strong_match_rejects_season_superset():
    # The whole point: never let season 1 collapse into a sequel.
    assert strong_title_match("Naruto", "Naruto: Shippuuden") is False
    assert strong_title_match("Naruto", "Road of Naruto") is False  # recap


class _FakeSource:
    def __init__(self, results_by_query):
        self._r = results_by_query

    async def search(self, query):
        return self._r.get(query, [])


def _stub(t):
    return AnimeStub(source_ref=t, title=t)


def test_find_verified_matches_via_romaji():
    # English search returns junk; Romaji search returns the real show.
    src = _FakeSource({
        "Attack on Titan": [_stub("Attack on Titan: Junior High")],   # wrong (spin-off)
        "Shingeki no Kyojin": [_stub("Shingeki no Kyojin")],          # right
    })
    stub = asyncio.run(find_verified_match(src, ["Attack on Titan", "Shingeki no Kyojin"]))
    assert stub is not None and stub.title == "Shingeki no Kyojin"


def test_find_verified_returns_none_when_nothing_matches():
    src = _FakeSource({"Naruto": [_stub("Boruto"), _stub("Road of Naruto")]})
    assert asyncio.run(find_verified_match(src, ["Naruto"])) is None
