"""Small pure parsers shared across the app (no framework imports — easy to test)."""

from __future__ import annotations


def parse_episode_spec(spec: str) -> list[int]:
    """Parse an episode selection like ``"1-5, 8, 10"`` into ``[1,2,3,4,5,8,10]``.

    Ignores malformed fragments; returns a sorted, de-duplicated list.
    """
    out: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                if lo <= hi:
                    out.update(range(lo, hi + 1))
        elif part.isdigit():
            out.add(int(part))
    return sorted(out)
