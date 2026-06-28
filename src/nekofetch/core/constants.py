"""Project-wide constant values.

The design language is *terminal-clean, anime-modern*: a small, cohesive set of
Unicode marks that read well in Telegram's monospace-ish rendering. One palette,
used everywhere, so the whole surface feels like one product. Prefer the
semantic names below (``DOT_ACTIVE``, ``RULE``, ``ARROW``) over raw characters.
"""

from __future__ import annotations

# ── Rules / dividers ──────────────────────────────────────────────────────────
# Kept short (≈12 cells) so they never wrap to a second line on a narrow phone.
RULE = "────────────"          # primary section divider (thin)
RULE_SOFT = "╌╌╌╌╌╌╌╌╌╌╌╌"      # secondary / sub-divider
RULE_HEAVY = "━━━━━━━━━━━━"      # header underline / emphasis

# ── Progress bar cells ────────────────────────────────────────────────────────
BAR_FILLED = "█"
BAR_EMPTY = "░"

# ── Status dots (lifecycle / health) ──────────────────────────────────────────
DOT_DONE = "●"        # completed
DOT_ACTIVE = "◐"      # in progress
DOT_PENDING = "○"     # waiting
DOT_FAIL = "✕"        # failed / blocked

# ── Structure / pointers ──────────────────────────────────────────────────────
ARROW = "→"
CHEVRON = "›"
TRIANGLE = "▸"
BULLET = "•"
TREE_MID = "├─"
TREE_END = "╰─"
PIPE = "│"
PIPE_DOTTED = "┆"

# ── Legacy aliases (kept so older imports keep resolving; migrate to the
# semantic names above). ──
DIAMOND_FILLED = TRIANGLE
DIAMOND_HOLLOW = "◦"
DIAMOND_FANCY = "◆"

# ── Redis key namespaces ──
REDIS_PROGRESS = "nf:progress:{job_id}"
REDIS_RATELIMIT = "nf:rl:{user_id}"
REDIS_FSM = "nf:fsm:{bot}:{user_id}"
REDIS_JOB_LOCK = "nf:lock:{job_id}"

# ── Request identifiers ──
REQUEST_PREFIX = "REQ"

# ── Pagination ──
DEFAULT_PAGE_SIZE = 8
