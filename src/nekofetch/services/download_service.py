"""Download worker — executes queued jobs through authorized sources.

Runs as a background loop (started by the bot manager / scheduler). For each job it:

1. claims the next queued job (respecting ``concurrent_downloads``),
2. resolves the request's source + episode variants,
3. downloads each variant resumably, publishing live progress to Redis and Postgres,
4. records :class:`MediaFile` rows, then advances the request to PROCESSING,
5. retries with backoff on failure, preserving ``resume_state``.

Byte-moving itself is delegated to the source's ``download`` (e.g. ``LocalFileSource``).
"""

from __future__ import annotations

import asyncio
import time

from nekofetch.core.container import Container
from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType, JobStatus, RequestStatus
from nekofetch.infrastructure.database.postgres.models import DownloadJob, MediaFile
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.database.redis.progress import ProgressSnapshot
from nekofetch.infrastructure.repositories.queue_repo import QueueRepository
from nekofetch.infrastructure.repositories.request_repo import RequestRepository

log = get_logger(__name__)


class DownloadWorker:
    def __init__(self, container: Container) -> None:
        self._c = container
        self._sem = asyncio.Semaphore(container.config.downloads.concurrent_downloads)
        self._running = False
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        self._running = True
        log.info("download.worker.start", concurrency=self._c.config.downloads.concurrent_downloads)
        while self._running:
            job_id = await self._claim_next()
            if job_id is None:
                await asyncio.sleep(poll_interval)
                continue
            task = asyncio.create_task(self._guarded(job_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        self._running = False
        for task in list(self._tasks):
            task.cancel()

    async def _claim_next(self) -> int | None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = QueueRepository(session)
            job = await repo.next_queued()
            if job is None:
                return None
            job.status = JobStatus.RUNNING
            job.attempts += 1
            return job.id

    async def _guarded(self, job_id: int) -> None:
        async with self._sem:
            try:
                await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await self._handle_failure(job_id, exc)

    async def _process_job(self, job_id: int) -> None:
        cfg = self._c.config.downloads
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            req = await RequestRepository(session).get(job.request_id)
            source = self._c.sources.get(req.source)
            episodes = await source.get_episodes(req.source_ref)
            if req.season is not None:
                episodes = [e for e in episodes if e.season == req.season]
            if req.episodes:
                episodes = [e for e in episodes if e.number in set(req.episodes)]
            job.started_at = _now()

        targets = self._targets(req)  # (resolution, audio) combos to acquire

        # For each episode, acquire every requested quality x language combo. Combos that
        # the source doesn't offer are skipped (not an error).
        for ep in episodes:
            variants = await source.get_variants(ep.source_ref)
            for resolution, audio in targets:
                variant = _select_variant(
                    variants, resolution, audio, self._c.config.acquisition.require_english_subs
                )
                if variant is None:
                    continue
                dest = (
                    self._c.env.storage_path
                    / "work"
                    / f"{req.source_ref}"
                    / f"S{ep.season:02d}E{ep.number:03d}_{variant.resolution}_{variant.audio.value}"
                    f".{variant.container or 'mkv'}"
                )

                start = time.monotonic()
                last_emit = 0.0

                async def on_progress(done: int, total: int, _ep=ep, _start=start,
                                      _v=variant) -> None:
                    nonlocal last_emit
                    now = time.monotonic()
                    if now - last_emit < cfg.progress_update_interval_seconds:
                        return
                    last_emit = now
                    elapsed = max(now - _start, 1e-6)
                    speed = done / elapsed
                    pct = (done / total * 100) if total else 0.0
                    eta = int((total - done) / speed) if speed > 0 else None
                    if self._c.progress:
                        await self._c.progress.set(
                            ProgressSnapshot(
                                job_id=job_id,
                                status=JobStatus.RUNNING.value,
                                progress=pct,
                                speed_bps=speed,
                                downloaded_bytes=done,
                                total_bytes=total,
                                current_episode=_ep.number,
                                eta_seconds=eta,
                                label=f"S{_ep.season:02d}E{_ep.number:03d} {_v.resolution} {_v.audio.value}",
                            )
                        )

                result = await self._download_with_retry(
                    source, variant, dest, on_progress,
                    cfg.retry_attempts, cfg.retry_backoff_seconds,
                )
                await self._record_file(job_id, req, ep, variant, dest, result)

        await self._complete(job_id)

    def _targets(self, req) -> list[tuple[str | None, AudioType]]:
        """Resolve the (resolution, audio) combos to acquire for a request.

        A fully-specified request yields one combo; an unspecified one fans out into the
        configured acquisition matrix (all resolutions x english/japanese).
        """
        acq = self._c.config.acquisition
        if req.resolution and req.audio:
            return [(req.resolution, req.audio)]
        resolutions = [req.resolution] if req.resolution else list(acq.resolutions)
        if req.audio:
            audios = [req.audio]
        else:
            audios = [a for a in (_audio_for_language(lang) for lang in acq.languages) if a]
        return [(r, a) for r in resolutions for a in audios]

    async def _download_with_retry(
        self, source, variant, dest, on_progress, attempts, backoff
    ) -> dict:
        resume_state: dict | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await source.download(
                    variant, dest, on_progress=on_progress, resume_state=resume_state
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("download.retry", attempt=attempt, error=str(exc))
                resume_state = {"partial": True} if self._c.config.downloads.resume_interrupted else None
                if attempt >= attempts:
                    raise
                await asyncio.sleep(backoff * attempt)
        return {}

    async def _record_file(self, job_id, req, ep, variant, dest, result) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            session.add(
                MediaFile(
                    job_id=job_id,
                    anime_doc_id=req.anime_doc_id or req.source_ref,
                    season=ep.season,
                    episode=ep.number,
                    resolution=variant.resolution,
                    audio=variant.audio,
                    original_name=ep.title,
                    local_path=str(dest),
                    size_bytes=int(result.get("bytes", 0)),
                    checksum=result.get("checksum"),
                    container=variant.container,
                    verified=False,
                )
            )

    async def _complete(self, job_id: int) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            job.status = JobStatus.COMPLETED
            job.progress = 100.0
            job.finished_at = _now()
            req = await RequestRepository(session).get(job.request_id)
            if req:
                req.status = RequestStatus.PROCESSING
                user_id = req.user_id
                title = req.anime_title
                code = req.code
                needs_approval = self._c.config.processing.require_approval_before_publish
            else:
                user_id = None
                title = ""
                code = ""
                needs_approval = False
        log.info("download.job.complete", job_id=job_id)
        if user_id:
            from nekofetch.services.notification_service import NotificationService
            await NotificationService(self._c).download_complete(user_id, title, code)
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event("download", "complete", job=job_id)
        from nekofetch.services.processing.pipeline import ProcessingPipeline

        try:
            await ProcessingPipeline(self._c).run_for_job(job_id)
            await LogChannelService(self._c).event("processing", "complete", job=job_id)
            if user_id:
                from nekofetch.services.notification_service import NotificationService
                await NotificationService(self._c).processing_complete(user_id, title, code, needs_approval=needs_approval)
        except Exception as exc:
            log.error("download.processing.failed", job_id=job_id, error=str(exc))
            await LogChannelService(self._c).event("error", "processing_failed", job=job_id, error=str(exc))
            if user_id:
                from nekofetch.services.notification_service import NotificationService
                await NotificationService(self._c).processing_failed(user_id, title, code, str(exc))

    async def _handle_failure(self, job_id: int, exc: Exception) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED
            job.error = str(exc)
            req = await RequestRepository(session).get(job.request_id)
            user_id = req.user_id if req else None
            title = req.anime_title if req else ""
            code = req.code if req else ""
        log.error("download.job.failed", job_id=job_id, error=str(exc))
        if user_id:
            from nekofetch.services.notification_service import NotificationService
            await NotificationService(self._c).download_failed(user_id, title, code, str(exc))
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event("error", "download_failed", job=job_id, error=str(exc))


def _audio_for_language(language: str) -> AudioType | None:
    return {
        "english": AudioType.DUBBED,
        "japanese": AudioType.SUBBED,
        "dual": AudioType.DUAL_AUDIO,
        "dual_audio": AudioType.DUAL_AUDIO,
    }.get(language.lower())


def _select_variant(variants, resolution, audio, require_english_subs: bool):
    """Pick the variant matching resolution + audio, preferring English subtitles.

    Returns None when the exact combo isn't offered (so unavailable combos are skipped).
    """
    cands = list(variants)
    if resolution:
        cands = [v for v in cands if v.resolution == resolution]
    if audio is not None:
        cands = [v for v in cands if v.audio == audio]
    if not cands:
        return None
    if require_english_subs:
        with_en = [
            v for v in cands
            if not v.subtitles or any("en" in s.lower() for s in v.subtitles)
        ]
        if with_en:
            cands = with_en
    return cands[0]


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
