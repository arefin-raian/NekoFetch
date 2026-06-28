"""Text formatting helpers — HTML only.

Emphasis comes from real HTML tags (Telegram HTML parse mode). Bold is the
default for anything that matters; italic for secondary notes. No ``<code>`` for
ordinary prose. Structural marks (rules, dots, arrows) come from
:mod:`nekofetch.core.constants` so the whole UI shares one visual language.
"""

from __future__ import annotations

from nekofetch.core.constants import RULE, RULE_HEAVY, RULE_SOFT


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


def rule(style: str = "thin") -> str:
    """A horizontal divider. ``style`` ∈ {thin, soft, heavy}."""
    return {"thin": RULE, "soft": RULE_SOFT, "heavy": RULE_HEAVY}.get(style, RULE)


def section(icon: str, title: str) -> str:
    """A section header: ``<icon>  <b>Title</b>`` over a thin rule."""
    return f"{icon}  <b>{title}</b>\n<i>{RULE}</i>"
