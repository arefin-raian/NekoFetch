"""Download-queue repository."""

from __future__ import annotations

from sqlalchemy import func, select

from nekofetch.domain.enums import JobStatus
from nekofetch.infrastructure.database.postgres.models import DownloadJob
from nekofetch.infrastructure.repositories.base import BaseRepository


class QueueRepository(BaseRepository[DownloadJob]):
    model = DownloadJob

    async def next_queued(self) -> DownloadJob | None:
        """Highest-priority queued job (lower priority value = sooner)."""
        result = await self.session.execute(
            select(DownloadJob)
            .where(DownloadJob.status == JobStatus.QUEUED)
            .order_by(DownloadJob.priority.asc(), DownloadJob.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def active(self) -> list[DownloadJob]:
        result = await self.session.execute(
            select(DownloadJob)
            .where(DownloadJob.status.in_({JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.PAUSED}))
            .order_by(DownloadJob.priority.asc(), DownloadJob.created_at.asc())
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: JobStatus) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(DownloadJob).where(DownloadJob.status == status)
        )
        return int(result.scalar_one())
