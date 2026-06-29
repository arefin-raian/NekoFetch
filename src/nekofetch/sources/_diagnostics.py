"""Shared download-failure classification for every web source.

The same failure modes occur on AniKoto, KickAssAnime and any future site, so the
diagnosis lives in ONE place rather than being re-guessed per provider. Both the
HLS segment engine and each source's server-fallback loop classify failures the
same way, so logs and the eventual "every server tried" verdict read identically
no matter which site produced them.

The point is to never emit a bare "download failed": every failure carries a
``FailureKind`` (what class of problem) plus a concrete human reason (status, CDN
host, Cloudflare mitigation, body snippet) so we know whether to retry, refresh
metadata, fall back to another server, or genuinely give up.
"""

from __future__ import annotations

import enum

import httpx


class FailureKind(enum.Enum):
    """Why a fetch/extraction failed — drives the recovery decision."""

    BLOCKED = "blocked"            # 403 / WAF challenge — missing header/cookie/fingerprint
    DEAD_HOST = "dead_host"        # 521/522/523/connect — origin/CDN host unreachable
    SERVER_ERROR = "server_error"  # 500/502/503/504 — transient backend error
    RATE_LIMITED = "rate_limited"  # 429 — back off and retry
    EXPIRED = "expired"            # 401 / token-looking 403 — stale token, re-extract
    NOT_FOUND = "not_found"        # 404/410 — genuinely gone on this server
    EXTRACTION = "extraction"      # we never produced a stream/server list to try
    UNKNOWN = "unknown"

    @property
    def retryable(self) -> bool:
        """Whether retrying the SAME url could plausibly succeed."""
        return self in {
            FailureKind.DEAD_HOST, FailureKind.SERVER_ERROR, FailureKind.RATE_LIMITED,
        }

    @property
    def needs_refresh(self) -> bool:
        """Whether the fix is to re-extract fresh metadata (new token/url)."""
        return self in {FailureKind.EXPIRED, FailureKind.BLOCKED}


def classify_response(resp: httpx.Response) -> tuple[FailureKind, str]:
    """Classify a non-OK HTTP response into a kind + concrete reason."""
    s = resp.status_code
    h = resp.headers
    host = resp.url.host
    cfm = h.get("cf-mitigated")
    server = h.get("server", "?")
    base = f"HTTP {s} on {host} [server={server} cf-ray={h.get('cf-ray', '-')} cf-mitigated={cfm or '-'}]"
    if s in (521, 522, 523, 525, 526):
        return FailureKind.DEAD_HOST, f"{base} — CDN origin unreachable (host down)"
    if s == 429:
        return FailureKind.RATE_LIMITED, f"{base} — rate limited"
    if s == 401:
        return FailureKind.EXPIRED, f"{base} — unauthorized (token expired/missing)"
    if s == 403:
        kind = FailureKind.BLOCKED if (cfm or server.startswith("cloudflare")) else FailureKind.EXPIRED
        why = "WAF/bot challenge" if kind is FailureKind.BLOCKED else "forbidden (missing referer/token)"
        return kind, f"{base} — {why}"
    if s in (404, 410):
        return FailureKind.NOT_FOUND, f"{base} — not found on this server"
    if 500 <= s < 600:
        return FailureKind.SERVER_ERROR, f"{base} — server error"
    return FailureKind.UNKNOWN, base


def classify_exception(exc: BaseException) -> tuple[FailureKind, str]:
    """Classify a transport-level exception (no response) into a kind + reason."""
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return FailureKind.DEAD_HOST, f"connection failed — {exc}"
    if isinstance(exc, httpx.TimeoutException):
        return FailureKind.DEAD_HOST, f"timed out — {exc}"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return classify_response(exc.response)
    return FailureKind.UNKNOWN, f"{type(exc).__name__}: {exc}"


def classify(obj: object) -> tuple[FailureKind, str]:
    """Classify either a response or an exception."""
    if isinstance(obj, httpx.Response):
        return classify_response(obj)
    if isinstance(obj, BaseException):
        return classify_exception(obj)
    return FailureKind.UNKNOWN, str(obj)
