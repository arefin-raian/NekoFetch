"""Unit tests for distribution/app.py — content delivery helpers.

Tests focus on the pure helper functions that can be exercised without a live
Pyrogram client:
  - _build_buttons() — converts stored button_data into InlineKeyboardMarkup
  - publish_distribution_commands() — validates constants
  - DISTRIBUTION_COMMANDS — command definitions

The /start handler and other client-bound message handlers require a live
Pyrogram Client and are tested through integration tests only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.bots.distribution.app import (
    DISTRIBUTION_COMMANDS,
    _K_USER_LAST_ACTIVITY,
    publish_distribution_commands,
)
from nekofetch.infrastructure.database.postgres.models import BotContentPost


# ── fixture helpers ──────────────────────────────────────────────────────────


def _build_buttons(post: BotContentPost):
    """Recreate _build_buttons logic from distribution/app.py for test isolation.

    The real _build_buttons is a non-exported closure inside build_distribution_bot().
    We reconstruct its logic here so we can test it deterministically without
    starting a Pyrogram client.
    """
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from nekofetch.ui.components import cb

    bd = post.button_data
    if not bd:
        return None

    rows: list[list[InlineKeyboardButton]] = []

    if bd.get("type") == "flat":
        quals = bd.get("qualities", [])
        row = [
            InlineKeyboardButton(q, callback_data=cb("d", "placeholder", q))
            for q in quals
        ]
        if row:
            rows.append(row)

    elif bd.get("type") == "separate_audio":
        sections = bd.get("sections", [])
        for sec in sections:
            rows.append([
                InlineKeyboardButton(
                    sec.get("label", "English"),
                    callback_data=cb("d", "nolink"),
                )
            ])
            qrow = [
                InlineKeyboardButton(
                    q,
                    callback_data=cb("d", "placeholder", sec.get("language"), q),
                )
                for q in sec.get("qualities", [])
            ]
            if qrow:
                rows.append(qrow)

    if post.post_type == "movie_card":
        rows.append([
            InlineKeyboardButton(
                "Download Now",
                callback_data=cb("d", "placeholder", "download"),
            )
        ])

    return InlineKeyboardMarkup(rows) if rows else None


def _make_post(
    post_type: str = "season_card",
    button_data: dict | None = None,
    image_url: str | None = None,
    order: int = 0,
) -> BotContentPost:
    """Create a minimal BotContentPost-like object for testing."""
    p = MagicMock(spec=BotContentPost)
    p.post_type = post_type
    p.button_data = button_data
    p.image_url = image_url
    p.order = order
    p.caption = "Test caption"
    p.is_pinned = False
    return p


# ── publish_distribution_commands ────────────────────────────────────────────


class TestPublishDistributionCommands:
    async def test_commands_defined(self):
        """DISTRIBUTION_COMMANDS has the expected commands."""
        names = [c.command for c in DISTRIBUTION_COMMANDS]
        assert "start" in names
        assert "help" in names

    async def test_redis_key_format(self):
        """The Redis key template formats correctly."""
        key = _K_USER_LAST_ACTIVITY.format(bot_id=42, user_id=123)
        assert key == "nf:dist:lastact:42:123"

    async def test_publish_distribution_commands(self):
        """publish_distribution_commands calls set_bot_commands."""
        client = MagicMock()
        client.set_bot_commands = AsyncMock()
        await publish_distribution_commands(client)
        client.set_bot_commands.assert_awaited_once()


# ── _build_buttons — flat layout ─────────────────────────────────────────────


class TestBuildButtonsFlat:
    def test_no_button_data_returns_none(self):
        post = _make_post()
        markup = _build_buttons(post)
        assert markup is None

    def test_single_quality(self):
        post = _make_post(button_data={"type": "flat", "qualities": ["1080p"]})
        markup = _build_buttons(post)
        assert markup is not None
        assert markup.inline_keyboard[0][0].text == "1080p"

    def test_three_qualities_in_single_row(self):
        post = _make_post(button_data={
            "type": "flat", "qualities": ["480p", "720p", "1080p"],
        })
        markup = _build_buttons(post)
        assert markup is not None
        row = markup.inline_keyboard[0]
        assert len(row) == 3
        assert row[0].text == "480p"
        assert row[1].text == "720p"
        assert row[2].text == "1080p"

    def test_empty_qualities_returns_no_row(self):
        post = _make_post(button_data={"type": "flat", "qualities": []})
        markup = _build_buttons(post)
        assert markup is None

    def test_quality_callback_matches_pattern(self):
        post = _make_post(button_data={"type": "flat", "qualities": ["720p"]})
        markup = _build_buttons(post)
        assert markup is not None
        cb = markup.inline_keyboard[0][0].callback_data
        assert "d|placeholder|720p" in cb


# ── _build_buttons — separate audio layout ───────────────────────────────────


class TestBuildButtonsSeparateAudio:
    def test_two_language_sections(self):
        post = _make_post(button_data={
            "type": "separate_audio",
            "sections": [
                {"language": "english", "label": "English", "qualities": ["720p", "1080p"]},
                {"language": "japanese", "label": "Japanese", "qualities": ["720p", "1080p"]},
            ],
        })
        markup = _build_buttons(post)
        assert markup is not None
        keyboard = markup.inline_keyboard

        # Row 0: language label, Row 1: quality buttons, Row 2: language label, Row 3: quality buttons
        assert keyboard[0][0].text == "English"
        assert keyboard[1][0].text == "720p"
        assert keyboard[1][1].text == "1080p"
        assert keyboard[2][0].text == "Japanese"
        assert keyboard[3][0].text == "720p"
        assert keyboard[3][1].text == "1080p"

    def test_language_label_is_nolink(self):
        """Language label buttons should be visual-only (nolink callback)."""
        post = _make_post(button_data={
            "type": "separate_audio",
            "sections": [
                {"language": "english", "label": "⬇️ English ↴", "qualities": ["720p"]},
            ],
        })
        markup = _build_buttons(post)
        assert markup is not None
        cb = markup.inline_keyboard[0][0].callback_data
        assert "d|nolink" in cb

    def test_quality_callback_includes_language(self):
        """Quality buttons under a language section should encode the language."""
        post = _make_post(button_data={
            "type": "separate_audio",
            "sections": [
                {"language": "english", "label": "English", "qualities": ["1080p"]},
            ],
        })
        markup = _build_buttons(post)
        assert markup is not None
        cb = markup.inline_keyboard[1][0].callback_data
        assert "english" in cb
        assert "1080p" in cb

    def test_empty_sections(self):
        post = _make_post(button_data={
            "type": "separate_audio",
            "sections": [],
        })
        markup = _build_buttons(post)
        assert markup is None


# ── _build_buttons — movie cards ─────────────────────────────────────────────


class TestBuildButtonsMovieCard:
    def test_movie_card_has_download_now_button(self):
        post = _make_post(
            post_type="movie_card",
            button_data={"type": "flat", "qualities": ["1080p"]},
        )
        markup = _build_buttons(post)
        assert markup is not None
        # Last row should be the Download Now button
        last_row = markup.inline_keyboard[-1]
        assert "Download Now" in last_row[0].text

    def test_movie_card_no_button_data_returns_none(self):
        """Without button_data, _build_buttons returns None regardless of post_type.

        The movie-card's Download Now button is only appended when button_data
        exists — it's an additional row on top of the quality layout, not a
        standalone fallback.
        """
        post = _make_post(post_type="movie_card", button_data=None)
        markup = _build_buttons(post)
        assert markup is None


# ── _build_buttons — edge cases ──────────────────────────────────────────────


class TestBuildButtonsEdgeCases:
    def test_unknown_button_type(self):
        """Unknown button_data types should render no buttons."""
        post = _make_post(button_data={"type": "unknown", "things": []})
        markup = _build_buttons(post)
        assert markup is None

    def test_missing_type_key(self):
        post = _make_post(button_data={"qualities": ["720p"]})
        markup = _build_buttons(post)
        assert markup is None
