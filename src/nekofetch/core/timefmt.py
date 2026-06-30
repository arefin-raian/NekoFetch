"""Display-timezone helpers.

Everything is *stored* in UTC (timezone-aware) — that never changes. But times
*shown* to people should be local: this project runs for a Bangladesh audience, so
the display timezone defaults to Asia/Dhaka (UTC+6). Override with the ``NEKO_TZ``
env var if you ever run it elsewhere.

On Windows the IANA ``zoneinfo`` database may be absent; we fall back to a fixed
UTC+6 offset so the app never crashes for the want of tzdata (Bangladesh has no DST).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

_TZ_NAME = os.getenv("NEKO_TZ", "Asia/Dhaka")
# Fixed-offset fallback (UTC+6, "Dhaka") for hosts without the tz database.
_FALLBACK = timezone(timedelta(hours=6), "Dhaka")

try:
    from zoneinfo import ZoneInfo

    DISPLAY_TZ = ZoneInfo(_TZ_NAME)
except Exception:  # noqa: BLE001 - missing tzdata / bad name → fixed offset
    DISPLAY_TZ = _FALLBACK


def now() -> datetime:
    """Current time in the display timezone."""
    return datetime.now(DISPLAY_TZ)


def offset_label() -> str:
    """The display timezone as a clean human label, e.g. 'UTC+6' (not '+06')."""
    off = now().utcoffset() or timedelta(0)
    total_min = int(off.total_seconds() // 60)
    sign = "+" if total_min >= 0 else "-"
    h, m = divmod(abs(total_min), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def now_label(fmt: str = "%H:%M:%S") -> str:
    """Short, CLEAN 'now' label for live UI (e.g. '13:45:09') — no timezone offset,
    which keeps the activity stream and section headers uncluttered."""
    return now().strftime(fmt)


def to_display(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a (possibly UTC) datetime in the display timezone with an explicit,
    readable zone label ('UTC+6'). Naive datetimes are assumed to be UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TZ).strftime(fmt) + f" {offset_label()}"
