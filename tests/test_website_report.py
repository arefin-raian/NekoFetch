"""Regression guards for the website source-comparison analysis."""

from __future__ import annotations

from nekofetch.services.website_report import _analyze, _ordered_tree
from nekofetch.sources.base import SourceCoverage


def _cov(source, total, sub, dub, available=True, approximate=False):
    return SourceCoverage(source=source, matched_title="x", source_ref="x",
                          total_episodes=total, sub_episodes=sub, dub_episodes=dub,
                          available=available, approximate=approximate)


def test_flags_incomplete_dub_variance():
    # The Naruto case: 220 subbed but only 3 dubbed on one source.
    ak = _cov("anikoto", 220, 220, 220, approximate=True)
    ka = _cov("kickassanime", 220, 220, 3)
    lines, recommended = _analyze(220, [ak, ka])
    blob = " ".join(lines).lower()
    assert "dub is incomplete" in blob
    assert "3 of 220" in blob


def test_flags_short_source_vs_anilist():
    short = _cov("kickassanime", 10, 10, 10)
    full = _cov("anikoto", 12, 12, 12)
    lines, recommended = _analyze(12, [short, full])
    blob = " ".join(lines).lower()
    assert "short of anilist" in blob          # 10 < 12 flagged
    assert recommended == "anikoto"            # the complete source wins


def test_unavailable_source_is_reported_not_recommended():
    ok = _cov("anikoto", 24, 24, 24)
    missing = _cov("kickassanime", 0, 0, 0, available=False)
    missing.note = "no match"
    lines, recommended = _analyze(24, [ok, missing])
    assert recommended == "anikoto"
    assert any("no usable match" in line.lower() for line in lines)


def test_tree_is_release_ordered():
    franchise = {
        "title": "Show", "format": "TV", "franchise_episodes": 12,
        "relations": [
            {"relation": "SEQUEL", "titles": ["Show 2"], "format": "TV", "episodes": 12},
            {"relation": "PREQUEL", "titles": ["Show 0"], "format": "TV", "episodes": 12},
        ],
    }
    tree = _ordered_tree(franchise)
    rels = [n["relation"] for n in tree]
    # Prequel before self before sequel — approximate release order.
    assert rels.index("PREQUEL") < rels.index("SELF") < rels.index("SEQUEL")
