from nekofetch.core.parsing import parse_episode_spec


def test_ranges_and_singletons():
    assert parse_episode_spec("1-5, 8, 10") == [1, 2, 3, 4, 5, 8, 10]


def test_dedup_and_sort():
    assert parse_episode_spec("3,1,2,2,1") == [1, 2, 3]


def test_ignores_garbage():
    assert parse_episode_spec("abc, 4, x-y, 7-6") == [4]


def test_empty():
    assert parse_episode_spec("") == []
    assert parse_episode_spec("  ,  ") == []
