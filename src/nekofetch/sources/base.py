"""The ``AnimeSource`` interface and its data models.

A source turns an authorized origin (local files, a licensed API) into a uniform
catalog NekoFetch can search, inspect, and download from. Implementations must only
expose content the operator is licensed/authorized to distribute.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from nekofetch.domain.enums import AudioType, ContentKind


@dataclass(slots=True)
class AnimeStub:
    """Lightweight search result."""

    source_ref: str          # source-native identifier
    title: str
    poster_url: str | None = None
    year: int | None = None


@dataclass(slots=True)
class AnimeDetails:
    source_ref: str
    title: str
    alt_titles: list[str] = field(default_factory=list)
    synopsis: str | None = None
    genres: list[str] = field(default_factory=list)
    studio: str | None = None
    release_date: str | None = None
    poster_url: str | None = None
    banner_url: str | None = None
    season_count: int = 0
    episode_count: int = 0


@dataclass(slots=True)
class Episode:
    source_ref: str
    season: int
    number: int
    title: str | None = None
    kind: ContentKind = ContentKind.SEASON


@dataclass(slots=True)
class VideoVariant:
    """A concrete downloadable rendition of an episode."""

    source_ref: str
    resolution: str                 # e.g. "1080p"
    audio: AudioType = AudioType.SUBBED
    languages: list[str] = field(default_factory=list)
    subtitles: list[str] = field(default_factory=list)
    container: str | None = None    # mkv / mp4 ...
    size_bytes: int | None = None


# Called repeatedly during a download with (downloaded_bytes, total_bytes).
ProgressCallback = Callable[[int, int], Awaitable[None]]


class AnimeSource(ABC):
    """Base class for all authorized content sources."""

    #: Stable identifier used in config (`sources.enabled`) and request records.
    name: str = "base"

    @abstractmethod
    async def search(self, query: str) -> list[AnimeStub]:
        """Search the catalog for titles matching ``query``."""

    @abstractmethod
    async def get_details(self, source_ref: str) -> AnimeDetails:
        """Full metadata for a title (synopsis, genres, studio, season counts)."""

    @abstractmethod
    async def get_episodes(self, source_ref: str) -> list[Episode]:
        """All episodes (seasons/movies/specials detected)."""

    @abstractmethod
    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        """Available renditions: resolutions, languages, audio, subtitles."""

    @abstractmethod
    async def download(
        self,
        variant: VideoVariant,
        dest: Path,
        *,
        on_progress: ProgressCallback | None = None,
        resume_state: dict | None = None,
    ) -> dict:
        """Download ``variant`` to ``dest``.

        Must be resumable: accept and return a ``resume_state`` dict so an interrupted
        download can continue. Should invoke ``on_progress`` periodically. Returns the
        final resume/metadata state (e.g. checksum, bytes written).
        """

    async def close(self) -> None:  # pragma: no cover - optional cleanup hook
        """Release any held resources (HTTP clients, handles)."""
        return None
