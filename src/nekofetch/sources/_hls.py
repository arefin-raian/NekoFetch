"""Shared, ffmpeg-free HLS download engine.

Many of the streaming origins these sources pull from disguise each HLS
segment with a junk header (a tiny fake PNG/JPEG plus padding) so that naive
downloaders — yt-dlp, ffmpeg, a plain GET loop — save unplayable garbage. The
real MPEG-TS payload always begins on a 188-byte packet boundary, so we can
locate it byte-for-byte and strip the mask without any external tools.

The output is a clean ``.ts`` file, which every real player (VLC, mpv, browsers)
plays natively. If ffmpeg happens to be installed we can losslessly remux to
``.mp4`` for a tidier container, but it is never required.
"""

from __future__ import annotations

import asyncio
import random
import re
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urljoin

import httpx

from nekofetch.core.logging import get_logger

log = get_logger(__name__)

# MPEG-TS: fixed 188-byte packets, each starting with the 0x47 sync byte.
TS_SYNC = 0x47
TS_PKT = 188

# Default segment-fetch concurrency. 8 is the reliability sweet spot: krussdomi
# (KickAssAnime's CDN) starts 403-rate-limiting an IP under sustained 16-wide
# bursts across back-to-back episodes, so we trade a little peak speed for not
# getting blocked mid-run.
DEFAULT_CONCURRENCY = 8

# Connection-pool limits sized for the concurrency above. Keeping every worker's
# connection alive (keepalive == max) lets the pool reuse TLS sessions across the
# hundreds of segments in an episode instead of re-handshaking each time.
RECOMMENDED_LIMITS = httpx.Limits(
    max_connections=32,
    max_keepalive_connections=32,
    keepalive_expiry=30.0,
)

# Split connect/read/write/pool budgets so a single slow segment can't stall the
# whole pipeline — a stuck read fails fast and is retried on a fresh connection.
RECOMMENDED_TIMEOUT = httpx.Timeout(connect=15.0, read=30.0, write=30.0, pool=30.0)

ProgressCb = Callable[[int, int], Awaitable[None]] | None

# HTTP status codes worth retrying (transient): rate-limit + the 5xx family.
_RETRYABLE = {429, 500, 502, 503, 504, 520, 521, 522, 524}


def build_client(headers: dict | None = None, *, http2: bool = False) -> httpx.AsyncClient:
    """Create an httpx client tuned for high-concurrency segment fetching."""
    return httpx.AsyncClient(
        headers=headers or {},
        limits=RECOMMENDED_LIMITS,
        timeout=RECOMMENDED_TIMEOUT,
        follow_redirects=True,
        http2=http2,
    )


def ts_start(seg: bytes) -> int:
    """Offset where the genuine MPEG-TS stream begins inside ``seg``.

    Tests offsets congruent to ``len(seg) % 188`` first — the real payload is a
    whole number of packets, so the decoy length ≡ ``len % 188`` and this hits on
    the first probe — then falls back to a short linear scan. The chosen offset
    must hold the 188-byte sync grid for ~40 packets, which rejects coincidental
    ``0x47`` bytes inside the decoy.
    """
    n = len(seg)
    candidates: list[int] = [n % TS_PKT + TS_PKT * i for i in range(4)]
    candidates += range(0, min(n, 8192))
    for s in candidates:
        if 0 <= s < n and seg[s] == TS_SYNC:
            window = range(s, min(n, s + TS_PKT * 40), TS_PKT)
            if sum(1 for k in window if seg[k] == TS_SYNC) >= 38:
                return s
    return 0


def ts_is_clean(data: bytes) -> bool:
    """True if ``data`` is a coherent transport stream end to end (>99.9% sync)."""
    if len(data) < TS_PKT * 100:
        return False
    rem = len(data) % TS_PKT
    start = rem if data[rem:rem + 1] == b"\x47" else 0
    grid = range(start, len(data) - TS_PKT, TS_PKT)
    total = len(grid)
    if total == 0:
        return False
    hits = sum(1 for k in grid if data[k] == TS_SYNC)
    return hits / total > 0.999


def looks_like_ts(seg: bytes) -> bool:
    """Heuristic: does this segment carry a maskable/real transport stream?"""
    return ts_start(seg) > 0 or (len(seg) > TS_PKT and seg[0] == TS_SYNC)


async def resolve_media_playlist(
    http: httpx.AsyncClient, url: str, headers: dict, quality: str, _depth: int = 0
) -> tuple[str, str]:
    """Walk a master playlist down to the media playlist matching ``quality``.

    Returns ``(media_url, media_text)``. ``quality`` is a bare height like
    ``"720"``; if no exact match exists the highest variant is chosen.
    """
    txt = (await http.get(url, headers=headers)).text
    if "#EXTM3U" not in txt[:64]:
        # A blocked/expired link often returns an HTML error page; treating its
        # lines as segments yields garbage URLs. Reject so the caller falls back.
        raise RuntimeError(f"not an HLS playlist (got {txt[:40]!r})")
    if "#EXT-X-STREAM-INF" not in txt or _depth > 4:
        return url, txt
    lines = txt.splitlines()
    variants: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if ln.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            m = re.search(r"RESOLUTION=\d+x(\d+)", ln)
            height = int(m.group(1)) if m else 0
            variants.append((height, urljoin(url, lines[i + 1].strip())))
    if not variants:
        return url, txt
    variants.sort()
    want = quality.rstrip("p")
    chosen = next((u for h, u in variants if str(h) == want), variants[-1][1])
    return await resolve_media_playlist(http, chosen, headers, quality, _depth + 1)


async def _fetch_segment(
    http: httpx.AsyncClient, seg_url: str, headers: dict, max_retries: int = 4
) -> bytes:
    """GET one segment with jittered backoff, honoring 429 Retry-After.

    Non-retryable HTTP errors (e.g. 404) raise immediately so a dead segment
    fails the whole stream fast and the caller can fall back to another server,
    rather than burning the full retry budget on a permanent error.
    """
    delay = 0.5
    for attempt in range(max_retries):
        try:
            resp = await http.get(seg_url, headers=headers)
            if resp.status_code in _RETRYABLE:
                wait = float(resp.headers.get("retry-after", delay))
                raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status not in _RETRYABLE or attempt == max_retries - 1:
                raise
            wait = float(exc.response.headers.get("retry-after", delay)) if exc.response else delay
            await asyncio.sleep(wait + random.uniform(0, 0.4))  # jitter avoids thundering herd
            delay = min(delay * 2, 8.0)
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(delay + random.uniform(0, 0.4))
            delay = min(delay * 2, 8.0)
    raise RuntimeError(f"segment failed after {max_retries} attempts: {seg_url}")


async def download_hls_ts(
    http: httpx.AsyncClient,
    master_url: str,
    headers: dict,
    quality: str,
    dest: Path,
    on_progress: ProgressCb = None,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    stats: dict | None = None,
) -> Path:
    """Download an HLS stream to a clean ``.ts`` file, stripping segment masks.

    Segments are fetched with a bounded concurrency window (``concurrency``) over
    a keepalive connection pool — the in-process equivalent of yt-dlp's
    ``--concurrent-fragments`` but without spawning a subprocess or requiring
    ffmpeg, and with byte-level control over the per-segment mask stripping.

    If ``stats`` is provided it is populated with timing/throughput metrics for
    benchmarking. Raises ``RuntimeError`` if the playlist is empty or the
    assembled stream fails the end-to-end TS integrity check (so callers can
    fall back to another server).
    """
    t0 = time.monotonic()
    media_url, media_txt = await resolve_media_playlist(http, master_url, headers, quality)
    if "#EXTINF" not in media_txt:
        raise RuntimeError("media playlist has no #EXTINF segments")
    segs = [
        urljoin(media_url, ln.strip())
        for ln in media_txt.splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    if not segs:
        raise RuntimeError("playlist contained no segments")

    sem = asyncio.Semaphore(concurrency)
    done = 0
    masked = 0

    async def grab(i: int, seg_url: str) -> tuple[int, bytes]:
        nonlocal done, masked
        async with sem:
            raw = await _fetch_segment(http, seg_url, headers)
            off = ts_start(raw)
            if off > 0:
                masked += 1
            done += 1
            if on_progress:
                await on_progress(done, len(segs))
            return i, raw[off:]

    results = await asyncio.gather(*(grab(i, su) for i, su in enumerate(segs)))
    clean = bytearray()
    for _, chunk in sorted(results):
        clean += chunk

    if not ts_is_clean(clean):
        raise RuntimeError("assembled stream failed TS integrity check")

    ts_path = dest.with_suffix(".ts")
    ts_path.write_bytes(clean)

    elapsed = time.monotonic() - t0
    if stats is not None:
        mb = len(clean) / 1048576
        stats.update(
            segments=len(segs),
            masked_segments=masked,
            bytes=len(clean),
            elapsed_s=round(elapsed, 2),
            throughput_mbps=round(mb / elapsed, 2) if elapsed else 0,
            concurrency=concurrency,
            media_url=media_url,
        )
    return ts_path


def find_ffmpeg() -> str | None:
    """Locate ffmpeg: PATH first, then the project-local ``tools/`` directory."""
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return found
    # src/nekofetch/sources/_hls.py -> project root is parents[3]
    for base in (Path(__file__).resolve().parents[3], Path.cwd()):
        for name in ("ffmpeg.exe", "ffmpeg"):
            cand = base / "tools" / name
            if cand.exists():
                return str(cand)
    return None


def find_ffprobe() -> str | None:
    """Locate ffprobe: PATH first, then the project-local ``tools/`` directory."""
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if found:
        return found
    for base in (Path(__file__).resolve().parents[3], Path.cwd()):
        for name in ("ffprobe.exe", "ffprobe"):
            cand = base / "tools" / name
            if cand.exists():
                return str(cand)
    return None


def maybe_remux(ts_path: Path, dest: Path) -> Path:
    """Losslessly remux ``.ts`` -> ``.mp4`` if ffmpeg exists; else keep the ``.ts``."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return ts_path
    mp4_path = dest.with_suffix(".mp4")
    proc = subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-i", str(ts_path),
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            str(mp4_path),
        ],
        capture_output=True,
    )
    if proc.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0:
        ts_path.unlink(missing_ok=True)
        return mp4_path
    log.warning("hls.remux.failed", error=proc.stderr.decode(errors="replace")[-300:])
    return ts_path


async def download_subtitles(
    http: httpx.AsyncClient,
    subtitles: list[tuple[str, str]],
    headers: dict,
    dest: Path,
) -> list[dict]:
    """Download VTT/SRT subtitle tracks as sidecar files next to ``dest``.

    ``subtitles`` is a list of ``(label, url)``. Returns metadata dicts describing
    each saved file (or the failure).
    """
    out: list[dict] = []

    async def one(idx: int, label: str, url: str) -> None:
        info: dict = {"label": label, "url": url, "index": idx}
        try:
            r = await http.get(url, headers=headers)
            r.raise_for_status()
            ext = ".vtt" if (".vtt" in url.lower() or b"WEBVTT" in r.content[:64]) else ".srt"
            safe = re.sub(r"[^\w.-]+", "_", label) or f"sub{idx}"
            sf = dest.parent / f"{dest.stem}.{safe}{ext}"
            sf.write_bytes(r.content)
            info.update(saved=str(sf), bytes=len(r.content), format=ext.lstrip("."),
                        is_vtt=r.content[:6] == b"WEBVTT")
        except Exception as exc:  # noqa: BLE001
            info.update(error=str(exc))
        out.append(info)

    await asyncio.gather(*(one(i, lbl, u) for i, (lbl, u) in enumerate(subtitles) if u))
    return out
