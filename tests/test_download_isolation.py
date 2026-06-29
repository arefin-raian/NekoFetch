"""Guards for per-episode download isolation + the Stop-current-episode flag."""

from __future__ import annotations

import asyncio
import types

from nekofetch.services.download_service import DownloadWorker, _CancelJob, _SkipEpisode


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        self.store[k] = v

    async def delete(self, k):
        self.store.pop(k, None)


def _worker(redis):
    w = DownloadWorker.__new__(DownloadWorker)
    w._c = types.SimpleNamespace(
        config=types.SimpleNamespace(downloads=types.SimpleNamespace(
            retry_attempts=1, retry_backoff_seconds=0, resume_interrupted=False)),
        redis=redis, progress=None,
    )
    return w


class _SlowSource:
    async def download(self, variant, dest, *, on_progress=None, resume_state=None):
        await asyncio.sleep(30)
        return {"bytes": 1}


class _FastSource:
    async def download(self, variant, dest, *, on_progress=None, resume_state=None):
        return {"bytes": 42, "checksum": "x"}


def test_stop_flag_skips_current_episode():
    redis = _FakeRedis()
    w = _worker(redis)

    async def run():
        await w.request_skip(7)                    # admin taps Stop on ACTIVE TASKS
        cfg = w._c.config.downloads
        try:
            await w._download_watched(7, _SlowSource(), None, None, None, cfg)
            return "ran"
        except _SkipEpisode:
            return "skipped"

    assert asyncio.run(run()) == "skipped"
    # The flag is consumed, so the NEXT episode isn't also skipped.
    assert asyncio.run(redis.get("nf:job:7:skip")) is None


def test_cancel_flag_aborts_whole_job():
    redis = _FakeRedis()
    w = _worker(redis)

    async def run():
        await redis.set("nf:job:7:cancel", "1")       # admin taps Cancel series
        cfg = w._c.config.downloads
        try:
            await w._download_watched(7, _SlowSource(), None, None, None, cfg)
            return "ran"
        except _CancelJob:
            return "cancelled"

    assert asyncio.run(run()) == "cancelled"


def test_normal_download_completes():
    w = _worker(_FakeRedis())
    cfg = w._c.config.downloads
    res = asyncio.run(w._download_watched(7, _FastSource(), None, None, None, cfg))
    assert res["bytes"] == 42
