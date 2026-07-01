"""Unit tests for BotContentService — pure content-building methods.

Tests focus on the deterministic, pure-logic methods that transform metadata
and pack data into the rendered post formats. Methods that touch external
services (DB, AniList, TMDB) are tested through their pure consumers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nekofetch.domain.enums import AudioType
from nekofetch.services.bot_content import BotContentService


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_service() -> BotContentService:
    """Create a BotContentService with a minimal mock container."""
    container = MagicMock()
    container.pg_sessionmaker = MagicMock()
    return BotContentService(container)


def _pack(
    *,
    season: int = 1,
    resolution: str = "1080p",
    audio: AudioType = AudioType.DUAL_AUDIO,
    episode_from: int = 1,
    episode_to: int = 12,
    file_count: int = 12,
    anime_doc_id: str = "test-anime",
) -> MagicMock:
    p = MagicMock()
    p.season = season
    p.resolution = resolution
    p.audio = audio
    p.episode_from = episode_from
    p.episode_to = episode_to
    p.file_count = file_count
    p.anime_doc_id = anime_doc_id
    p.enabled = True
    return p


# ── _build_watch_guide ───────────────────────────────────────────────────────


class TestBuildWatchGuide:
    def test_empty_packs_returns_none(self):
        svc = _make_service()
        meta = {"title": "Naruto"}
        assert svc._build_watch_guide(meta, []) is None

    def test_single_season(self):
        svc = _make_service()
        meta = {"title": "Naruto"}
        packs = [
            _pack(season=1, resolution="1080p", episode_to=12),
            _pack(season=1, resolution="720p", episode_to=12),
        ]
        result = svc._build_watch_guide(meta, packs)
        assert result is not None
        assert "Season 01" in result
        assert "1080p" in result
        assert "720p" in result
        assert "12" in result or "12 episodes" in result.lower()

    def test_multi_season(self):
        svc = _make_service()
        meta = {"title": "Attack on Titan"}
        packs = [
            _pack(season=1, resolution="1080p", episode_to=25),
            _pack(season=2, resolution="1080p", episode_to=12),
            _pack(season=3, resolution="720p", episode_to=22),
        ]
        result = svc._build_watch_guide(meta, packs)
        assert result is not None
        assert "Season 01" in result
        assert "Season 02" in result
        assert "Season 03" in result
        # Seasons should appear in order
        s01 = result.index("Season 01")
        s02 = result.index("Season 02")
        s03 = result.index("Season 03")
        assert s01 < s02 < s03

    def test_qualities_ordered_by_resolution(self):
        svc = _make_service()
        meta = {"title": "Test"}
        packs = [
            _pack(season=1, resolution="720p", episode_to=12),
            _pack(season=1, resolution="480p", episode_to=12),
            _pack(season=1, resolution="1080p", episode_to=12),
        ]
        result = svc._build_watch_guide(meta, packs)
        assert result is not None
        # Should be ordered 480p → 720p → 1080p
        p480 = result.index("480p")
        p720 = result.index("720p")
        p1080 = result.index("1080p")
        assert p480 < p720 < p1080

    def test_episode_count_from_max(self):
        svc = _make_service()
        meta = {"title": "Test"}
        packs = [
            _pack(season=1, resolution="1080p", episode_to=24, file_count=24),
            _pack(season=1, resolution="720p", episode_to=12, file_count=12),
        ]
        result = svc._build_watch_guide(meta, packs)
        assert result is not None
        # episode_to max is 24
        assert "24" in result

    def test_fallback_qualities_when_empty(self):
        svc = _make_service()
        meta = {"title": "Test"}
        packs = [_pack(season=1, resolution=None, episode_to=12)]
        result = svc._build_watch_guide(meta, packs)
        assert result is not None
        # When resolution is None, _RES_ORDER.get(None, 9999) puts it last but the
        # qual_str construction might produce empty. The guide should still render.
        assert "Season 01" in result


# ── _season_label ────────────────────────────────────────────────────────────


class TestSeasonLabel:
    def test_basic(self):
        svc = _make_service()
        assert svc._season_label(1, {}) == "Season 01"
        assert svc._season_label(12, {}) == "Season 12"
        assert svc._season_label(99, {}) == "Season 99"


# ── _build_info_card ─────────────────────────────────────────────────────────


class TestBuildInfoCard:
    async def test_no_title_returns_none(self):
        svc = _make_service()
        caption, image = await svc._build_info_card({"title": None})
        assert caption is None
        assert image is None

    async def test_with_full_metadata(self):
        svc = _make_service()
        meta = {
            "title": "Attack on Titan",
            "romaji": "Shingeki no Kyojin",
            "genres": ["Action", "Drama", "Fantasy"],
            "format": "TV",
            "score": "8.5",
            "status": "FINISHED",
            "release_date": "2013-04-07 to 2023-11-05",
            "episode_count": 94,
            "synopsis": "Humans fight giants.",
            "poster_url": "https://example.com/poster.jpg",
        }
        caption, image = await svc._build_info_card(meta)
        assert caption is not None
        assert "Attack on Titan" in caption
        assert "Action" in caption
        assert "8.5" in caption
        assert "TV" in caption
        assert image == meta["poster_url"]  # no banner, falls back to poster

    async def test_uses_banner_when_available(self):
        svc = _make_service()
        meta = {
            "title": "Test",
            "genres": [],
            "poster_url": "https://example.com/poster.jpg",
            "banner_url": "https://example.com/banner.jpg",
        }
        caption, image = await svc._build_info_card(meta)
        assert image == "https://example.com/banner.jpg"

    async def test_aired_dates_and_runtime_from_acutebot_fields(self):
        svc = _make_service()
        meta = {
            "title": "Test",
            "genres": [],
            "first_aired": "2021-01-10",
            "last_aired": "2021-03-28",
            "runtime": "24 min/ep",
        }
        caption, image = await svc._build_info_card(meta)
        assert caption is not None
        assert "2021-01-10" in caption
        assert "2021-03-28" in caption
        assert "24 min/ep" in caption

    async def test_fallback_to_placeholder(self):
        svc = _make_service()
        meta = {
            "title": "Minimal",
            "genres": [],
            "episode_count": None,
            "score": None,
            "synopsis": None,
        }
        caption, image = await svc._build_info_card(meta)
        assert caption is not None
        assert "Minimal" in caption
        assert "—" in caption  # placeholders for missing fields


# ── _build_season_card ───────────────────────────────────────────────────────


class TestBuildSeasonCard:
    def test_tv_season_format(self):
        svc = _make_service()
        meta = {"title": "Naruto", "genres": ["Action"], "score": "7.5", "synopsis": "Ninja world."}
        packs = [_pack(season=1, episode_to=25)]
        caption, image = svc._build_season_card(meta, 1, packs)
        assert caption is not None
        assert "Naruto" in caption
        assert "Season 1" in caption or "Season 01" in caption
        assert "25" in caption
        assert "Action" in caption

    def test_movie_detection(self):
        svc = _make_service()
        meta = {"title": "Movie", "genres": [], "score": None, "synopsis": "A movie."}
        # Single-episode pack with season=None → movie
        p = _pack(season=None, episode_to=1, episode_from=1, file_count=1)
        caption, image = svc._build_season_card(meta, 0, [p])
        assert caption is not None
        assert "1h" in caption

    def test_language_dual_audio(self):
        svc = _make_service()
        meta = {"title": "Test", "genres": [], "score": None, "synopsis": ""}
        packs = [_pack(audio=AudioType.DUAL_AUDIO, episode_to=12)]
        caption, image = svc._build_season_card(meta, 1, packs)
        assert caption is not None
        assert "Dual" in caption
        assert "ENG + JPN" in caption

    def test_language_subbed_only(self):
        svc = _make_service()
        meta = {"title": "Test", "genres": [], "score": None, "synopsis": ""}
        packs = [_pack(audio=AudioType.SUBBED, episode_to=12)]
        caption, image = svc._build_season_card(meta, 1, packs)
        assert caption is not None
        assert "Sub" in caption
        assert "JPN + EngSubs" in caption

    def test_language_dubbed_only(self):
        svc = _make_service()
        meta = {"title": "Test", "genres": [], "score": None, "synopsis": ""}
        packs = [_pack(audio=AudioType.DUBBED, episode_to=12)]
        caption, image = svc._build_season_card(meta, 1, packs)
        assert caption is not None
        assert "Dub" in caption
        assert "English" in caption

    def test_language_dubbed_with_subs(self):
        """English audio with subtitles → ENG + Subs."""
        svc = _make_service()
        result = svc._language_display({AudioType.DUBBED}, has_english_subs=True)
        assert result == "ENG + Subs"
        result = svc._language_display({AudioType.DUBBED}, has_english_subs=False)
        assert result == "English"

    def test_multi_audio_with_extra_langs(self):
        """When extra_langs has 3+ languages, DUAL_AUDIO → Multi / ENG+JPN+HIN."""
        svc = _make_service()
        audios = {AudioType.DUAL_AUDIO}
        assert "Multi" == svc._audio_display(audios, extra_langs={"en", "ja", "hi"})
        assert "Dual" == svc._audio_display(audios, extra_langs={"en", "ja"})
        assert "Dual" == svc._audio_display(audios)  # no extra_langs
        assert "ENG + JPN + HIN" == svc._language_display(audios, extra_langs={"en", "ja", "hi"})
        assert "ENG + JPN" == svc._language_display(audios, extra_langs={"en", "ja"})
        # Sub-only: no brackets, raw value.
        assert "JPN + EngSubs" == svc._language_display({AudioType.SUBBED})
        # Dub-only: "English" by default, "ENG + Subs" when has_english_subs.
        assert "English" == svc._language_display({AudioType.DUBBED})
        assert "ENG + Subs" == svc._language_display({AudioType.DUBBED}, has_english_subs=True)

    def test_image_is_poster_url(self):
        svc = _make_service()
        meta = {"title": "Test", "poster_url": "https://example.com/poster.jpg",
                "genres": [], "score": None, "synopsis": ""}
        packs = [_pack(episode_to=12)]
        caption, image = svc._build_season_card(meta, 1, packs)
        assert image == "https://example.com/poster.jpg"


# ── _build_season_buttons ────────────────────────────────────────────────────


class TestBuildSeasonButtons:
    def test_dual_audio_flat_layout(self):
        svc = _make_service()
        packs = [
            _pack(resolution="1080p", audio=AudioType.DUAL_AUDIO),
            _pack(resolution="720p", audio=AudioType.DUAL_AUDIO),
            _pack(resolution="480p", audio=AudioType.DUAL_AUDIO),
        ]
        result = svc._build_season_buttons(packs)
        assert result["type"] == "flat"
        assert result["qualities"] == ["480p", "720p", "1080p"]

    def test_separate_audio_layout(self):
        svc = _make_service()
        packs = [
            _pack(resolution="1080p", audio=AudioType.SUBBED),
            _pack(resolution="1080p", audio=AudioType.DUBBED),
            _pack(resolution="720p", audio=AudioType.SUBBED),
            _pack(resolution="720p", audio=AudioType.DUBBED),
        ]
        result = svc._build_season_buttons(packs)
        assert result["type"] == "separate_audio"
        assert len(result["sections"]) == 2
        assert result["sections"][0]["language"] == "english"
        assert result["sections"][1]["language"] == "japanese"
        # Both sections should have the available qualities
        for sec in result["sections"]:
            assert "720p" in sec["qualities"]
            assert "1080p" in sec["qualities"]

    def test_single_audio_flat(self):
        svc = _make_service()
        packs = [_pack(resolution="1080p", audio=AudioType.SUBBED)]
        result = svc._build_season_buttons(packs)
        assert result["type"] == "flat"
        assert result["qualities"] == ["1080p"]

    def test_dual_audio_with_separate_present_uses_flat(self):
        """When dual-audio packs exist alongside sub/dub, prefer flat layout."""
        svc = _make_service()
        packs = [
            _pack(resolution="1080p", audio=AudioType.DUAL_AUDIO),
            _pack(resolution="720p", audio=AudioType.SUBBED),
            _pack(resolution="720p", audio=AudioType.DUBBED),
        ]
        result = svc._build_season_buttons(packs)
        # Dual audio present → flat even though separate sub+dub also exist
        assert result["type"] == "flat"

    def test_qualities_filtered_to_reference_set(self):
        svc = _make_service()
        packs = [
            _pack(resolution="360p", audio=AudioType.DUAL_AUDIO),
            _pack(resolution="540p", audio=AudioType.DUAL_AUDIO),
        ]
        result = svc._build_season_buttons(packs)
        # 360p and 540p aren't in _BTN_QUALITIES, so fallback to all available
        assert result["type"] == "flat"
        assert len(result["qualities"]) == 2

    def test_no_packs_returns_flat_empty(self):
        svc = _make_service()
        result = svc._build_season_buttons([])
        assert isinstance(result, dict)
        assert "qualities" in result
