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
from nekofetch.sources._diagnostics import classify as _classify

log = get_logger(__name__)


class _SkipEpisode(Exception):
    """Raised internally when an admin Stops the currently-downloading episode."""


class _CancelJob(BaseException):
    """Raised internally when an admin Cancels the entire job.

    Deliberately a ``BaseException`` so the per-unit ``except Exception`` guards
    (which isolate ordinary download failures) don't swallow it — a Cancel must
    propagate all the way up to ``_process_job`` and tear the whole job down.
    """


class DownloadWorker:
    def __init__(self, container: Container) -> None:
        self._c = container
        self._sem = asyncio.Semaphore(container.config.downloads.concurrent_downloads)
        self._running = False
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self, poll_interval: float = 2.0) -> None:
        self._running = True
        await self.recover_on_startup()
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
        await self._clear_skip(job_id)

        # First pass: download every (episode, resolution, audio) unit. A unit that
        # fails — or is Stopped mid-flight from ACTIVE TASKS — is recorded and
        # retried after the rest, so ONE bad episode never blocks the whole series.
        # A whole-job Cancel aborts the lot and tears the job down cleanly.
        try:
            failed: list[dict] = []
            for ep in episodes:
                if await self._cancel_requested(job_id):
                    raise _CancelJob()
                await self._download_episode(
                    job_id, req, source, chain, ep, audios, folder, cfg, failed
                )

            # Retry pass: re-extract FRESH variants (new tokens / rotated hosts),
            # which recovers expired-token and dead-host failures with no manual action.
            remaining: list[dict] = []
            for spec in failed:
                if await self._cancel_requested(job_id):
                    raise _CancelJob()
                if not await self._retry_unit(job_id, req, source, chain, spec, folder, cfg):
                    remaining.append(spec)
        except _CancelJob:
            await self._finalize_cancelled(job_id)
            return

        # The series is NOT blocked: whatever downloaded proceeds to processing, and
        # any still-stuck episodes are recorded so the control center can offer
        # Retry / Switch-source / Provide-file instead of auto-retrying forever.
        if remaining:
            await self._mark_partial(job_id, remaining)
        await self._complete(job_id)

    async def _download_episode(self, job_id, req, source, chain, ep, audios, folder,
                                cfg, failed: list) -> None:
        """Download every resolution/audio unit for ONE episode, recording (never
        raising) failures so the caller keeps going through the rest of the series."""
        try:
            variants = await source.get_variants(ep.source_ref)
        except Exception as exc:  # noqa: BLE001
            kind, reason = _classify(exc)
            log.warning("download.variants.failed", season=ep.season, episode=ep.number,
                        failure=kind.value, reason=reason)
            failed.append(self._spec(ep, None, None, dual=False))
            return
        if getattr(source, "name", "") == "local":
            # Operator-owned library (also the manual-upload target): ingest exactly
            # the files present — every laid-down resolution/audio — with no
            # acquisition-policy filtering. Everything downstream (record → process →
            # storage → publish) is identical to any other source.
            for variant in variants:
                spec = self._spec(ep, variant.resolution, variant.audio, dual=False)
                try:
                    if await self._already_have(job_id, ep, variant.resolution, variant.audio):
                        continue
                    if not await self._run_unit(job_id, req, source, ep, variant, folder, cfg):
                        failed.append(spec)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    kind, reason = _classify(exc)
                    log.warning("download.unit.failed", season=ep.season, episode=ep.number,
                                resolution=variant.resolution,
                                audio=variant.audio.value if variant.audio else None,
                                failure=kind.value, reason=reason)
                    failed.append(spec)
            return
        available = {v.resolution for v in variants}
        for resolution in self._resolutions_to_fetch(req, available):
            has_native_dual = any(
                v.audio == AudioType.DUAL_AUDIO and v.resolution == resolution for v in variants
            )
            for audio in audios:
                dual = audio == AudioType.DUAL_AUDIO and not has_native_dual
                spec = self._spec(ep, resolution, audio, dual=dual)
                try:
                    if dual:
                        await self._acquire_dual(chain, req, ep, resolution, folder, job_id, cfg)
                        continue
                    variant = _select_variant(
                        variants, resolution, audio,
                        self._c.config.acquisition.require_english_subs,
                    )
                    if variant is None:
                        continue
                    # Resume: if a prior run already downloaded this exact unit and
                    # the file is still on disk, skip it (e.g. eps 1-9 done → ep 10).
                    if await self._already_have(job_id, ep, resolution, audio):
                        continue
                    if not await self._run_unit(job_id, req, source, ep, variant, folder, cfg):
                        failed.append(spec)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    kind, reason = _classify(exc)
                    log.warning("download.unit.failed", season=ep.season, episode=ep.number,
                                resolution=resolution, audio=audio.value,
                                failure=kind.value, reason=reason)
                    failed.append(spec)

    @staticmethod
    def _spec(ep, resolution, audio, *, dual: bool) -> dict:
        return {"ep_ref": ep.source_ref, "season": ep.season, "number": ep.number,
                "title": ep.title, "resolution": resolution,
                "audio": audio.value if audio is not None else None, "dual": dual}

    async def _run_unit(self, job_id, req, source, ep, variant, folder, cfg) -> bool:
        """Download a single variant under a Stop watcher. True on success; False if
        it failed or was Stopped (so it lands on the retry list)."""
        dest = (
            self._c.env.storage_path / "work" / folder
            / f"S{ep.season:02d}E{ep.number:03d}_{variant.resolution}_{variant.audio.value}"
              f".{variant.container or 'mkv'}"
        )
        on_progress = self._make_progress(job_id, ep, variant, cfg)
        try:
            result = await self._download_watched(job_id, source, variant, dest, on_progress, cfg)
        except _SkipEpisode:
            log.info("download.episode.stopped", season=ep.season, episode=ep.number)
            return False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            kind, reason = _classify(exc)
            log.warning("download.unit.error", season=ep.season, episode=ep.number,
                        failure=kind.value, reason=reason)
            return False
        await self._record_file(job_id, req, ep, variant, dest, result)
        return True

    async def _download_watched(self, job_id, source, variant, dest, on_progress, cfg) -> dict:
        """Run the (retrying) download as a sub-task while polling the Stop flag, so
        an admin can stop the CURRENT episode without killing the whole job."""
        task = asyncio.ensure_future(self._download_with_retry(
            source, variant, dest, on_progress, cfg.retry_attempts, cfg.retry_backoff_seconds,
        ))
        while True:
            cancel = await self._cancel_requested(job_id)
            if cancel or await self._skip_requested(job_id):
                task.cancel()
                if not cancel:
                    await self._clear_skip(job_id)
                try:
                    await task
                except BaseException:  # noqa: BLE001 - swallow whatever the cancel surfaces
                    pass
                raise _CancelJob() if cancel else _SkipEpisode()
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
            except asyncio.TimeoutError:
                continue

    def _make_progress(self, job_id, ep, variant, cfg):
        """Build the rolling-window progress callback for one unit."""
        st = {"last": 0.0, "win_t": time.monotonic(), "win_done": 0}

        async def on_progress(done: int, total: int) -> None:
            now = time.monotonic()
            if now - st["last"] < cfg.progress_update_interval_seconds:
                return
            dt = max(now - st["win_t"], 1e-6)
            speed = max(done - st["win_done"], 0) / dt
            st["win_t"], st["win_done"], st["last"] = now, done, now
            pct = (done / total * 100) if total else 0.0
            eta = int((total - done) / speed) if speed > 0 else None
            if self._c.progress:
                try:
                    await self._c.progress.set(ProgressSnapshot(
                        job_id=job_id, status=JobStatus.RUNNING.value, progress=pct,
                        speed_bps=speed, downloaded_bytes=done, total_bytes=total,
                        current_episode=ep.number, eta_seconds=eta,
                        resolution=variant.resolution, audio=variant.audio.value,
                        label=f"S{ep.season:02d}E{ep.number:03d} {variant.resolution} {variant.audio.value}",
                    ))
                except Exception:  # noqa: BLE001
                    # Progress is cosmetic telemetry — a Redis hiccup (e.g. an
                    # Upstash read timeout) must NEVER fail an episode that is
                    # actually downloading fine.
                    pass
        return on_progress

    async def _retry_unit(self, job_id, req, source, chain, spec, folder, cfg) -> bool:
        """Retry one failed unit ONCE with freshly re-extracted metadata."""
        from nekofetch.sources.base import Episode

        ep = Episode(source_ref=spec["ep_ref"], season=spec["season"],
                     number=spec["number"], title=spec.get("title"))
        try:
            if spec.get("dual"):
                await self._acquire_dual(chain, req, ep, spec["resolution"], folder, job_id, cfg)
                return True
            if not spec.get("resolution") or not spec.get("audio"):
                return False
            variants = await source.get_variants(spec["ep_ref"])  # fresh tokens/hosts
            variant = _select_variant(
                variants, spec["resolution"], AudioType(spec["audio"]),
                self._c.config.acquisition.require_english_subs,
            )
            if variant is None:
                return False
            return await self._run_unit(job_id, req, source, ep, variant, folder, cfg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            kind, reason = _classify(exc)
            log.warning("download.retry.failed", season=spec["season"], episode=spec["number"],
                        failure=kind.value, reason=reason)
            return False

    async def _mark_partial(self, job_id: int, remaining: list) -> None:
        """Record the episodes that couldn't be downloaded and post an actionable
        attention card (Retry / Switch-source / Provide-file). The job still
        completes — the series ships with what succeeded."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            req = await RequestRepository(session).get(job.request_id) if job else None
            if job is not None:
                state = dict(job.resume_state or {})
                state["partial_failures"] = remaining
                job.resume_state = state
            code = req.code if req else ""
            title = req.anime_title if req else ""
            source = req.source if req else ""
        # Keep per-episode audio so the card says exactly WHICH version failed
        # (sub vs dub), not just an episode number.
        seen: set = set()
        failures: list[dict] = []
        for s in remaining:
            n = s.get("number")
            if n is None or (n, s.get("audio")) in seen:
                continue
            seen.add((n, s.get("audio")))
            failures.append({"ep": n, "audio": s.get("audio")})
        log.warning("download.job.partial", job_id=job_id,
                    stuck=[(f["ep"], f["audio"]) for f in failures], source=source)
        from nekofetch.services.log_channel_service import LogChannelService
        await LogChannelService(self._c).post_attention_card(
            code=code, title=title, failures=failures, source=source,
            alt_source=_alternate_source(source),
        )

    async def ingest_provided_file(self, code: str, episode: int, src_path) -> None:
        """Ingest an admin-provided file for a stuck episode: record it as a verified
        MediaFile, push it to the storage channel, then remove the local temp so we
        don't keep the hand-delivered copy around."""
        from pathlib import Path

        from sqlalchemy import select

        from nekofetch.core.exceptions import NotFound
        from nekofetch.infrastructure.database.postgres.models import DownloadJob

        src_path = Path(src_path)
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            job = (await session.execute(
                select(DownloadJob).where(DownloadJob.request_id == req.id)
                .order_by(DownloadJob.id.desc())
            )).scalars().first()
            job_id = job.id if job else None
            anime_doc_id = req.anime_doc_id or req.source_ref
            audio = req.audio or AudioType.SUBBED
            season = req.season or 1
            folder = _safe_folder(req)
        ext = src_path.suffix.lstrip(".") or "mkv"
        dest = (self._c.env.storage_path / "work" / folder
                / f"S{season:02d}E{int(episode):03d}_manual.{ext}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src_path.resolve() != dest.resolve():
            src_path.replace(dest)
        import hashlib
        async with session_scope(self._c.pg_sessionmaker) as session:
            session.add(MediaFile(
                job_id=job_id, anime_doc_id=anime_doc_id, season=season,
                episode=int(episode), resolution="source", audio=audio,
                local_path=str(dest), size_bytes=dest.stat().st_size,
                checksum=hashlib.sha256(dest.read_bytes()).hexdigest(),
                container=ext, verified=True,
            ))
        from nekofetch.services.publishing_service import PublishingService
        await PublishingService(self._c).upload_to_storage(code)
        try:
            dest.unlink()                 # delete the provided file after ingesting it
        except OSError:
            pass
        log.info("download.manual.ingested", code=code, episode=episode)

    # ── Stop-current-episode flag (set from ACTIVE TASKS) ────────────────────────
    @staticmethod
    def _skip_key(job_id: int) -> str:
        return f"nf:job:{job_id}:skip"

    async def _skip_requested(self, job_id: int) -> bool:
        if not self._c.redis:
            return False
        try:
            return bool(await self._c.redis.get(self._skip_key(job_id)))
        except Exception:  # noqa: BLE001 - a Redis blip must not fail the download
            return False

    async def _clear_skip(self, job_id: int) -> None:
        if self._c.redis:
            await self._c.redis.delete(self._skip_key(job_id))

    async def request_skip(self, job_id: int) -> None:
        """Public: signal the worker to Stop the currently-downloading episode (it
        finishes the rest of the series, then retries this one at the end)."""
        if self._c.redis:
            await self._c.redis.set(self._skip_key(job_id), "1", ex=300)

    # ── Cancel-whole-job flag ────────────────────────────────────────────────────
    @staticmethod
    def _cancel_key(job_id: int) -> str:
        return f"nf:job:{job_id}:cancel"

    async def _cancel_requested(self, job_id: int) -> bool:
        if not self._c.redis:
            return False
        try:
            return bool(await self._c.redis.get(self._cancel_key(job_id)))
        except Exception:  # noqa: BLE001 - a Redis blip must not fail the download
            return False

    async def _clear_cancel(self, job_id: int) -> None:
        if self._c.redis:
            await self._c.redis.delete(self._cancel_key(job_id))

    async def _finalize_cancelled(self, job_id: int) -> None:
        """Tear a cancelled job down cleanly: mark it CANCELLED (so it leaves the
        active list), drop its live progress, and clear its control flags."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            title = code = ""
            if job is not None:
                job.status = JobStatus.CANCELLED
                job.finished_at = _now()
                req = await RequestRepository(session).get(job.request_id)
                if req is not None:
                    req.status = RequestStatus.FAILED
                    title, code = req.anime_title, req.code
        if self._c.progress:
            await self._c.progress.delete(job_id)
        await self._clear_skip(job_id)
        await self._clear_cancel(job_id)
        log.info("download.job.cancelled", job_id=job_id)
        from nekofetch.services.log_channel_service import LogChannelService
        await LogChannelService(self._c).event("error", "cancelled", job=job_id,
                                                anime=title, code=code)

    # ── startup recovery / resume ────────────────────────────────────────────────
    async def recover_on_startup(self) -> None:
        """At process start NOTHING is downloading yet, so any job left RUNNING/PAUSED
        was orphaned by a crash or kill. Re-queue it so the worker resumes (the loop
        skips already-downloaded episodes), and clear its stale live-progress so
        ACTIVE TASKS reflects reality instead of a phantom 'downloading' row.

        When resume is disabled, orphans are failed outright rather than left hanging.
        """
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = QueueRepository(session)
            orphaned = await repo.by_status(JobStatus.RUNNING, JobStatus.PAUSED)
            ids = [j.id for j in orphaned]
            resume = self._c.config.downloads.resume_interrupted
            for job in orphaned:
                if resume:
                    job.status = JobStatus.QUEUED          # picked up + resumed
                else:
                    job.status = JobStatus.FAILED
                    job.error = "interrupted (worker restarted)"
        for jid in ids:
            if self._c.progress:
                await self._c.progress.delete(jid)
            await self._clear_skip(jid)
            await self._clear_cancel(jid)
        if ids:
            log.info("download.recover", orphaned=ids, resume=resume)

    async def _already_have(self, job_id, ep, resolution, audio) -> bool:
        """True if this exact unit was already downloaded in a prior run and the file
        still exists — the basis of resume (eps 1-9 done → skip straight to ep 10)."""
        from pathlib import Path

        from sqlalchemy import select
        try:
            async with session_scope(self._c.pg_sessionmaker) as session:
                row = (await session.execute(
                    select(MediaFile).where(
                        MediaFile.job_id == job_id, MediaFile.season == ep.season,
                        MediaFile.episode == ep.number, MediaFile.resolution == resolution,
                        MediaFile.audio == audio,
                    )
                )).scalars().first()
            return bool(row and row.local_path and Path(row.local_path).exists())
        except Exception:  # noqa: BLE001 - on error, just re-download (safe) not fail
            return False

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
        sub_dest = base / f"{stem}_Sub.mkv"
        dub_dest = base / f"{stem}_Dub.mkv"
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

    def _resolutions_to_fetch(self, req, available: set[str]) -> list[str]:
        """Which resolutions to actually download for this episode.

        A request that pins a resolution gets exactly that (if the source has it).
        Otherwise we grab every mandatory target (1080p/720p/480p) the source
        offers, and for any missing target we take the first available alternate
        from its fallback ladder — so 480p degrades to 540p or 360p instead of
        being skipped. Order/dupes are preserved/removed so each tier is fetched once.
        """
        if req.resolution:
            return [req.resolution] if req.resolution in available else []
        acq = self._c.config.acquisition
        wanted: list[str] = []
        for target in acq.target_resolutions:
            pick = target if target in available else next(
                (fb for fb in acq.resolution_fallbacks.get(target, []) if fb in available),
                None,
            )
            if pick and pick not in wanted:
                wanted.append(pick)
        return wanted

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
        """The download finished — but the JOB is not 'complete' until processing AND
        the database (storage) upload are done. The job is kept RUNNING through both
        so every stage is visible in ACTIVE TASKS, and only flipped to COMPLETED at
        the very end (after the storage upload)."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is not None:
                job.progress = 100.0
            req = await RequestRepository(session).get(job.request_id) if job else None
            if req is not None:
                req.status = RequestStatus.PROCESSING
            user_id = req.user_id if req else None
            title = req.anime_title if req else ""
            code = req.code if req else ""
        needs_approval = self._c.config.processing.require_approval_before_publish
        log.info("download.job.downloaded", job_id=job_id)

        from nekofetch.services.log_channel_service import LogChannelService
        from nekofetch.services.notification_service import NotificationService

        if user_id:
            await NotificationService(self._c).download_complete(user_id, title, code)
        # "downloaded" (not "complete") — the job isn't complete until processing +
        # DB upload finish. Only the final step emits the ✅ complete line.
        await LogChannelService(self._c).event("download", "downloaded", job=job_id,
                                               anime=title, code=code)

        from nekofetch.services.processing.pipeline import ProcessingPipeline

        try:
            ctx = await ProcessingPipeline(self._c).run_for_job(job_id)
            # Upload the verified packs to the storage (DB) channel WITH live progress —
            # this is part of being done, not an afterthought, and only NOW (after a
            # successful upload) is the job genuinely complete.
            if code:
                from nekofetch.services.publishing_service import PublishingService

                await self._push_stage(job_id, title, "Uploading", 0.0)
                await LogChannelService(self._c).event("processing", "uploading",
                                                       job=job_id, anime=title)
                await PublishingService(self._c).upload_to_storage(
                    code, on_progress=self._upload_progress(job_id, title),
                )
            await LogChannelService(self._c).event("processing", "complete", job=job_id,
                                                   anime=title, notes=len(ctx.notes))
            await self._finalize_complete(job_id)
            if user_id:
                await NotificationService(self._c).processing_complete(
                    user_id, title, code, needs_approval=needs_approval)
        except Exception as exc:  # noqa: BLE001
            log.error("download.processing.failed", job_id=job_id, error=str(exc))
            logcc = LogChannelService(self._c)
            await logcc.event("error", "processing_failed", job=job_id, error=str(exc))
            await logcc.post_failure_card(code=code, title=title, stage="processing", error=str(exc))
            await self._mark_failed(job_id, str(exc))
            if user_id:
                await NotificationService(self._c).processing_failed(user_id, title, code, str(exc))

    async def _finalize_complete(self, job_id: int) -> None:
        """Mark the job COMPLETED only after download + processing + DB upload — and
        clear its live progress so it leaves ACTIVE TASKS."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is not None:
                job.status = JobStatus.COMPLETED
                job.progress = 100.0
                job.finished_at = _now()
        if self._c.progress:
            try:
                await self._c.progress.delete(job_id)
            except Exception:  # noqa: BLE001
                pass
        log.info("download.job.complete", job_id=job_id)

    async def _mark_failed(self, job_id: int, error: str) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            job = await session.get(DownloadJob, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = error[:500]
        if self._c.progress:
            try:
                await self._c.progress.delete(job_id)
            except Exception:  # noqa: BLE001
                pass

    async def _push_stage(self, job_id: int, title: str, stage: str, pct: float) -> None:
        """Publish a coarse stage marker so ACTIVE TASKS shows post-download stages
        (Verifying / Metadata / Uploading …) with a bar, not just downloads."""
        if not self._c.progress:
            return
        try:
            await self._c.progress.set(ProgressSnapshot(
                job_id=job_id, status=JobStatus.RUNNING.value, progress=pct,
                stage=stage, label=title,
            ))
        except Exception:  # noqa: BLE001
            pass

    def _upload_progress(self, job_id: int, title: str):
        """Rolling-window progress callback for the storage upload — same speed/ETA
        treatment as downloads, tagged with the 'Uploading' stage."""
        st = {"last": 0.0, "win_t": time.monotonic(), "win_done": 0}

        async def on_progress(done: int, total: int) -> None:
            now = time.monotonic()
            if now - st["last"] < 0.5:
                return
            dt = max(now - st["win_t"], 1e-6)
            speed = max(done - st["win_done"], 0) / dt
            st["win_t"], st["win_done"], st["last"] = now, done, now
            pct = (done / total * 100) if total else 0.0
            eta = int((total - done) / speed) if speed > 0 else None
            if self._c.progress:
                try:
                    await self._c.progress.set(ProgressSnapshot(
                        job_id=job_id, status=JobStatus.RUNNING.value, progress=pct,
                        speed_bps=speed, downloaded_bytes=done, total_bytes=total,
                        eta_seconds=eta, stage="Uploading", label=title,
                    ))
                except Exception:  # noqa: BLE001
                    pass
        return on_progress

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

        logcc = LogChannelService(self._c)
        await logcc.event(
            "error", "download_failed", job=job_id, error=str(exc),
            anime=title, code=code,
        )
        await logcc.post_failure_card(code=code, title=title, stage="download", error=str(exc))


_WEBSITE_SOURCES = ("anikoto", "kickassanime")


def _alternate_source(source: str) -> str | None:
    """The other website source to offer as a switch target, or None when the
    request isn't on a website source (torrent/telegram have no peer)."""
    s = (source or "").lower()
    present = [w for w in _WEBSITE_SOURCES if w in s]
    if not present:
        return None
    primary = present[0]  # first token in a "a>b" chain is the current primary
    return next((w for w in _WEBSITE_SOURCES if w != primary), None)


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
        "hindi": AudioType.MULTI,
        "multi": AudioType.MULTI,
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
