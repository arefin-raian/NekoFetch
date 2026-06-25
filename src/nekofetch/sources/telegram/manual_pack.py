"""Manual Telegram fallback — process an admin-provided, already-ordered pack.

When an anime isn't on AnimeFair, Telegram is the preferred manual fallback: an
admin hands us the anime name, a quality, and a complete pack of files **already
in episode order** (file #1 = Episode 1, …). No scraping, no fragile order
detection — we simply:

    1. take the files in the given order,
    2. rename them to our standard,
    3. normalize metadata + extract/clean/brand subtitles (shared pipeline),
    4. apply our caption,
    5. (optionally) upload the finished files to a target chat.

Because the order is provided, naming heuristics are not relied upon; if anything
is ambiguous the admin clarifies by simply ordering the files correctly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from nekofetch.core.logging import get_logger
from nekofetch.sources._normalize import (
    BRAND_HANDLE,
    normalize_release,
    probe_audio_config,
)

log = get_logger(__name__)

ProgressCb = Callable[[int, int], Awaitable[None]] | None


def _safe(s: str) -> str:
    """Filesystem-safe component (keep it readable)."""
    return "".join(c for c in s if c not in '<>:"/\\|?*').strip()


def _q(quality: str) -> str:
    return quality if quality.endswith("p") or not quality[:1].isdigit() else f"{quality}p"


def standard_stem(anime: str, season: int, episode: int, quality: str,
                  audio_config: str) -> str:
    """Canonical stem, e.g. 'Tokyo Ghoul S01E01 [Dual] [1080p] @AniXWeebs'."""
    return (f"{_safe(anime)} S{season:02d}E{episode:02d} "
            f"[{audio_config}] [{_q(quality)}] {BRAND_HANDLE}")


def our_caption(anime: str, season: int, episode: int, quality: str,
                audio_config: str) -> str:
    """Our standard delivery caption (replaces any original caption)."""
    return (f"🎬 {anime}\n"
            f"📺 Season {season} • Episode {episode:02d} • {_q(quality)} • {audio_config}\n\n"
            f"⚡ Brought to you by {BRAND_HANDLE}")


async def process_pack(
    anime: str,
    quality: str,
    ordered_files: list[str | Path],
    out_dir: str | Path,
    *,
    season: int = 1,
    start_episode: int = 1,
    audio_config: str | None = None,
    pool=None,
    upload_to: int | str | None = None,
    on_progress: ProgressCb = None,
) -> dict:
    """Process one quality's ordered pack into finished, branded releases.

    ``ordered_files`` MUST already be in episode order (index 0 → start_episode).
    ``audio_config`` (Dual/Multi/Sub/Dub) overrides per-file auto-detection — pass
    it when the admin specifies the config; otherwise it's detected from each
    file's audio streams and any uncertain detection is flagged for confirmation.
    Returns a manifest of every processed episode. If ``pool`` and ``upload_to``
    are given, each finished file is uploaded with our caption.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - one-time setup
    episodes: list[dict] = []

    for i, src in enumerate(ordered_files):
        ep = start_episode + i
        src_path = Path(src)
        rec: dict = {"episode": ep, "season": season, "quality": quality,
                     "source": src_path.name}
        if not src_path.exists():  # noqa: ASYNC240 - cheap existence check
            rec["error"] = "source file missing"
            episodes.append(rec)
            continue

        # Audio config: admin override, else detect from the file's streams.
        if audio_config:
            config, certain = audio_config, True
        else:
            config, certain = probe_audio_config(src_path)
        rec["audio_config"] = config
        if not certain:
            rec["audio_config_uncertain"] = True   # admin should confirm/override

        stem = standard_stem(anime, season, ep, quality, config)
        title = f"{anime} - S{season:02d}E{ep:02d}"
        try:
            norm = await normalize_release(src_path, out / stem, title=title,
                                           audio_config=config)
            final = Path(norm["path"])
            rec.update(path=str(final), name=final.name, bytes=norm["bytes"],
                       audio=norm["audio"], subtitles=norm["subtitles"])
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"normalize failed: {exc}"
            episodes.append(rec)
            log.warning("manual.normalize.failed", episode=ep, error=str(exc))
            continue

        if pool is not None and upload_to is not None:
            try:
                rec["uploaded"] = await _upload(
                    pool, upload_to, final,
                    our_caption(anime, season, ep, quality, config), on_progress,
                )
            except Exception as exc:  # noqa: BLE001
                rec["upload_error"] = str(exc)
                log.warning("manual.upload.failed", episode=ep, error=str(exc))

        episodes.append(rec)
        if on_progress:
            await on_progress(i + 1, len(ordered_files))

    ok = sum(1 for e in episodes if e.get("path") and "error" not in e)
    return {"anime": anime, "season": season, "quality": quality,
            "total": len(ordered_files), "processed": ok, "episodes": episodes}


async def _upload(pool, chat, path: Path, caption: str, on_progress: ProgressCb) -> bool:
    """Upload one finished file to ``chat`` via the userbot pool."""
    async def run(client) -> bool:
        async def _p(cur: int, tot: int) -> None:
            if on_progress:
                await on_progress(cur, tot)
        await client.send_document(chat, str(path), caption=caption,
                                   progress=_p if on_progress else None)
        return True
    return await pool.execute(run)
