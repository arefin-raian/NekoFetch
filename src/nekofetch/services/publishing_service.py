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
            anime_doc_id = req.anime_doc_id or req.source_ref
            title = req.anime_title
            # Snapshot file rows for upload outside the session.
            snapshot = [
                {"season": f.season, "episode": f.episode, "resolution": f.resolution,
                 "audio": f.audio, "path": f.local_path}
                for f in files if f.local_path
            ]

        from nekofetch.services.analytics_service import AnalyticsService

        await AnalyticsService(self._c).record(
            "publish", anime_doc_id=anime_doc_id, data={"code": code, "files": count}
        )
        await self._upload_packs(anime_doc_id, title, snapshot)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "publish", "approved", code=code, anime=title, files=count
        )
        return count

    async def _upload_packs(self, anime_doc_id: str, title: str, files: list[dict]) -> None:
        """Group published files by (season, resolution, audio) and upload each as a pack."""
        if not self._c.config.storage_channel.enabled or not files:
            return
        from pathlib import Path

        from nekofetch.core.exceptions import FeatureDisabled
        from nekofetch.services.storage_channel_service import StorageChannelService

        storage = StorageChannelService(self._c)
        groups: dict[tuple, list[dict]] = {}
        for f in files:
            groups.setdefault((f["season"], f["resolution"], f["audio"]), []).append(f)

        for (season, resolution, audio), items in groups.items():
            if not resolution or audio is None:
                continue
            items.sort(key=lambda x: (x["episode"] or 0))
            episodes = [i["episode"] for i in items if i["episode"] is not None]
            try:
                await storage.upload_pack(
                    storage.key_from(anime_doc_id, season, resolution, audio),
                    title=title,
                    file_paths=[Path(i["path"]) for i in items],
                    episode_from=min(episodes) if episodes else None,
                    episode_to=max(episodes) if episodes else None,
                )
            except FeatureDisabled:
                return
            except Exception as exc:  # noqa: BLE001 - one pack failing shouldn't abort publish
                from nekofetch.core.logging import get_logger

                get_logger(__name__).warning("publish.upload_pack.failed",
                                             season=season, resolution=resolution, error=str(exc))

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
