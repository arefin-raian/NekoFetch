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


def disabled_markup(markup: InlineKeyboardMarkup | None) -> InlineKeyboardMarkup | None:
    """Return a copy of ``markup`` with every button neutralized.

    Labels are kept (so the panel still reads the same) but every callback is
    routed to ``noop`` — the button stays *visible but inert*, which is what we
    want while the next screen loads: disabled, not hidden, so it can't be
    double-fired. Returns ``None`` when there's nothing to disable.
    """
    if markup is None or not getattr(markup, "inline_keyboard", None):
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b.text, callback_data=cb("noop")) for b in row]
         for row in markup.inline_keyboard]
    )


async def lock_buttons(q) -> None:
    """Immediately neutralize the buttons on the message a callback fired from.

    Call this at the very top of a flow handler, before any slow async work, so a
    second tap during the load window hits inert ``noop`` buttons instead of
    re-triggering the action. Best-effort — purely cosmetic, never raises.
    """
    try:
        await q.message.edit_reply_markup(disabled_markup(q.message.reply_markup))
    except Exception:
        pass
