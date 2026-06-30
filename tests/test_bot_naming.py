"""Distribution-bot name formatting."""

from __future__ import annotations

from nekofetch.domain.enums import AudioType
from nekofetch.services.bot_naming import audio_tag, format_bot_name, format_bot_username

A = AudioType


def test_audio_tag_variants():
    assert audio_tag({A.SUBBED, A.DUBBED}) == "Dual Sub Dub"
    assert audio_tag({A.DUAL_AUDIO}) == "Dual Sub Dub"
    assert audio_tag({A.SUBBED}) == "Sub"
    assert audio_tag({A.DUBBED}) == "Dub"
    assert audio_tag(set()) == ""


def test_audio_tag_multi_language():
    assert audio_tag({A.SUBBED, A.DUBBED}, {"english", "japanese", "hindi"}) == "Multi Dual Sub Dub"
    assert audio_tag({A.SUBBED, A.DUBBED}, {"english", "japanese"}) == "Dual Sub Dub"


def test_format_name_english_and_romaji():
    n = format_bot_name("Attack on Titan", "Shingeki no Kyojin", audios={A.SUBBED, A.DUBBED})
    assert n == "Attack on Titan / Shingeki no Kyojin [Dual Sub Dub]"


def test_format_name_same_title_not_doubled():
    n = format_bot_name("Frieren", "Frieren", audios={A.SUBBED})
    assert n == "Frieren [Sub]"


def test_format_name_truncates_to_64_keeping_tag():
    long = "A" * 80
    n = format_bot_name(long, "", audios={A.SUBBED, A.DUBBED})
    assert len(n) <= 64
    assert n.endswith("[Dual Sub Dub]")


def test_username_is_valid():
    u = format_bot_username("Takopi's Original Sin!!", "doc123")
    assert 5 <= len(u) <= 32
    assert u.endswith("bot")
    assert all(c.isalnum() or c == "_" for c in u)
