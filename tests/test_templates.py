from nekofetch.ui import templates


def test_render_substitutes():
    assert templates.render("{a}-{b}", a="x", b="y") == "x-y"


def test_render_keeps_unknown_placeholders():
    # A missing key must not raise; it's left intact for the admin to notice.
    assert templates.render("{title} {missing}", title="Naruto") == "Naruto {missing}"


def test_render_filename_strips_illegal_chars():
    out = templates.render_filename("{t}", t='a/b:c*d?"e')
    for ch in '/\\:*?"<>|':
        assert ch not in out


def test_render_filename_collapses_whitespace():
    assert templates.render_filename("{t}", t="a    b   c") == "a b c"
