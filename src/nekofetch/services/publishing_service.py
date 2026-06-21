"""Publishing service — the approval gate before content becomes user-visible.

Lists requests in READY state, and publishes / reprocesses / cancels them. Publishing
marks the request's files visible and (in a full build) deploys them to the bound
distribution bot.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NotFound
from nekofetch.domain.enums import RequestStatus
from nekofetch.infrastructure.database.postgres.models import DownloadJob, MediaFile, Request
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.request_repo import RequestRepository


@dataclass(slots=True)
class ApprovalSummary:
    code: str
    title: str
    files: int
    resolution: str | None
    audio: str | None
    has_thumbnail: bool


class PublishingService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def list_ready(self, *, limit: int = 10) -> list[ApprovalSummary]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            reqs = (
                await session.execute(
                    select(Request).where(Request.status == RequestStatus.READY).limit(limit)
                )
            ).scalars().all()
            out: list[ApprovalSummary] = []
            for req in reqs:
                files = await self._files_for_request(session, req.id)
                first = files[0] if files else None
                out.append(
                    ApprovalSummary(
                        code=req.code,
                        title=req.anime_title,
                        files=len(files),
                        resolution=first.resolution if first else None,
                        audio=(first.audio.value if first and first.audio else None),
                        has_thumbnail=any(
                            f.local_path and f.local_path.endswith(".thumb.jpg") for f in files
                        ),
                    )
                )
            return out

    async def _files_for_request(self, session, request_id: int) -> list[MediaFile]:
        job_ids = (
            await session.execute(
                select(DownloadJob.id).where(DownloadJob.request_id == request_id)
            )
        ).scalars().all()
        if not job_ids:
            return []
        return list(
            (await session.execute(select(MediaFile).where(MediaFile.job_id.in_(job_ids))))
            .scalars()
            .all()
        )

    async def publish(self, code: str) -> int:
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            files = await self._files_for_request(session, req.id)
            for f in files:
                f.published = True
            req.status = RequestStatus.PUBLISHED
            count = len(files)

        from nekofetch.services.analytics_service import AnalyticsService

        await AnalyticsService(self._c).record(
            "publish", anime_doc_id=req.anime_doc_id, data={"code": code, "files": count}
        )
        # Full build: deploy published files to the bound distribution bot here.
        return count

    async def reprocess(self, code: str) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            job = (
                await session.execute(
                    select(DownloadJob).where(DownloadJob.request_id == req.id)
                )
            ).scalars().first()
            job_id = job.id if job else None
        if job_id is not None:
            from nekofetch.services.processing.pipeline import ProcessingPipeline

            await ProcessingPipeline(self._c).run_for_job(job_id)

    async def cancel(self, code: str) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            req.status = RequestStatus.REJECTED
