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
from nekofetch.domain.enums import JobStatus, RequestStatus
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

        # Download each episode's chosen variant.
        for ep in episodes:
            variants = await source.get_variants(ep.source_ref)
            variant = _pick_variant(variants, req.resolution, req.audio) or variants[0]
            dest = (
                self._c.env.storage_path
                / "work"
                / f"{req.source_ref}"
                / f"S{ep.season:02d}E{ep.number:03d}.{variant.container or 'mkv'}"
            )

            start = time.monotonic()
            last_emit = 0.0

            async def on_progress(done: int, total: int, _ep=ep, _start=start) -> None:
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
                            label=f"S{_ep.season:02d}E{_ep.number:03d}",
                        )
                    )

            result = await self._download_with_retry(
                source, variant, dest, on_progress, cfg.retry_attempts, cfg.retry_backoff_seconds
            )
            await self._record_file(job_id, req, ep, variant, dest, result)

        await self._complete(job_id)

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
        log.info("download.job.complete", job_id=job_id)
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event("download", "complete", job=job_id)
        # Hand off to the processing pipeline.
        from nekofetch.services.processing.pipeline import ProcessingPipeline

        await ProcessingPipeline(self._c).run_for_job(job_id)
        await LogChannelService(self._c).event("processing", "complete", job=job_id)

    async def _handle_failure(self, job_id: int, exc: Exception) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED
            job.error = str(exc)
        log.error("download.job.failed", job_id=job_id, error=str(exc))
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event("error", "download_failed", job=job_id, error=str(exc))


def _pick_variant(variants, resolution, audio):
    for v in variants:
        if (resolution is None or v.resolution == resolution) and (
            audio is None or v.audio == audio
        ):
            return v
    return None


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
