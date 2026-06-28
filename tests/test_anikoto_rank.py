"""Regression guard: AniKoto results are ranked by title relevance, not views.

Found live — searching "Naruto" returned the viral recap "Road of Naruto" first
because the site sorts by views. We re-rank so the exact title wins.
"""

from __future__ import annotations

from nekofetch.sources.anikoto import _rank_by_title
from nekofetch.sources.base import AnimeStub


def _stub(title):
    return AnimeStub(source_ref=title.lower().replace(" ", "-"), title=title)


def test_exact_title_beats_viral_recap():
    results = [_stub("Road of Naruto"), _stub("Naruto"), _stub("Naruto: Shippuden")]
    ranked = _rank_by_title("Naruto", results)
    assert ranked[0].title == "Naruto"          # exact match wins, not the recap


def test_word_overlap_orders_partial_matches():
    results = [_stub("Bleach"), _stub("Attack on Titan Final Season"),
               _stub("Attack on Titan")]
    ranked = _rank_by_title("Attack on Titan", results)
    assert ranked[0].title == "Attack on Titan"  # exact over the longer variant
    assert ranked[-1].title == "Bleach"          # unrelated sinks to the bottom
