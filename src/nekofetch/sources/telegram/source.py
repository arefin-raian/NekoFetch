"""TelegramSource — anime releases sourced from Telegram channels.

Flow: AnimeFair index (Anilist-enriched matching) → channel → join/request →
discover the pack structure → expose seasons/episodes/resolutions → download the
chosen file through the user session. When the requested anime exists here it is
preferred over the streaming/torrent sources; otherwise ``search`` returns
nothing and the orchestrator falls back.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType
from nekofetch.sources.base import (
    AnimeDetails,
    AnimeSource,
    AnimeStub,
    Episode,
    ProgressCallback,
    VideoVariant,
)
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.sources.telegram.animefair import AnimeFairIndex
from nekofetch.sources.telegram.packs import TgMedia, discover
from nekofetch.sources.telegram.userbot import UserbotPool

log = get_logger(__name__)


class TelegramSource(AnimeSource):
    name = "telegram"

    def __init__(
        self,
        api_id: int | None = None,
        api_hash: str | None = None,
        *,
        workdir: str = "sessions",
        history_limit: int = 400,
    ) -> None:
        self._api_id = api_id or int(os.getenv("TELEGRAM_API_ID", "0"))
        self._api_hash = api_hash or os.getenv("TELEGRAM_API_HASH", "")
        self.workdir = workdir
        self.history_limit = history_limit
        self._pool: UserbotPool | None = None
        self._anilist = AnilistClient()
        self._index: AnimeFairIndex | None = None

    @property
    def pool(self) -> UserbotPool:
        if self._pool is None:
            self._pool = UserbotPool.from_env(self._api_id, self._api_hash, self.workdir)
        return self._pool

    @property
    def index(self) -> AnimeFairIndex:
        if self._index is None:
            self._index = AnimeFairIndex(self.pool, self._anilist)
        return self._index

    async def close(self) -> None:
        await self._anilist.close()
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ---- discovery via the index -----------------------------------------

    async def search(self, query: str) -> list[AnimeStub]:
        """Return a stub only if the index has a channel for this anime."""
        try:
            entry = await self.index.find_channel(query)
        except Exception as exc:  # noqa: BLE001 - let the orchestrator fall back
            log.warning("telegram.search.failed", query=query, error=str(exc))
            return []
        if not entry:
            return []
        return [AnimeStub(
            source_ref=json.dumps({"channel": entry.channel, "name": entry.name,
                                   "is_invite": entry.is_invite, "query": query}),
            title=f"{entry.name} · Telegram",
        )]

    async def get_details(self, source_ref: str) -> AnimeDetails:
        r = json.loads(source_ref)
        return AnimeDetails(source_ref=source_ref, title=r["name"],
                            synopsis=f"Telegram channel {r['channel']}")

    async def get_episodes(self, source_ref: str) -> list[Episode]:
        """Enter the channel, scan media, discover structure, list episodes."""
        from nekofetch.sources.telegram.animefair import IndexEntry

        r = json.loads(source_ref)
        entry = IndexEntry(name=r["name"], channel=r["channel"], is_invite=r["is_invite"])
        state = await self.index.enter_channel(entry)
        if state.status not in ("joined", "public"):
            # pending approval or failed — caller retries later (after approval).
            log.info("telegram.channel.not_ready", channel=r["channel"], status=state.status)
            return []

        media = await self._scan_channel(r["channel"])
        cat = discover(media)

        episodes: list[Episode] = []
        for season, eps in sorted(cat.seasons.items()):
            for e in eps:
                files = {res: {"msg_id": m.msg_id, "name": m.file_name, "size": m.size}
                         for res, m in e.files.items()}
                episodes.append(Episode(
                    source_ref=json.dumps({"channel": r["channel"], "season": season,
                                           "episode": e.episode, "files": files,
                                           "kind": "episode"}),
                    season=season, number=e.seq,
                    title=f"S{season} EP{e.seq} — {e.title}",
                ))
        # movies / specials appended after episodes, preserving discovery
        for kind, items in (("movie", cat.movies), ("special", cat.specials)):
            for m in items:
                episodes.append(Episode(
                    source_ref=json.dumps({"channel": r["channel"], "season": 0,
                                           "files": {m.resolution or "src":
                                                     {"msg_id": m.msg_id, "name": m.file_name,
                                                      "size": m.size}}, "kind": kind}),
                    season=0, number=len(episodes) + 1,
                    title=f"{kind.title()} — {m.file_name}",
                ))
        return episodes

    async def _scan_channel(self, channel: str) -> list[TgMedia]:
        async def run(client) -> list[TgMedia]:
            out: list[TgMedia] = []
            async for msg in client.get_chat_history(channel, limit=self.history_limit):
                media = getattr(msg, "document", None) or getattr(msg, "video", None)
                if not media:
                    continue
                out.append(TgMedia(
                    msg_id=msg.id,
                    file_name=getattr(media, "file_name", "") or "",
                    caption=msg.caption or "",
                    size=getattr(media, "file_size", 0) or 0,
                ))
            return out
        return await self.pool.execute(run)

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        """One variant per available resolution of the episode."""
        e = json.loads(episode_ref)
        variants: list[VideoVariant] = []
        for res, f in e["files"].items():
            variants.append(VideoVariant(
                source_ref=json.dumps({"channel": e["channel"], "msg_id": f["msg_id"],
                                       "name": f["name"], "resolution": res}),
                resolution=res if res.endswith("p") else "1080p",
                audio=AudioType.DUAL_AUDIO,
                size_bytes=f.get("size"),
            ))
        # highest resolution first
        def _res(v: VideoVariant) -> int:
            r = v.resolution.rstrip("p")
            return int(r) if r.isdigit() else 0
        variants.sort(key=_res, reverse=True)
        return variants

    async def download(
        self,
        variant: VideoVariant,
        dest: Path,
        *,
        on_progress: ProgressCallback | None = None,
        resume_state: dict | None = None,
    ) -> dict:
        info = json.loads(variant.source_ref)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_name = info.get("name") or f"{dest.stem}.mkv"
        out_path = dest.parent / out_name

        async def run(client) -> str:
            msg = await client.get_messages(info["channel"], info["msg_id"])

            async def _prog(current: int, total: int) -> None:
                if on_progress:
                    await on_progress(current, total)

            return await client.download_media(
                msg, file_name=str(out_path), progress=_prog if on_progress else None,
            )

        saved = await self.pool.execute(run)
        path = Path(saved) if saved else out_path
        size = path.stat().st_size if path.exists() else 0
        if size == 0:
            raise RuntimeError("telegram download produced no file")

        # Normalize: our caption/title, extracted+branded subtitles, @AniXWeebs
        # track labels — exactly as every other source's output is standardized.
        result: dict = {"raw_path": str(path), "name": path.name, "bytes": size,
                        "complete": True}
        try:
            from nekofetch.sources._normalize import find_ffmpeg, normalize_release
            if find_ffmpeg():
                norm = await normalize_release(path, dest.with_name(dest.stem))
                path.unlink(missing_ok=True)
                result.update(path=norm["path"], name=Path(norm["path"]).name,
                              bytes=norm["bytes"], normalized=norm)
            else:
                result["path"] = str(path)
                result["warnings"] = ["ffmpeg missing — delivered without normalization"]
        except Exception as exc:  # noqa: BLE001 - keep the raw download on failure
            log.warning("telegram.normalize.failed", error=str(exc))
            result["path"] = str(path)
            result["warnings"] = [f"normalization failed: {exc}"]
        return result
