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


def now_label(fmt: str = "%H:%M:%S %Z") -> str:
    """Short 'now' label for live UI (e.g. '13:45:09 +06')."""
    return now().strftime(fmt)


def to_display(dt: datetime, fmt: str = "%Y-%m-%d %H:%M %Z") -> str:
    """Render a (possibly UTC) datetime in the display timezone. Naive datetimes
    are assumed to be UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(DISPLAY_TZ).strftime(fmt)
