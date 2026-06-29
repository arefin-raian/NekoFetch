"""Regression guard: dual-audio acquisition can cross-source.

The key new capability — when one site has the sub and another has the dub,
``_best_variant`` finds each from the right source so both languages are delivered.
"""

from __future__ import annotations

import asyncio
import types

from nekofetch.domain.enums import AudioType
from nekofetch.services.download_service import DownloadWorker
from nekofetch.sources.base import Episode, VideoVariant


class _Src:
    def __init__(self, name, variants_by_ref):
        self.name = name
        self._v = variants_by_ref

    async def get_variants(self, ref):
        return self._v.get(ref, [])


def _worker():
    c = types.SimpleNamespace(
        config=types.SimpleNamespace(downloads=types.SimpleNamespace(concurrent_downloads=2))
    )
    return DownloadWorker(c)


def test_best_variant_picks_audio_cross_source():
    w = _worker()
    sub = VideoVariant(source_ref="s", resolution="1080p", audio=AudioType.SUBBED)
    dub = VideoVariant(source_ref="d", resolution="1080p", audio=AudioType.DUBBED)
    src_sub = _Src("anikoto", {"a/ep1": [sub]})          # only offers sub
    src_dub = _Src("kickassanime", {"b/ep1": [dub]})     # only offers dub
    chain = [
        (src_sub, [Episode(source_ref="a/ep1", season=1, number=1)]),
        (src_dub, [Episode(source_ref="b/ep1", season=1, number=1)]),
    ]
    got_sub = asyncio.run(w._best_variant(chain, 1, AudioType.SUBBED))
    got_dub = asyncio.run(w._best_variant(chain, 1, AudioType.DUBBED))
    assert got_sub[0].name == "anikoto" and got_sub[1].audio == AudioType.SUBBED
    # dub came from the OTHER source — cross-source acquisition works.
    assert got_dub[0].name == "kickassanime" and got_dub[1].audio == AudioType.DUBBED


def test_best_variant_none_when_audio_missing():
    w = _worker()
    sub = VideoVariant(source_ref="s", resolution="1080p", audio=AudioType.SUBBED)
    src = _Src("anikoto", {"a/ep1": [sub]})
    chain = [(src, [Episode(source_ref="a/ep1", season=1, number=1)])]
    assert asyncio.run(w._best_variant(chain, 1, AudioType.DUBBED)) is None
    # also None when the episode number isn't present
    assert asyncio.run(w._best_variant(chain, 99, AudioType.SUBBED)) is None
