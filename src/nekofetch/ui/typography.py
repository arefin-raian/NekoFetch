"""Text formatting helpers — HTML only.

Emphasis comes from real HTML tags (Telegram HTML parse mode), not unicode
"small caps"/"bold serif" tricks. Bold is the default for anything that matters;
italic for secondary notes. No ``<code>`` for ordinary text.
"""

from __future__ import annotations


def b(text: str) -> str:
    return f"<b>{text}</b>"


def i(text: str) -> str:
    return f"<i>{text}</i>"


def bq(text: str) -> str:
    return f"<blockquote>{text}</blockquote>"


def bqx(text: str) -> str:
    return f"<blockquote expandable>{text}</blockquote>"


def heading(text: str) -> str:
    """A bold heading line."""
    return f"<b>{text}</b>"


def field(label: str, value: str) -> str:
    """A clean ``Label : value`` row — bold label, plain value (no code box)."""
    return f"<b>{label}:</b> {value}"


# ── Deprecated shims ──
# Former unicode-styling helpers. Kept as identity passthroughs so existing
# imports keep working while call sites migrate to plain text + <b>/<i>.
# They intentionally do NOT transform text any more.
def small_caps(text: str) -> str:  # noqa: D401 - deprecated, identity
    return text


def bold_serif(text: str) -> str:  # noqa: D401 - deprecated, identity
    return text
