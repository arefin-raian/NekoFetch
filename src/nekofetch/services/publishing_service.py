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

    async def upload_to_storage(self, code: str, *, on_progress=None) -> int:
        """Upload a request's processed files to the storage (DB) channel as packs.

        This is **automatic** — it runs straight after processing, independent of
        the main-channel publish/approval gate. Putting verified files into the
        database channel is just part of the pipeline; "publishing" (posting to the
        main channel, index, etc.) is a separate, deliberate action.
        """
        from pathlib import Path

        verify_on = self._c.config.processing.verify_files
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            files = await self._files_for_request(session, req.id)
            # Upload every file that exists on disk. The verify GATE only applies when
            # verification is actually enabled — otherwise files are never flagged
            # verified and NOTHING would ever reach the DB channel (the bug where DB
            # uploads "didn't consistently happen").
            files = [
                f for f in files
                if f.local_path and Path(f.local_path).exists()
                and (f.verified or not verify_on)
            ]
            anime_doc_id = req.anime_doc_id or req.source_ref
            title = req.anime_title
            snapshot = [
                {"season": f.season, "episode": f.episode, "resolution": f.resolution,
                 "audio": f.audio, "path": f.local_path}
                for f in files
            ]

        await self._upload_packs(anime_doc_id, title, snapshot, on_progress=on_progress)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "download", "stored", code=code, anime=title, files=len(snapshot),
        )
        return len(snapshot)

    async def publish(self, code: str) -> int:
        """Make stored content user-visible: create bot → post to main channel + index.

        Correct flow: storage → bot creation/configuration → main channel post →
        redirect via Download button to the bot.
        """
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            user_id = req.user_id
            files = await self._files_for_request(session, req.id)
            for f in files:
                f.published = True
            req.status = RequestStatus.PUBLISHED
            count = len(files)
            anime_doc_id = req.anime_doc_id or req.source_ref
            title = req.anime_title
            first = next((f for f in files if f.local_path), None)
            res = first.resolution if first else None
            aud = first.audio.value if first and first.audio else None

        from nekofetch.services.analytics_service import AnalyticsService

        await AnalyticsService(self._c).record(
            "publish", anime_doc_id=anime_doc_id, data={"code": code, "files": count}
        )

        # Step 1: Create distribution bot (if auto-create is enabled and feature is on).
        if self._c.config.features.distribution_bots and self._c.config.bot.auto_create_on_publish:
            from nekofetch.services.bot_orchestrator import BotOrchestratorService

            await BotOrchestratorService(self._c).ensure_bot_for_anime(anime_doc_id)

        # Step 2: Post to main channel (the Download button now has the bot username).
        from nekofetch.services.index_channel_service import IndexChannelService
        from nekofetch.services.main_channel_service import MainChannelService

        await MainChannelService(self._c).publish(anime_doc_id)
        await IndexChannelService(self._c).refresh_letter(
            IndexChannelService.letter_of(title)
        )

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "publish", "approved", code=code, anime=title, files=count,
            audio=aud, resolution=res,
        )

        # Refresh database stats (pinned message in index channel)
        from nekofetch.services.stats_service import StatsService

        await StatsService(self._c).refresh()

        if user_id:
            from nekofetch.services.notification_service import NotificationService
            await NotificationService(self._c).request_published(user_id, title, code)
        return count

    async def _upload_packs(self, anime_doc_id: str, title: str, files: list[dict],
                            *, on_progress=None) -> None:
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

        from nekofetch.services.processing.stages import POSTER_THUMB_NAME

        for (season, resolution, audio), items in groups.items():
            if not resolution or audio is None:
                continue
            items.sort(key=lambda x: (x["episode"] or 0))
            episodes = [i["episode"] for i in items if i["episode"] is not None]
            # Find the poster the thumbnail stage wrote — it's a sibling of the media
            # files. Search each item's folder so EVERY pack gets the thumbnail even
            # if the first item happens to live elsewhere.
            poster = next(
                (p for i in items
                 if (p := Path(i["path"]).with_name(POSTER_THUMB_NAME)).exists()),
                None,
            )
            try:
                await storage.upload_pack(
                    storage.key_from(anime_doc_id, season, resolution, audio),
                    title=title,
                    file_paths=[Path(i["path"]) for i in items],
                    episode_from=min(episodes) if episodes else None,
                    episode_to=max(episodes) if episodes else None,
                    thumb=poster,
                    on_progress=on_progress,
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
