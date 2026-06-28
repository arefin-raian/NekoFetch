"""Regression guard: franchise_totals walks the WHOLE relation graph (not just
immediate children) and excludes ALTERNATIVE adaptations."""

from __future__ import annotations

import asyncio

from nekofetch.sources.telegram.anilist import AnilistClient

# A miniature graph: a 3-season TV chain + a movie + an OVA, plus an ALTERNATIVE
# adaptation that must NOT be counted. Each node lists its immediate edges only —
# exactly how AniList returns them — so the test proves recursive expansion.
_GRAPH = {
    1: {"format": "TV", "episodes": 25,
        "edges": [("SEQUEL", 2), ("ALTERNATIVE", 99), ("SPIN_OFF", 50)]},
    2: {"format": "TV", "episodes": 12, "edges": [("SEQUEL", 3), ("SIDE_STORY", 10)]},
    3: {"format": "TV", "episodes": 10, "edges": [("SIDE_STORY", 11)]},
    10: {"format": "MOVIE", "episodes": 1, "edges": []},
    11: {"format": "OVA", "episodes": 4, "edges": []},
    50: {"format": "TV", "episodes": 24, "edges": []},  # SPIN_OFF TV — NOT a season
    99: {"format": "TV", "episodes": 13, "edges": []},  # ALTERNATIVE — excluded
}


class _FakeAnilist(AnilistClient):
    async def _post(self, query, variables):  # type: ignore[override]
        ids = variables.get("ids", [])
        media = []
        for i in ids:
            node = _GRAPH.get(i)
            if not node:
                continue
            media.append({
                "id": i, "type": "ANIME", "format": node["format"],
                "episodes": node["episodes"],
                "relations": {"edges": [
                    {"relationType": rt,
                     "node": {"id": nid, "type": "ANIME",
                              "format": _GRAPH[nid]["format"],
                              "episodes": _GRAPH[nid]["episodes"]}}
                    for rt, nid in node["edges"]
                ]},
            })
        return {"Page": {"media": media}}


def test_franchise_totals_traverses_full_graph():
    cli = _FakeAnilist()
    totals = asyncio.run(cli.franchise_totals(1))
    # Seasons 1+2+3 reached recursively (immediate children would give only 1+2).
    assert totals.seasons == 3
    assert totals.episodes == 25 + 12 + 10
    assert totals.movies == 1
    assert totals.ovas == 1
    assert totals.nodes == 6  # ALTERNATIVE (99) excluded; spin-off (50) included


def test_spinoff_tv_is_not_a_season():
    cli = _FakeAnilist()
    totals = asyncio.run(cli.franchise_totals(1))
    # Node 50 is a TV series reached only via SPIN_OFF — it must be a spin-off,
    # never a season, and its 24 episodes must NOT be added to the season total.
    assert totals.spin_offs == 1
    assert totals.seasons == 3
    assert totals.episodes == 47  # 25+12+10, NOT +24


def test_franchise_totals_excludes_alternative_adaptation():
    cli = _FakeAnilist()
    totals = asyncio.run(cli.franchise_totals(1))
    # The ALTERNATIVE TV (id 99, 13 eps) must not inflate the count: 3 seasons /
    # 47 eps, not 4 / 60. Following ALTERNATIVE would change both.
    assert totals.seasons == 3
    assert totals.episodes == 47
