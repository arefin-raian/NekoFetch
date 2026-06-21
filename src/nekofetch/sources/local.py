"""LocalFileSource — reference authorized source.

Ingests a directory tree of content the operator owns. This is the canonical,
always-safe source: nothing leaves your machine and nothing is scraped.

Expected layout (flexible; parsed best-effort)::

    <library_root>/
        Naruto Shippuden/
            poster.jpg                      # optional artwork
            banner.jpg                      # optional artwork
            anime.json                      # optional metadata override
            Season 01/
                Naruto Shippuden - S01E001 [1080p] [Dual Audio].mkv
                Naruto Shippuden - S01E002 [720p] [Subbed].mkv

Season/episode/resolution/audio are detected from folder and file names; an optional
``anime.json`` per title can supply synopsis, genres, studio, alt titles, etc.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import aiofiles

from nekofetch.core.config import get_env
from nekofetch.core.exceptions import NotFound
from nekofetch.domain.enums import AudioType, ContentKind
from nekofetch.sources.base import (
    AnimeDetails,
    AnimeSource,
    AnimeStub,
    Episode,
    ProgressCallback,
    VideoVariant,
)

_VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov"}
_SXXEXX = re.compile(r"[Ss](\d{1,2})[\s._-]*[Ee](\d{1,4})")
_RES = re.compile(r"(\d{3,4})[pP]")
_AUDIO_HINTS = {
    "dual": AudioType.DUAL_AUDIO,
    "dual audio": AudioType.DUAL_AUDIO,
    "dub": AudioType.DUBBED,
    "dubbed": AudioType.DUBBED,
    "sub": AudioType.SUBBED,
    "subbed": AudioType.SUBBED,
}


def _detect_audio(name: str) -> AudioType:
    low = name.lower()
    for hint, audio in _AUDIO_HINTS.items():
        if hint in low:
            return audio
    return AudioType.SUBBED


def _detect_resolution(name: str) -> str | None:
    m = _RES.search(name)
    return f"{m.group(1)}p" if m else None


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class LocalFileSource(AnimeSource):
    name = "local"

    def __init__(self, library_root: str | Path | None = None) -> None:
        root = Path(library_root) if library_root else get_env().storage_path / "library"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    # ── internal helpers ──
    def _title_dir(self, source_ref: str) -> Path:
        for child in self.root.iterdir():
            if child.is_dir() and _slug(child.name) == source_ref:
                return child
        raise NotFound(f"No local title for {source_ref!r}")

    def _read_meta(self, title_dir: Path) -> dict:
        meta_file = title_dir / "anime.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _iter_episode_files(self, title_dir: Path):
        for path in sorted(title_dir.rglob("*")):
            if path.suffix.lower() in _VIDEO_EXTS:
                yield path

    # ── interface ──
    async def search(self, query: str) -> list[AnimeStub]:
        q = query.lower().strip()
        results: list[AnimeStub] = []
        for child in sorted(self.root.iterdir()):
            if child.is_dir() and q in child.name.lower():
                poster = child / "poster.jpg"
                results.append(
                    AnimeStub(
                        source_ref=_slug(child.name),
                        title=child.name,
                        poster_url=str(poster) if poster.exists() else None,
                    )
                )
        return results

    async def get_details(self, source_ref: str) -> AnimeDetails:
        title_dir = self._title_dir(source_ref)
        meta = self._read_meta(title_dir)

        seasons = {
            s for s, _ in (self._parse_locator(p) for p in self._iter_episode_files(title_dir))
        }
        episode_count = sum(1 for _ in self._iter_episode_files(title_dir))

        poster = title_dir / "poster.jpg"
        banner = title_dir / "banner.jpg"
        return AnimeDetails(
            source_ref=source_ref,
            title=meta.get("title", title_dir.name),
            alt_titles=meta.get("alt_titles", []),
            synopsis=meta.get("synopsis"),
            genres=meta.get("genres", []),
            studio=meta.get("studio"),
            release_date=meta.get("release_date"),
            poster_url=str(poster) if poster.exists() else None,
            banner_url=str(banner) if banner.exists() else None,
            season_count=len(seasons) or meta.get("season_count", 0),
            episode_count=episode_count,
        )

    def _parse_locator(self, path: Path) -> tuple[int, int]:
        """Return (season, episode) for a file, falling back to folder hints."""
        m = _SXXEXX.search(path.name)
        if m:
            return int(m.group(1)), int(m.group(2))
        # Fall back to "Season N" folder + positional episode index.
        season = 1
        sm = re.search(r"[Ss]eason[\s._-]*(\d{1,2})", str(path.parent))
        if sm:
            season = int(sm.group(1))
        em = re.search(r"(\d{1,4})", path.stem)
        return season, int(em.group(1)) if em else 0

    async def get_episodes(self, source_ref: str) -> list[Episode]:
        title_dir = self._title_dir(source_ref)
        episodes: list[Episode] = []
        for path in self._iter_episode_files(title_dir):
            season, number = self._parse_locator(path)
            kind = ContentKind.SEASON
            low = str(path).lower()
            if "movie" in low:
                kind = ContentKind.MOVIE
            elif "special" in low or "ova" in low:
                kind = ContentKind.SPECIAL
            episodes.append(
                Episode(
                    source_ref=str(path),  # path is the episode-native ref locally
                    season=season,
                    number=number,
                    title=path.stem,
                    kind=kind,
                )
            )
        return episodes

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        path = Path(episode_ref)
        if not path.exists():
            raise NotFound(f"Episode file missing: {episode_ref}")
        return [
            VideoVariant(
                source_ref=episode_ref,
                resolution=_detect_resolution(path.name) or "unknown",
                audio=_detect_audio(path.name),
                container=path.suffix.lstrip("."),
                size_bytes=path.stat().st_size,
            )
        ]

    async def download(
        self,
        variant: VideoVariant,
        dest: Path,
        *,
        on_progress: ProgressCallback | None = None,
        resume_state: dict | None = None,
    ) -> dict:
        """Resumable chunked copy from the local library into the working store."""
        src = Path(variant.source_ref)
        if not src.exists():
            raise NotFound(f"Source file missing: {src}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        total = src.stat().st_size
        already = dest.stat().st_size if (resume_state and dest.exists()) else 0
        chunk = (get_env().storage_path and 1024 * 1024)  # 1 MiB

        sha = hashlib.sha256()
        mode = "ab" if already else "wb"
        async with aiofiles.open(src, "rb") as fsrc, aiofiles.open(dest, mode) as fdst:
            if already:
                await fsrc.seek(already)
            written = already
            while True:
                data = await fsrc.read(chunk)
                if not data:
                    break
                await fdst.write(data)
                sha.update(data)
                written += len(data)
                if on_progress:
                    await on_progress(written, total)

        return {
            "checksum": sha.hexdigest() if not already else None,
            "bytes": written,
            "complete": written >= total,
        }
