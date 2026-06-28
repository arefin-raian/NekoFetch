"""Regression guards for dual-audio mergeability detection.

The key property: we decide whether sub and dub are the same cut from the HLS
manifest alone (summed #EXTINF), no video download — and reject different cuts.
"""

from __future__ import annotations

import asyncio

from nekofetch.sources._dualaudio import are_mergeable, playlist_duration

_MEDIA = (
    "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n"
    "#EXTINF:6.0,\nseg0.ts\n#EXTINF:6.0,\nseg1.ts\n#EXTINF:4.5,\nseg2.ts\n#EXT-X-ENDLIST\n"
)
_MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=1280x720\nmedia.m3u8\n"


class _Resp:
    def __init__(self, text):
        self.text = text


class _Http:
    def __init__(self, mapping):
        self.mapping = mapping

    async def get(self, url, headers=None):
        return _Resp(self.mapping[url])


def test_are_mergeable_same_cut():
    assert are_mergeable(1400.0, 1400.4) is True       # ~0.4s apart → same cut


def test_are_mergeable_different_cut():
    # The real Naruto case measured live: 1400.4 vs 1434.6 → 34s apart.
    assert are_mergeable(1400.4, 1434.6) is False
    assert are_mergeable(None, 1400.0) is False


def test_playlist_duration_sums_extinf():
    http = _Http({"http://x/media.m3u8": _MEDIA})
    d = asyncio.run(playlist_duration(http, "http://x/media.m3u8"))
    assert abs(d - 16.5) < 0.001


def test_playlist_duration_resolves_master():
    http = _Http({"http://x/master.m3u8": _MASTER, "http://x/media.m3u8": _MEDIA})
    d = asyncio.run(playlist_duration(http, "http://x/master.m3u8"))
    assert abs(d - 16.5) < 0.001
