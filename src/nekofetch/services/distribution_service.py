"""Distribution service — season-centric delivery with protected/temporary access.

Users receive a *season package* (a batch of indexed files), not individual episodes by
default. Access is granted via tokens that can be protected (no forwarding), time-limited
(temporary links), and/or auto-deleted after a configurable window — all per config.

Token generation is deterministic-free (uuid4) and stored in Postgres ``access_links``.
Expiry/auto-delete are enforced both lazily (on use) and actively (scheduler sweeps).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.exceptions import LinkExpired, NotFound
from nekofetch.domain.enums import AudioType
from nekofetch.infrastructure.database.postgres.models import AccessLink, MediaFile
from nekofetch.infrastructure.database.postgres.session import session_scope


@dataclass(slots=True)
class SeasonPackage:
    anime_doc_id: str
    season: int
    resolution: str | None
    audio: AudioType | None
    file_ids: list[int]
    episode_span: tuple[int, int] | None


class DistributionService:
    def __init__(self, container: Container) -> None:
        self._c = container

    # ── catalog queries (published content only) ──
    async def published_titles(self, *, limit: int = 50) -> list[tuple[str, str]]:
        """Distinct (anime_doc_id, title) among published files."""
        from nekofetch.infrastructure.database.postgres.models import Request

        async with session_scope(self._c.pg_sessionmaker) as session:
            doc_ids = (
                await session.execute(
                    select(MediaFile.anime_doc_id)
                    .where(MediaFile.published.is_(True))
                    .distinct()
                    .limit(limit)
                )
            ).scalars().all()
            out: list[tuple[str, str]] = []
            for doc_id in doc_ids:
                title = (
                    await session.execute(
                        select(Request.anime_title)
                        .where(Request.anime_doc_id == doc_id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                out.append((doc_id, title or doc_id))
            return out

    async def seasons_for(self, anime_doc_id: str) -> list[int]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (
                await session.execute(
                    select(MediaFile.season)
                    .where(MediaFile.anime_doc_id == anime_doc_id, MediaFile.published.is_(True))
                    .distinct()
                )
            ).scalars().all()
            return sorted(s for s in rows if s is not None)

    async def variants_for(self, anime_doc_id: str, season: int) -> list[tuple[str, str]]:
        """Distinct (resolution, audio) pairs available for a published season."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (
                await session.execute(
                    select(MediaFile.resolution, MediaFile.audio)
                    .where(
                        MediaFile.anime_doc_id == anime_doc_id,
                        MediaFile.season == season,
                        MediaFile.published.is_(True),
                    )
                    .distinct()
                )
            ).all()
            return [(r[0] or "unknown", (r[1].value if r[1] else "subbed")) for r in rows]

    async def build_season_package(
        self,
        anime_doc_id: str,
        season: int,
        *,
        resolution: str | None = None,
        audio: AudioType | None = None,
    ) -> SeasonPackage:
        async with session_scope(self._c.pg_sessionmaker) as session:
            stmt = select(MediaFile).where(
                MediaFile.anime_doc_id == anime_doc_id,
                MediaFile.season == season,
                MediaFile.published.is_(True),
            )
            if resolution:
                stmt = stmt.where(MediaFile.resolution == resolution)
            if audio:
                stmt = stmt.where(MediaFile.audio == audio)
            files = list((await session.execute(stmt.order_by(MediaFile.episode))).scalars().all())
            if not files:
                raise NotFound(f"No published files for {anime_doc_id} S{season}")
            episodes = [f.episode for f in files if f.episode is not None]
            span = (min(episodes), max(episodes)) if episodes else None
            return SeasonPackage(
                anime_doc_id=anime_doc_id,
                season=season,
                resolution=resolution,
                audio=audio,
                file_ids=[f.id for f in files],
                episode_span=span,
            )

    async def create_access_link(
        self,
        package: SeasonPackage,
        *,
        user_id: int | None = None,
        expiry_minutes: int | None = None,
        max_uses: int | None = None,
    ) -> AccessLink:
        cfg = self._c.config.distribution
        token = secrets.token_urlsafe(16)
        expires_at = None
        if cfg.temporary_links and self._c.config.features.temporary_links:
            minutes = expiry_minutes if expiry_minutes is not None else cfg.link_expiry_minutes
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        async with session_scope(self._c.pg_sessionmaker) as session:
            link = AccessLink(
                token=token,
                user_id=user_id,
                payload={
                    "anime_doc_id": package.anime_doc_id,
                    "season": package.season,
                    "resolution": package.resolution,
                    "audio": package.audio.value if package.audio else None,
                    "file_ids": package.file_ids,
                    "protected": cfg.protect_content,
                },
                expires_at=expires_at,
                max_uses=max_uses,
            )
            session.add(link)
            await session.flush()
            session.expunge(link)
            return link

    async def redeem(self, token: str) -> dict:
        """Validate a link and return its payload, enforcing expiry & use limits."""
        now = datetime.now(timezone.utc)
        async with session_scope(self._c.pg_sessionmaker) as session:
            link = (
                await session.execute(select(AccessLink).where(AccessLink.token == token))
            ).scalar_one_or_none()
            if link is None or link.revoked:
                raise NotFound("link")
            if link.expires_at is not None and link.expires_at < now:
                raise LinkExpired(token)
            if link.max_uses is not None and link.uses >= link.max_uses:
                raise LinkExpired(token)
            link.uses += 1
            return dict(link.payload)

    async def sweep_expired(self) -> int:
        """Scheduler job: revoke links past their expiry. Returns count revoked."""
        now = datetime.now(timezone.utc)
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = (
                await session.execute(
                    select(AccessLink).where(
                        AccessLink.revoked.is_(False), AccessLink.expires_at < now
                    )
                )
            ).scalars().all()
            for link in rows:
                link.revoked = True
            return len(rows)
