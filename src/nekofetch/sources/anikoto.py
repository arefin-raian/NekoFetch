from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import AudioType
from nekofetch.sources._hls import (
    RECOMMENDED_LIMITS,
    RECOMMENDED_TIMEOUT,
    download_hls_ts,
    download_subtitles,
    find_ffmpeg,
    maybe_remux,
)
from nekofetch.sources._mux import assemble_final, audio_label
from nekofetch.sources.base import (
    AnimeDetails,
    AnimeSource,
    AnimeStub,
    Episode,
    ProgressCallback,
    SourceCoverage,
    VideoVariant,
)

log = get_logger(__name__)


def _rank_by_title(query: str, results: list[AnimeStub]) -> list[AnimeStub]:
    """Re-order site results by title relevance, not raw popularity.

    The site sorts by views, so a viral recap ("Road of Naruto") can outrank the
    real series for a query like "Naruto". We prefer an exact title match, then
    word overlap, keeping the site's order as a stable tiebreak.
    """
    from nekofetch.sources.telegram.matching import normalize_words

    q = normalize_words(query)
    nq = query.strip().lower()

    def key(stub: AnimeStub) -> tuple[int, float]:
        c = normalize_words(stub.title)
        exact = stub.title.strip().lower() == nq
        overlap = (len(q & c) / len(q)) if q else 0.0
        return (1 if exact else 0, overlap)

    return sorted(results, key=key, reverse=True)

BASE_URL = "https://anikototv.to"
MAPPER_API = "https://mapper.nekostream.site/api/mal/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


class AnikotoSource(AnimeSource):
    name = "anikoto"

    def __init__(
        self,
        base_url: str = BASE_URL,
        preferred_quality: str = "1080",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.preferred_quality = preferred_quality
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=RECOMMENDED_TIMEOUT,
                limits=RECOMMENDED_LIMITS,
                headers={
                    "User-Agent": USER_AGENT,
                    "x-requested-with": "XMLHttpRequest",
                },
                follow_redirects=True,
            )
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def search(self, query: str) -> list[AnimeStub]:
        slug_match = re.match(r"slug:(.+)", query)
        if slug_match:
            slug = slug_match.group(1)
            stub = await self._search_by_slug(slug)
            return [stub] if stub else []

        url = f"{self.base_url}/search"
        params = {"keyword": query, "sort": "views", "page": 1}
        try:
            resp = await self.http.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError:
            return await self._popular()

        results = self._parse_item_grid(BeautifulSoup(resp.text, "html.parser"))
        results = _rank_by_title(query, results)
        return results or await self._popular()

    def _parse_item_grid(self, soup: BeautifulSoup) -> list[AnimeStub]:
        """Parse a grid of ``div.item`` cards (search / browse / home listings)."""
        results: list[AnimeStub] = []
        seen: set[str] = set()
        for item in soup.select("div.item"):
            name_a = item.select_one("a.name.d-title") or item.select_one("a[href*='/watch/']")
            if not name_a:
                continue
            href = name_a.get("href", "")
            # /watch/<slug>/ep-N  ->  <slug>
            m = re.search(r"/watch/([^/]+)", href)
            slug = m.group(1) if m else ""
            if not slug or slug in seen:
                continue
            seen.add(slug)
            img = item.select_one("img")
            title = name_a.get_text(strip=True) or (img.get("alt", "") if img else "")
            poster = (img.get("data-src") or img.get("src")) if img else None
            results.append(
                AnimeStub(
                    source_ref=slug,
                    title=str(title).strip(),
                    poster_url=_fix_url(poster) if poster else None,
                )
            )
        return results

    async def _search_by_slug(self, slug: str) -> AnimeStub | None:
        sections = slug.split("/")
        clean_slug = sections[0] if sections else slug
        url = f"{self.base_url}/watch/{clean_slug}"
        try:
            resp = await self.http.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title_el = soup.select_one("h1.title.d-title")
            img = soup.select_one("img[alt]")
            title = title_el.get_text(strip=True) if title_el else clean_slug
            poster = img.get("src") if img else None
            return AnimeStub(
                source_ref=clean_slug,
                title=title,
                poster_url=_fix_url(poster) if poster else None,
            )
        except httpx.HTTPError:
            return None

    async def _popular(self) -> list[AnimeStub]:
        try:
            resp = await self.http.get(f"{self.base_url}/home")
            resp.raise_for_status()
            return self._parse_item_grid(BeautifulSoup(resp.text, "html.parser"))
        except httpx.HTTPError:
            return []

    async def get_details(self, source_ref: str) -> AnimeDetails:
        slug = source_ref.strip("/")
        url = f"{self.base_url}/watch/{slug}"
        resp = await self.http.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title_el = soup.select_one("h1.title.d-title")
        title = title_el.get_text(strip=True) if title_el else slug

        synopsis_el = soup.select_one("div.description")
        synopsis = synopsis_el.get_text(strip=True) if synopsis_el else None

        genres: list[str] = []
        for g in soup.select("a[href*='/genre/']"):
            t = g.get_text(strip=True)
            if t:
                genres.append(t)

        img = soup.select_one("img[alt]")
        poster = img.get("src") if img else None

        return AnimeDetails(
            source_ref=slug,
            title=title,
            synopsis=synopsis,
            genres=genres,
            poster_url=_fix_url(poster) if poster else None,
            season_count=1,
        )

    async def get_episodes(self, source_ref: str) -> list[Episode]:
        slug = source_ref.strip("/")
        url = f"{self.base_url}/watch/{slug}"
        resp = await self.http.get(url)
        resp.raise_for_status()

        search = re.search(rf'{re.escape(self.base_url)}/anime/getinfo/(\d+)', resp.text)
        if not search:
            search = re.search(r'/anime/getinfo/(\d+)', resp.text)
        if not search:
            return []
        video_id = search.group(1)

        ep_resp = await self.http.get(
            f"{self.base_url}/ajax/episode/list/{video_id}?vrf="
        )
        ep_resp.raise_for_status()
        data = ep_resp.json()
        html_code = data.get("result", "")
        if not html_code:
            return []

        soup = BeautifulSoup(html_code, "html.parser")
        episodes: list[Episode] = []
        items = soup.find_all("li", {"data-html": "true"})
        for num, item in enumerate(items, start=1):
            anchor = item.find("a")
            if not anchor:
                continue
            ep_title = anchor.get("title", "")
            data_ids = anchor.get("data-ids", "")
            data_mal = anchor.get("data-mal", "")
            data_timestamp = anchor.get("data-timestamp", "")
            ep_slug = f"{video_id}/{data_ids}/{data_mal}/{data_timestamp}"
            episodes.append(
                Episode(
                    source_ref=ep_slug,
                    season=1,
                    number=num,
                    title=ep_title or None,
                )
            )

        return episodes

    async def coverage(self, *titles: str) -> SourceCoverage:
        """Exact episode total + a sampled sub/dub estimate.

        Matches by AniList English + Romaji so seasons/recaps aren't confused.
        AniKoto resolves audio per-episode, so an exact sub/dub split would mean
        probing every episode. Instead we sample a handful spread across the run
        (first / middle / last …) and extrapolate — enough to surface gross
        variance (e.g. dub only on the first few episodes). Marked approximate.
        """
        from nekofetch.domain.enums import AudioType
        from nekofetch.sources._match import find_verified_match

        stub = await find_verified_match(self, list(titles))
        if not stub:
            return SourceCoverage(source=self.name, matched_title=titles[0] if titles else "",
                                  source_ref="", available=False, note="no confident match")
        try:
            eps = await self.get_episodes(stub.source_ref)
        except Exception:
            eps = []
        total = len(eps)
        if not total:
            return SourceCoverage(source=self.name, matched_title=stub.title,
                                  source_ref=stub.source_ref, available=False,
                                  note="no episodes")
        # Evenly spaced sample (cap at 5) for an audio-availability estimate.
        k = min(5, total)
        idxs = sorted({round(i * (total - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
        sub_hits = dub_hits = sampled = 0
        for i in idxs:
            try:
                variants = await self.get_variants(eps[i].source_ref)
            except Exception:
                continue
            sampled += 1
            audios = {v.audio for v in variants}
            if AudioType.SUBBED in audios:
                sub_hits += 1
            if AudioType.DUBBED in audios:
                dub_hits += 1
        if sampled == 0:
            return SourceCoverage(source=self.name, matched_title=stub.title,
                                  source_ref=stub.source_ref, total_episodes=total,
                                  approximate=True, note="audio resolved per-episode")
        return SourceCoverage(
            source=self.name, matched_title=stub.title, source_ref=stub.source_ref,
            total_episodes=total, seasons=1,
            sub_episodes=round(total * sub_hits / sampled),
            dub_episodes=round(total * dub_hits / sampled),
            approximate=True, available=True,
        )

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        parts = episode_ref.split("/")
        if len(parts) < 4:
            return []
        video_id, data_ids, data_mal, data_timestamp = parts[:4]

        # Ordered fallback servers per audio type. Each entry is a candidate the
        # downloader tries in turn until one yields a clean file.
        #   sub  -> soft subtitles (separate VTT track)
        #   hsub -> hardcoded subtitles burned into the video
        #   dub  -> dubbed audio, no subtitles
        candidates: dict[AudioType, list[dict]] = {
            AudioType.SUBBED: [],
            AudioType.DUBBED: [],
        }
        seen: set[str] = set()

        def add(kind: str, url: str, referer: str, subtitles: list | None = None) -> None:
            if not url or url in seen:
                return
            seen.add(url)
            audio = AudioType.DUBBED if kind == "dub" else AudioType.SUBBED
            candidates[audio].append({
                "video_url": url,
                "referer": referer,
                "kind": kind,
                "subtitles": subtitles or [],
            })

        await self._collect_mapper(data_mal, episode_ref, data_timestamp, add)
        await self._collect_server_list(data_ids, add)

        variants: list[VideoVariant] = []
        for audio, cands in candidates.items():
            if not cands:
                continue
            # Soft-sub before hard-sub so selectable subtitles win when available.
            cands.sort(key=lambda c: {"sub": 0, "hsub": 1, "dub": 0}.get(c["kind"], 2))
            variants.append(
                VideoVariant(
                    source_ref=json.dumps({
                        "candidates": cands,
                        "quality": self.preferred_quality,
                    }),
                    resolution=f"{self.preferred_quality}p",
                    audio=audio,
                )
            )
        return variants

    async def dual_audio_plan(self, episode_ref: str) -> dict:
        """Assess whether one dual-audio file can be built for this episode.

        AniKoto has no native dual track, so we check — *without downloading the
        videos* — whether the sub and dub streams are the same cut (matching
        runtime). If so they can be merged into one dual file; if not, they must
        stay as separate sub and dub. Returns the variants + the verdict.
        """
        from nekofetch.sources._dualaudio import are_mergeable, playlist_duration

        variants = await self.get_variants(episode_ref)
        sub = next((v for v in variants if v.audio == AudioType.SUBBED), None)
        dub = next((v for v in variants if v.audio == AudioType.DUBBED), None)
        if not (sub and dub):
            return {"feasible": False, "mergeable": False,
                    "reason": "missing sub or dub", "sub_variant": sub, "dub_variant": dub}

        def _first_candidate(v: VideoVariant) -> dict | None:
            try:
                cands = json.loads(v.source_ref).get("candidates", [])
                return cands[0] if cands else None
            except (json.JSONDecodeError, IndexError):
                return None

        async def _dur(v: VideoVariant) -> float | None:
            cand = _first_candidate(v)
            if not cand or not cand.get("video_url"):
                return None
            # AniKoto's m3u8 must be fetched with the embed host root as referer.
            ref = cand.get("referer") or f"{self.base_url}/"
            headers = {"referer": ref, "origin": ref.rstrip("/")}
            return await playlist_duration(self.http, cand["video_url"], headers)

        d_sub = await _dur(sub)
        d_dub = await _dur(dub)
        return {
            "feasible": True, "mergeable": are_mergeable(d_sub, d_dub),
            "sub_variant": sub, "dub_variant": dub,
            "sub_dur": d_sub, "dub_dur": d_dub,
        }

    async def _collect_mapper(self, data_mal, episode_ref, data_timestamp, add) -> None:
        """Kiwi/mapper servers — usually soft-sub + dub HLS streams."""
        try:
            ep_no = self._ep_number_from_ref(episode_ref)
            r = await self.http.get(
                f"{MAPPER_API}{data_mal}/{ep_no}/{data_timestamp}",
                headers={"referer": self.base_url, "origin": self.base_url},
            )
            if r.status_code != 200:
                return
            for stream_key, block in r.json().items():
                if "Stream" not in stream_key or not isinstance(block, dict):
                    continue
                for audio_key in ("sub", "dub"):
                    code = block.get(audio_key)
                    code = code.get("url") if isinstance(code, dict) else code
                    if not code:
                        continue
                    url = await self._resolve_server(code)
                    add(audio_key, url, self.base_url)
        except Exception as exc:
            log.debug("kiwi.stream.failed", error=str(exc))

    async def _collect_server_list(self, data_ids, add) -> None:
        """Site server list — resolves each embed exactly like the website player.

        Flow (verified against the live site):
          ajax/server/list  -> per-type (sub / hsub / dub) data-link-id list
          ajax/server?get=  -> embed URL (e.g. vidtube.site/stream/<tok>/<type>)
          embed page        -> data-id + embed host
          {host}/stream/getSources?id=<data-id> -> { sources.file = master.m3u8,
                                                      tracks = [subtitles] }
        The m3u8 MUST be fetched with ``referer: https://{host}/`` (host root);
        any other referer is 403'd by the CDN.
        """
        try:
            r = await self.http.get(
                f"{self.base_url}/ajax/server/list", params={"servers": data_ids}
            )
            if r.status_code != 200:
                return
            soup = BeautifulSoup(r.json().get("result", ""), "html.parser")
            for server in soup.find_all("div", class_="type"):
                # data-type is one of sub / hsub / dub
                kind = server.get("data-type", "sub").lower()
                for li in server.find_all("li"):
                    link_id = li.get("data-link-id")
                    if not link_id:
                        continue
                    embed_url = await self._resolve_server(link_id, decode=False)
                    if not embed_url:
                        continue
                    await self._extract_embed(embed_url, kind, add)
        except Exception as exc:
            log.debug("server.list.failed", error=str(exc))

    async def _extract_embed(self, embed_url: str, kind: str, add) -> None:
        """Replicate the website player: fetch embed -> getSources -> m3u8 + subs."""
        host = re.match(r"https?://([^/]+)", embed_url)
        if not host:
            return
        host = host.group(1)
        host_root = f"https://{host}/"
        try:
            main_html = (
                await self.http.get(embed_url, headers={"referer": f"{self.base_url}/"})
            ).text
        except Exception:
            return

        # --- Primary: megaplay/vidtube-style data-id + {host}/stream/getSources ---
        id_match = re.search(r'data-id=["\'](\w+)["\']', main_html)
        if id_match:
            try:
                gs = await self.http.get(
                    f"https://{host}/stream/getSources",
                    params={"id": id_match.group(1)},
                    headers={"referer": embed_url, "x-requested-with": "XMLHttpRequest"},
                )
                if gs.status_code == 200:
                    data = gs.json()
                    file_url = data.get("sources", {}).get("file", "")
                    subs = [
                        (t.get("label", t.get("kind", "")), t.get("file", ""))
                        for t in data.get("tracks", [])
                        if t.get("kind") == "captions" and t.get("file")
                    ]
                    # CDN requires the embed HOST ROOT as referer, not the full URL.
                    add(kind, file_url, host_root, subs)
                    if file_url:
                        return
            except Exception as exc:
                log.debug("getsources.failed", host=host, error=str(exc))

        # --- Fallback: legacy save_data.php embeds ---
        id_2_match = re.search(r' data-ep-id="(\d+)"', main_html)
        type_match = re.search(r"type: '(\w+)',", main_html)
        domain_match = re.search(r"domain2_url: '(.+)',", main_html)
        if id_2_match and type_match and domain_match:
            domain2 = domain_match.group(1)
            try:
                vs_r = await self.http.get(
                    f"{domain2}/save_data.php",
                    params={"id": f"{id_2_match.group(1)}-{type_match.group(1)}"},
                    headers={"referer": embed_url},
                )
                if vs_r.status_code == 200:
                    for src in vs_r.json().get("data", {}).get("sources", []):
                        add(kind, src.get("url", ""), host_root)
            except Exception as exc:
                log.debug("savedata.failed", error=str(exc))

    async def _resolve_server(self, code: str, *, decode: bool = True) -> str:
        """Resolve an ``ajax/server`` code to a playable URL (optionally b64-decoded)."""
        try:
            r = await self.http.get(f"{self.base_url}/ajax/server", params={"get": code})
            if r.status_code != 200:
                return ""
            url = r.json().get("result", {}).get("url", "")
            if decode and "#" in url:
                return base64.b64decode(url.split("#")[1]).decode("utf-8")
            return url
        except Exception:
            return ""

    def _ep_number_from_ref(self, episode_ref: str) -> str:
        parts = episode_ref.split("/")
        ancestors = self._episode_cache.get(episode_ref)
        if ancestors is not None:
            return str(ancestors.number)
        return parts[-1] if parts else "1"

    _episode_cache: dict[str, Episode] = {}

    async def _resolve_episode_refs(self, episodes: list[Episode]) -> None:
        for ep in episodes:
            self._episode_cache[ep.source_ref] = ep

    async def download(
        self,
        variant: VideoVariant,
        dest: Path,
        *,
        on_progress: ProgressCallback | None = None,
        resume_state: dict | None = None,
    ) -> dict:
        info = json.loads(variant.source_ref)
        quality = info.get("quality", variant.resolution).rstrip("p")

        # New format carries an ordered candidate list; fall back to the legacy
        # single-URL shape for compatibility.
        candidates = info.get("candidates")
        if not candidates:
            candidates = [{
                "video_url": info["video_url"],
                "referer": info.get("referer", self.base_url),
                "kind": "sub",
            }]

        dest.parent.mkdir(parents=True, exist_ok=True)
        if on_progress:
            await on_progress(0, 1)

        last_error = "no candidates"
        for idx, cand in enumerate(candidates):
            url = cand["video_url"]
            referer = cand.get("referer", self.base_url)
            try:
                if ".m3u8" in url:
                    out = await self._download_hls(url, referer, dest, quality, on_progress)
                else:
                    out = await self._download_direct(url, referer, dest, on_progress)
            except Exception as exc:  # noqa: BLE001 - try the next server
                last_error = str(exc)
                log.warning(
                    "anikoto.candidate.failed",
                    index=idx,
                    kind=cand.get("kind"),
                    error=last_error,
                )
                continue

            # Fetch subtitle tracks (host-root referer, same as the stream).
            sub_info: list[dict] = []
            sub_tracks: list[tuple[str, str, Path]] = []
            hdrs = {"referer": referer, "origin": referer.rstrip("/")}
            subs = cand.get("subtitles") or []
            if subs:
                pairs = [(s[0], s[1]) for s in subs if isinstance(s, (list, tuple)) and len(s) >= 2]
                sub_info = await download_subtitles(self.http, pairs, hdrs, out)
                for s in sub_info:
                    if s.get("saved"):
                        lang_m = re.search(r"\((\w[\w-]*)\)", s.get("label", ""))
                        sub_tracks.append((
                            s["label"], lang_m.group(1) if lang_m else "und", Path(s["saved"]),
                        ))

            # AniKoto streams carry embedded audio (Japanese for sub, English for
            # dub); if ffmpeg is present, mux the (cleaned/branded) subtitles into
            # a single MKV with that audio language tagged, else keep the .ts.
            audio = "en" if cand.get("kind") == "dub" else "ja"
            container = out.suffix.lstrip(".")
            if find_ffmpeg() and sub_tracks:
                try:
                    name = "English" if audio == "en" else "Japanese"
                    out, sub_info = await assemble_final(
                        out, [], sub_tracks, dest, title=dest.stem,
                        embedded_audio=(name, audio),
                    )
                    container = "mkv"
                except Exception as exc:  # noqa: BLE001 - keep the playable .ts
                    log.warning("anikoto.mux.failed", error=str(exc))

            total_bytes = out.stat().st_size
            if on_progress:
                await on_progress(total_bytes, total_bytes)
            sha = hashlib.sha256()
            sha.update(out.read_bytes())
            # AniKoto serves one audio per stream (Japanese for sub, English for
            # dub), so the label is always single-audio SUBBED/DUBBED.
            log.info("anikoto.download.ok", kind=cand.get("kind"), bytes=total_bytes)
            return {
                "checksum": sha.hexdigest(),
                "bytes": total_bytes,
                "complete": True,
                "container": container,
                "server_kind": cand.get("kind"),
                "label": audio_label([audio]),
                "subtitles": sub_info,
            }

        raise RuntimeError(f"all {len(candidates)} servers failed; last error: {last_error}")

    async def _download_hls(
        self,
        master_url: str,
        referer: str,
        dest: Path,
        quality: str,
        on_progress: ProgressCallback | None,
    ) -> Path:
        """Download an HLS stream via the shared de-masking engine -> clean .ts
        (remuxed to .mp4 if ffmpeg is present)."""
        hdrs = {"referer": referer, "origin": referer.rstrip("/")}
        ts_path = await download_hls_ts(
            self.http, master_url, hdrs, quality, dest, on_progress
        )
        return maybe_remux(ts_path, dest)

    async def _download_direct(
        self, url: str, referer: str, dest: Path, on_progress: ProgressCallback | None
    ) -> Path:
        """Stream a plain progressive file (mp4 etc.) straight to disk."""
        out = dest.with_suffix(Path(url.split("?")[0]).suffix or ".mp4")
        hdrs = {"referer": referer, "origin": referer.rstrip("/")}
        total = 0
        async with self.http.stream("GET", url, headers=hdrs) as resp:
            resp.raise_for_status()
            expected = int(resp.headers.get("content-length", 0))
            with out.open("wb") as fh:
                async for chunk in resp.aiter_bytes(1 << 16):
                    fh.write(chunk)
                    total += len(chunk)
                    if on_progress and expected:
                        await on_progress(total, expected)
        if total == 0:
            raise RuntimeError("direct download produced an empty file")
        return out


def _fix_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"{BASE_URL}{raw}"
    return raw
