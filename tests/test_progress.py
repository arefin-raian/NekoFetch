from nekofetch.ui import progress


def test_bar_bounds():
    assert progress.bar(0).endswith("0%")
    assert progress.bar(100).endswith("100%")
    # Clamps out-of-range input.
    assert progress.bar(-10).endswith("0%")
    assert progress.bar(250).endswith("100%")


def test_bar_width():
    rendered = progress.bar(50, width=10)
    glyphs = rendered.split(" ")[0]
    assert len(glyphs) == 10
    assert glyphs.count(progress.BAR_FILLED) == 5


def test_human_bytes():
    assert progress.human_bytes(0) == "0.0 B"
    assert progress.human_bytes(1024) == "1.0 KB"
    assert progress.human_bytes(1024 * 1024) == "1.0 MB"


def test_human_eta():
    assert progress.human_eta(None) == "—"
    assert progress.human_eta(65) == "01m 05s"
    assert "h" in progress.human_eta(3700)
