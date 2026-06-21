from nekofetch.providers.metadata.models import (
    RawAssets,
    RawCharacter,
    RawProfile,
    RawStatistics,
)
from nekofetch.providers.metadata.renderer import render_anime_info
from nekofetch.providers.metadata.transformer import build_template_data


def _data():
    return build_template_data(
        "naruto",
        profile=RawProfile(
            title="Naruto", genres=["Action"], studio="Pierrot", episode_count=220
        ),
        characters=[RawCharacter(name="Naruto Uzumaki", role="Main")],
        statistics=RawStatistics(score=8.0, rank=10, status="Finished"),
        assets=RawAssets(poster_url="p.jpg", banner_url="b.jpg"),
    )


def test_transformer_merges_status_from_statistics():
    data = _data()
    assert data.title == "Naruto"
    # status was absent on profile, taken from statistics
    assert data.status == "Finished"
    assert data.header_image == "b.jpg"  # banner preferred


def test_renderer_includes_present_sections():
    card = render_anime_info(_data(), footer="Anime Weebs")
    assert "Naruto" in card.caption
    assert card.has_characters is True
    assert card.has_statistics is True
    assert card.image_url == "b.jpg"
    assert "Anime Weebs" in card.caption


def test_renderer_minimal_requires_only_title():
    data = build_template_data("x", profile=RawProfile(title="Solo"))
    card = render_anime_info(data)
    assert "Solo" in card.caption
    assert card.has_characters is False
    assert card.image_url is None
