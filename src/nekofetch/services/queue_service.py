"""Queue service — turns approved requests into download jobs and reports the queue.

Provides the data behind the admin Downloads Queue and the live dashboard. Actual
byte-moving is done by the download worker (``download_service``).
"""

from __future__ import annotations

from dataclasses import dataclass

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NotFound
from nekofetch.domain.enums import JobStatus, RequestStatus
from nekofetch.infrastructure.database.postgres.models import DownloadJob
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.queue_repo import QueueRepository
from nekofetch.infrastructure.repositories.request_repo import RequestRepository


@dataclass(slots=True)
class QueueRow:
    job_id: int
    anime_title: str
    requested_by: str
    status: str
    progress: float
    speed_bps: float
    eta_seconds: int | None


class QueueService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def enqueue(self, request_code: str, *, priority: int = 100) -> int:
        async with session_scope(self._c.pg_sessionmaker) as session:
            requests = RequestRepository(session)
            req = await requests.get_by_code(request_code)
            if req is None:
                raise NotFound(request_code)
            job = DownloadJob(request_id=req.id, status=JobStatus.QUEUED, priority=priority)
            session.add(job)
            req.status = RequestStatus.QUEUED
            await session.flush()
            return job.id

    async def dashboard(self, *, limit: int | None = None) -> list[QueueRow]:
        limit = limit or self._c.config.queue.max_visible
        async with session_scope(self._c.pg_sessionmaker) as session:
            jobs = await QueueRepository(session).active()
            rows: list[QueueRow] = []
            for job in jobs[:limit]:
                req = await RequestRepository(session).get(job.request_id)
                # Prefer fast live progress from Redis when present.
                snap = await self._c.progress.get(job.id) if self._c.progress else None
                rows.append(
                    QueueRow(
                        job_id=job.id,
                        anime_title=req.anime_title if req else "—",
                        requested_by=str(req.user_id) if req else "—",
                        status=(snap.status if snap else job.status.value),
                        progress=(snap.progress if snap else job.progress),
                        speed_bps=(snap.speed_bps if snap else job.speed_bps),
                        eta_seconds=(snap.eta_seconds if snap else job.eta_seconds),
                    )
                )
            return rows

    async def counts(self) -> dict[str, int]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = QueueRepository(session)
            return {
                "queued": await repo.count_by_status(JobStatus.QUEUED),
                "running": await repo.count_by_status(JobStatus.RUNNING),
                "failed": await repo.count_by_status(JobStatus.FAILED),
            }
