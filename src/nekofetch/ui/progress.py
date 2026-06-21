"""Progress bar rendering using the design glyphs ▰ / ▱.

    Searching Anime...

    ▰▰▱▱▱▱▱▱▱▱ 20%
"""

from __future__ import annotations

from nekofetch.core.constants import BAR_EMPTY, BAR_FILLED


def bar(percent: float, *, width: int = 10) -> str:
    """Render a filled/empty glyph bar with a trailing percentage."""
    percent = max(0.0, min(100.0, percent))
    filled = round(percent / 100 * width)
    return f"{BAR_FILLED * filled}{BAR_EMPTY * (width - filled)} {int(percent)}%"


def labeled(label: str, percent: float, *, width: int = 10) -> str:
    """A captioned progress block, e.g. for staged status messages."""
    return f"{label}\n\n{bar(percent, width=width)}"


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def human_speed(bps: float) -> str:
    return f"{human_bytes(bps)}/s"


def human_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}h {m:02d}m"
    return f"{m:02d}m {s:02d}s"
