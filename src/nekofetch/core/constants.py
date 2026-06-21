"""Project-wide constant values.

Stylistic symbols come from the design language: minimal, modern, anime-inspired.
Avoid emojis; prefer these glyphs throughout the UI.
"""

from __future__ import annotations

# ── Design glyphs ──
DIAMOND_FILLED = "◆"
DIAMOND_HOLLOW = "◇"
DIAMOND_FANCY = "◈"
BAR_FILLED = "▰"
BAR_EMPTY = "▱"
ARROW = "➜"
TRIANGLE = "▸"
PIPE = "│"
PIPE_DOTTED = "┆"

# ── Redis key namespaces ──
REDIS_PROGRESS = "nf:progress:{job_id}"
REDIS_RATELIMIT = "nf:rl:{user_id}"
REDIS_FSM = "nf:fsm:{bot}:{user_id}"
REDIS_JOB_LOCK = "nf:lock:{job_id}"

# ── Request identifiers ──
REQUEST_PREFIX = "REQ"

# ── Pagination ──
DEFAULT_PAGE_SIZE = 8
