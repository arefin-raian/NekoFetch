"""Processing pipeline orchestrator.

Runs the enabled stages in order for a completed download job, then moves the request
to READY (awaiting publish approval) or PUBLISHED (if approval isn't required).
"""

from __future__ import annotations

from sqlalchemy import select

from nekofetch.core.container import Container
from nekofetch.core.exceptions import ProcessingError
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import JobStatus, RequestStatus
from nekofetch.infrastructure.database.postgres.models import DownloadJob, MediaFile
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.request_repo import RequestRepository
from nekofetch.services.processing.base import StageContext
from nekofetch.services.processing.stages import default_stages

log = get_logger(__name__)


class ProcessingPipeline:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def run_for_job(self, job_id: int) -> StageContext:
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                raise ProcessingError(f"job {job_id} not found")
            req = await RequestRepository(session).get(job.request_id)
            files = list(
                (await session.execute(select(MediaFile).where(MediaFile.job_id == job_id)))
                .scalars()
                .all()
            )
            ctx = StageContext(job_id=job_id, request=req, files=files)

            for stage in default_stages(self._c):
                if not stage.enabled():
                    note = f"{stage.stage.value}: skipped (disabled)"
                    ctx.notes.append(note)
                    continue
                log.info("processing.stage", job_id=job_id, stage=stage.stage.value)
                from nekofetch.services.log_channel_service import LogChannelService

                await LogChannelService(self._c).event(
                    "processing", stage.stage.value, job=job_id,
                    anime=req.anime_title if req else None,
                )
                try:
                    await stage.process(ctx)
                    await LogChannelService(self._c).event(
                        "processing", f"{stage.stage.value}_done", job=job_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    job.status = JobStatus.FAILED
                    await LogChannelService(self._c).event(
                        "error", f"{stage.stage.value}_failed", job=job_id,
                        error=str(exc)[:300],
                    )
                    raise ProcessingError(f"{stage.stage.value}: {exc}") from exc

            if self._c.config.processing.require_approval_before_publish:
                req.status = RequestStatus.READY
            else:
                req.status = RequestStatus.PUBLISHED
                for f in files:
                    f.published = True

        log.info("processing.complete", job_id=job_id, notes=len(ctx.notes))
        return ctx
