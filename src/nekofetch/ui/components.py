"""Reusable premium UI components: layouts, inline keyboards, pagination.

Keeps the design language consistent (glyphs, minimal emoji, elegant spacing) and
centralizes callback-data conventions so handlers stay declarative.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nekofetch.core.constants import ARROW, DIAMOND_FILLED, PIPE, TRIANGLE

CB_SEP = "|"  # callback-data field separator


def cb(action: str, *args: object) -> str:
    """Build compact callback data: ``action|arg1|arg2`` (<=64 bytes)."""
    return CB_SEP.join([action, *(str(a) for a in args)])


def parse_cb(data: str) -> tuple[str, list[str]]:
    action, *args = data.split(CB_SEP)
    return action, args


def bullet_list(items: list[str], glyph: str = DIAMOND_FILLED) -> str:
    return "\n".join(f"{glyph} {item}" for item in items)


def field(label: str, value: str) -> str:
    """A label/value block in the house style."""
    return f"{label}:\n{value}"


def section(title: str) -> str:
    return f"{TRIANGLE} {title}"


def divider() -> str:
    return PIPE * 1


@dataclass(slots=True)
class Page:
    buttons: list[InlineKeyboardButton]
    index: int
    total_pages: int


def paginate(
    items: list[tuple[str, str]],
    *,
    page: int,
    nav_action: str,
    page_size: int = 8,
    columns: int = 1,
) -> InlineKeyboardMarkup:
    """Build a paginated inline keyboard.

    ``items`` are (label, callback_data) pairs. ``nav_action`` is the callback action
    used for the prev/next controls (it receives the target page index as its arg).
    """
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    window = items[start : start + page_size]

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, data in window:
        row.append(InlineKeyboardButton(label, callback_data=data))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(f"{ARROW} Prev", callback_data=cb(nav_action, page - 1)))
        nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=cb("noop")))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(f"Next {ARROW}", callback_data=cb(nav_action, page + 1)))
        rows.append(nav)

    return InlineKeyboardMarkup(rows)


def keyboard(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Concise keyboard builder from rows of (label, callback_data) pairs."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in rows]
    )
