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
            job.started_at = _now()
            session.expunge(req)  # detach so we can use it after the session closes

        # Resolve the source chain (preferred site first; both sites for website
        # requests so dual-audio can cross-source). The primary drives the episode
        # list and all non-dual downloads.
        chain = await self._resolve_chain(req)
        source, episodes = chain[0]
        if req.season is not None:
            episodes = [e for e in episodes if e.season == req.season]
        if req.episodes:
            episodes = [e for e in episodes if e.number in set(req.episodes)]

        audios = self._target_audios(req)
        folder = _safe_folder(req)

        for ep in episodes:
            variants = await source.get_variants(ep.source_ref)
            avail_resolutions = sorted(
                set(v.resolution for v in variants),
                key=lambda r: int(r.rstrip("p")), reverse=True,
            )
            if req.resolution:
                avail_resolutions = [r for r in avail_resolutions if r == req.resolution]
            for resolution in avail_resolutions:
                has_native_dual = any(
                    v.audio == AudioType.DUAL_AUDIO and v.resolution == resolution
                    for v in variants
                )
                for audio in audios:
                    # Dual requested but no single native dual track — build the
                    # best result across the source chain (merge / separate /
                    # cross-source / sub-only) so both languages are delivered.
                    if audio == AudioType.DUAL_AUDIO and not has_native_dual:
                        await self._acquire_dual(chain, req, ep, resolution, folder,
                                                 job_id, cfg)
                        continue
                    variant = _select_variant(
                        variants, resolution, audio, self._c.config.acquisition.require_english_subs
                    )
                    if variant is None:
                        continue

                    dest = (
                        self._c.env.storage_path
                        / "work"
                        / folder
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

    async def _resolve_chain(self, req) -> list[tuple]:
        """Resolve a request to a priority-ordered chain of ``(source, episodes)``.

        Requests carry an AniList discovery ref (``anilist:<id>``), so we search
        each candidate source by verified title (English + Romaji) to find its
        native id, then list episodes. For a website priority chain
        (``anikoto>kickassanime``) BOTH sites are resolved when available — that is
        what lets dual-audio acquisition pull sub from one and dub from the other.
        Raises ``NotFound`` only when nothing resolves.
        """
        from nekofetch.core.exceptions import NotFound
        from nekofetch.sources._match import find_verified_match
        from nekofetch.sources.registry import _ALIASES

        fr = req.franchise_data or {}
        title = fr.get("english") or fr.get("title") or req.anime_title
        # Verify against English + Romaji so we never grab the wrong season/title.
        match_titles = [t for t in (fr.get("english") or req.anime_title,
                                    fr.get("title"), fr.get("romaji")) if t]

        raw = req.source or ""
        if ">" in raw:                          # website priority chain
            names = [_ALIASES.get(tok.strip(), tok.strip()) for tok in raw.split(">")]
        else:
            try:
                names = [self._c.sources.resolve(raw).name]
            except Exception:
                names = []
        names = [n for n in names if n and n != "anilist"]

        chain: list[tuple] = []
        last_err: str | None = None
        for name in names:
            try:
                src = self._c.sources.get(name)
            except Exception:
                continue
            try:
                ref = req.source_ref
                if not ref or ref.startswith("anilist:"):
                    stub = await find_verified_match(src, match_titles)
                    if not stub:
                        last_err = f"{name}: no confident title match"
                        continue
                    ref = stub.source_ref
                episodes = await src.get_episodes(ref)
                if episodes:
                    log.info("download.source.resolved", source=name, episodes=len(episodes))
                    chain.append((src, episodes))
                else:
                    last_err = f"{name}: no episodes"
            except Exception as exc:  # noqa: BLE001
                log.warning("download.source.failed", source=name, error=str(exc))
                last_err = f"{name}: {exc}"
        if not chain:
            raise NotFound(f"no source could provide episodes for {title!r} ({last_err})")
        return chain

    async def _best_variant(self, chain, ep_number: int, audio):
        """First ``(source, variant, ep_ref)`` across the chain that offers ``audio``
        for ``ep_number`` — this is what enables cross-source acquisition."""
        for src, eps in chain:
            match = next((e for e in eps if e.number == ep_number), None)
            if not match:
                continue
            try:
                variants = await src.get_variants(match.source_ref)
            except Exception:
                continue
            v = next((x for x in variants if x.audio == audio), None)
            if v is not None:
                return src, v, match.source_ref
        return None

    async def _acquire_dual(self, chain, req, ep, resolution, folder, job_id, cfg) -> None:
        """Deliver BOTH languages for an episode, in the best available shape.

        Strategy, in order of preference:
          1. sub+dub on the SAME source and the same cut → remux into one dual file;
          2. sub+dub available (possibly cross-source) → keep as separate files;
          3. only one audio available → deliver it and flag the gap to staff.
        The goal is "both languages delivered" — one file or two doesn't matter.
        """
        from nekofetch.sources._dualaudio import merge_dual
        from nekofetch.sources.base import VideoVariant

        base = self._c.env.storage_path / "work" / folder
        base.mkdir(parents=True, exist_ok=True)
        stem = f"S{ep.season:02d}E{ep.number:03d}_{resolution}"
        sub_dest = base / f"{stem}_subbed.mkv"
        dub_dest = base / f"{stem}_dubbed.mkv"
        a, b, c = cfg.retry_attempts, cfg.retry_backoff_seconds, None  # retry args

        sub = await self._best_variant(chain, ep.number, AudioType.SUBBED)
        dub = await self._best_variant(chain, ep.number, AudioType.DUBBED)

        # 1) same source + same cut → one merged dual file.
        if sub and dub and sub[0] is dub[0] and hasattr(sub[0], "dual_audio_plan"):
            try:
                plan = await sub[0].dual_audio_plan(sub[2])
            except Exception:
                plan = {}
            if plan.get("mergeable"):
                sr = await self._download_with_retry(sub[0], sub[1], sub_dest, c, a, b)
                dr = await self._download_with_retry(dub[0], dub[1], dub_dest, c, a, b)
                dual_dest = base / f"{stem}_dual_audio.mkv"
                if await merge_dual(sub_dest, dub_dest, dual_dest):
                    dual_v = VideoVariant(source_ref="", resolution=resolution,
                                          audio=AudioType.DUAL_AUDIO, container="mkv")
                    size = dual_dest.stat().st_size if dual_dest.exists() else 0
                    await self._record_file(job_id, req, ep, dual_v, dual_dest, {"bytes": size})
                    sub_dest.unlink(missing_ok=True)
                    dub_dest.unlink(missing_ok=True)
                    log.info("dualaudio.merged", episode=ep.number)
                    return
                # merge failed → keep the two we already downloaded.
                await self._record_file(job_id, req, ep, sub[1], sub_dest, sr)
                await self._record_file(job_id, req, ep, dub[1], dub_dest, dr)
                return

        # 2/3) download each available audio (cross-source if needed), separately.
        got_sub = got_dub = False
        if sub:
            r = await self._download_with_retry(sub[0], sub[1], sub_dest, c, a, b)
            await self._record_file(job_id, req, ep, sub[1], sub_dest, r)
            got_sub = True
        if dub:
            r = await self._download_with_retry(dub[0], dub[1], dub_dest, c, a, b)
            await self._record_file(job_id, req, ep, dub[1], dub_dest, r)
            got_dub = True

        if got_sub and got_dub:
            log.info("dualaudio.separate", episode=ep.number,
                     sub_src=sub[0].name, dub_src=dub[0].name)
        elif got_sub or got_dub:
            await self._notify_audio_gap(req, ep, "dub" if got_sub else "sub")
        else:
            await self._notify_audio_gap(req, ep, "both")

    async def _notify_audio_gap(self, req, ep, missing: str) -> None:
        """Flag to staff that an audio track was unavailable so they can decide
        (accept the partial result, or reassign the source)."""
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "admin", "audio_unavailable", code=req.code, anime=req.anime_title,
            episode=ep.number, missing=missing,
        )

    def _target_audios(self, req) -> list[AudioType]:
        """Resolve the audio types (subbed/dubbed) to acquire for a request.

        When unspecified, fans out into the configured languages (english → DUBBED, japanese → SUBBED).
        """
        acq = self._c.config.acquisition
        if req.audio:
            return [req.audio]
        return [a for a in (_audio_for_language(lang) for lang in acq.languages) if a]

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

        await LogChannelService(self._c).event(
            "download", "complete", job=job_id, anime=title, code=code
        )
        from nekofetch.services.processing.pipeline import ProcessingPipeline

        try:
            pipeline = ProcessingPipeline(self._c)
            # Log each stage as it runs
            ctx = await pipeline.run_for_job(job_id)
            await LogChannelService(self._c).event(
                "processing", "complete", job=job_id, notes=len(ctx.notes),
                stages=",".join(ctx.notes) if ctx.notes else None,
            )
            # Auto-upload the verified packs to the storage (database) channel — this
            # is part of the pipeline, NOT the separate main-channel "publish".
            if code:
                from nekofetch.services.publishing_service import PublishingService
                await PublishingService(self._c).upload_to_storage(code)
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

        await LogChannelService(self._c).event(
            "error", "download_failed", job=job_id, error=str(exc),
            anime=title, code=code,
        )


def _safe_folder(req) -> str:
    """A filesystem-safe work folder name for a request (no colons/slashes)."""
    import re

    base = req.anime_doc_id or req.code or req.source_ref or "work"
    return re.sub(r"[^\w.\-]+", "_", str(base)).strip("_") or "work"


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
