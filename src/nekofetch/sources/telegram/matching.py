"""Flexible anime-title matching.

Titles vary wildly in separators and casing across Telegram indexes and release
groups: "Attack on Titan", "Attack-on-Titan", "AttackOnTitan", "Attack_On_Titan",
"[Group] Attack.on.Titan.S01". We never compare by exact string — instead we
reduce a title to its set of meaningful word tokens and check that all of the
query's meaningful words appear in the candidate, regardless of formatting.
"""

from __future__ import annotations

import re

# Words that carry no identifying weight when matching a title.
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "no", "wa", "ga", "wo", "season",
    "part", "cour", "tv", "ova", "ona", "movie", "special", "specials",
}

# Tokens that hint at quality/format, never part of the title proper.
_NOISE = re.compile(
    r"\b(480p|540p|720p|1080p|2160p|4k|bd|bluray|web|webrip|webdl|hevc|x264|x265|"
    r"av1|10bit|8bit|aac|opus|flac|dual|audio|multi|sub|subs|subbed|dubbed|eng|"
    r"jpn|batch|complete|uncensored|remux|repack|v\d)\b",
    re.IGNORECASE,
)

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def normalize_words(title: str) -> set[str]:
    """Reduce a title to a set of meaningful lowercase word tokens.

    Splits camelCase, normalizes every separator, drops quality/format noise,
    stopwords, and pure punctuation. Roman numerals and digits are kept (they
    distinguish seasons / sequels).
    """
    if not title:
        return set()
    # strip bracketed group/quality tags first: [Group], (1080p), {x265}
    s = re.sub(r"[\[(\{][^\]\)\}]*[\]\)\}]", " ", title)
    s = _NOISE.sub(" ", s)
    s = _CAMEL.sub(" ", s)            # AttackOnTitan -> Attack On Titan
    s = re.sub(r"[^\w\s]", " ", s)    # separators -> space
    s = re.sub(r"_", " ", s)
    words = {w.lower() for w in s.split() if w}
    return {w for w in words if w not in _STOPWORDS and (len(w) > 1 or w.isdigit())}


def title_matches(query: str, candidate: str, *, threshold: float = 1.0) -> bool:
    """True if ``candidate`` contains all meaningful words of ``query``.

    ``threshold`` (0–1) is the fraction of query words that must be present;
    1.0 requires every meaningful word (the default, strict but separator-proof).
    """
    q = normalize_words(query)
    if not q:
        return False
    c = normalize_words(candidate)
    if not c:
        return False
    present = len(q & c)
    return present / len(q) >= threshold


def best_match(query: str, candidates: list[str], *, threshold: float = 0.85):
    """Return (index, score) of the best-matching candidate, or (-1, 0.0).

    Score = fraction of the query's meaningful words found in the candidate;
    ties break toward the shorter candidate (less likely to be a batch/superset).
    """
    q = normalize_words(query)
    if not q:
        return -1, 0.0
    best_i, best_score, best_len = -1, 0.0, 1 << 30
    for i, cand in enumerate(candidates):
        c = normalize_words(cand)
        if not c:
            continue
        score = len(q & c) / len(q)
        clen = len(c)
        if score > best_score or (score == best_score and clen < best_len):
            best_i, best_score, best_len = i, score, clen
    return (best_i, best_score) if best_score >= threshold else (-1, best_score)


def any_title_matches(queries: list[str], candidate: str, *, threshold: float = 0.9) -> bool:
    """True if the candidate matches ANY of the query titles (e.g. Anilist set)."""
    return any(title_matches(q, candidate, threshold=threshold) for q in queries if q)


def meaningful_variants(variants: list[str]) -> list[str]:
    """Drop acronym/too-short variants that cause false matches.

    Acronyms like "AoT" / "SnK" normalize to a single short token (e.g. {"ao"})
    and collide with unrelated titles ("Ao Ashi"). Keep only variants with ≥2
    meaningful words, or a single word of ≥5 characters.
    """
    out = []
    for v in variants:
        words = normalize_words(v)
        if len(words) >= 2 or (len(words) == 1 and len(next(iter(words))) >= 5):
            out.append(v)
    return out or variants
