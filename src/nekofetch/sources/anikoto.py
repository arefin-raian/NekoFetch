from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

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

log = get_logger(__name__)

BASE_URL = "https://anikoto.tv"


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
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/141.0.0.0 Safari/537.36"
                    ),
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

        soup = BeautifulSoup(resp.text, "html.parser")
        results: list[AnimeStub] = []
        seen: set[str] = set()
        for item in soup.select("div.flw-item"):
            anchor = item.select_one("a")
            img = item.select_one("img")
            if not anchor:
                continue
            href = anchor.get("href", "")
            slug = href.strip("/").split("/")[-1] if href.strip("/") else ""
            if not slug or slug in seen:
                continue
            seen.add(slug)
            title = anchor.get("title") or img.get("alt", "") if img else ""
            poster = img.get("data-src") or img.get("src") if img else None
            results.append(
                AnimeStub(
                    source_ref=slug,
                    title=str(title).strip(),
                    poster_url=_fix_url(poster) if poster else None,
                )
            )
        return results or await self._popular()

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
            soup = BeautifulSoup(resp.text, "html.parser")
            results: list[AnimeStub] = []
            seen: set[str] = set()
            for item in soup.select("div.flw-item"):
                anchor = item.select_one("a")
                img = item.select_one("img")
                if not anchor:
                    continue
                href = anchor.get("href", "")
                slug = href.strip("/").split("/")[-1] if href.strip("/") else ""
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                title = anchor.get("title") or img.get("alt", "") if img else ""
                poster = img.get("data-src") or img.get("src") if img else None
                results.append(
                    AnimeStub(
                        source_ref=slug,
                        title=str(title).strip(),
                        poster_url=_fix_url(poster) if poster else None,
                    )
                )
            return results
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

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        parts = episode_ref.split("/")
        if len(parts) < 4:
            return []
        video_id, data_ids, data_mal, data_timestamp = parts[:4]

        variants: list[VideoVariant] = []
        seen_urls: set[str] = set()

        try:
            r = await self.http.get(
                f"https://mapper.mewcdn.online/api/mal/{data_mal}/{self._ep_number_from_ref(episode_ref)}/{data_timestamp}",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
                    ),
                    "referer": self.base_url,
                    "origin": self.base_url,
                },
            )
            if r.status_code == 200:
                kiwi_data = r.json()
                for stream_key in kiwi_data:
                    if "Stream" in stream_key:
                        for audio_key in ("sub", "dub"):
                            if audio_key in kiwi_data[stream_key]:
                                url_data = kiwi_data[stream_key][audio_key]
                                server_code = (
                                    url_data["url"]
                                    if isinstance(url_data, dict)
                                    else url_data
                                )
                                server_r = await self.http.get(
                                    f"{self.base_url}/ajax/server",
                                    params={"get": server_code},
                                )
                                if server_r.status_code == 200:
                                    result_url = server_r.json().get("result", {}).get("url", "")
                                    if result_url and "#" in result_url:
                                        decoded = base64.b64decode(
                                            result_url.split("#")[1]
                                        ).decode("utf-8")
                                        if decoded not in seen_urls:
                                            seen_urls.add(decoded)
                                            audio_type = (
                                                AudioType.DUBBED
                                                if audio_key == "dub"
                                                else AudioType.SUBBED
                                            )
                                            variants.append(
                                                VideoVariant(
                                                    source_ref=json.dumps({
                                                        "video_url": decoded,
                                                        "quality": self.preferred_quality,
                                                        "referer": "https://kwik.cx2.mewcdn.online",
                                                    }),
                                                    resolution=f"{self.preferred_quality}p",
                                                    audio=audio_type,
                                                )
                                            )
        except Exception as exc:
            log.debug("kiwi.stream.failed", error=str(exc))

        try:
            r = await self.http.get(
                f"{self.base_url}/ajax/server/list",
                params={"servers": data_ids},
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.json().get("result", ""), "html.parser")
                servers = soup.find_all("div", class_="type")
                for server in servers:
                    server_type = server.get("data-type", "").upper()
                    items = server.find_all("li")
                    for li in items:
                        link_id = li.get("data-link-id")
                        if not link_id:
                            continue
                        srv_r = await self.http.get(
                            f"{self.base_url}/ajax/server",
                            params={"get": link_id},
                        )
                        if srv_r.status_code != 200:
                            continue
                        srv_url = srv_r.json().get("result", {}).get("url", "")
                        if not srv_url:
                            continue
                        main_r = await self.http.get(
                            srv_url,
                            headers={"referer": f"{self.base_url}/"},
                        )
                        main_html = main_r.text

                        id_match = re.search(r' data-id="(\d+)"', main_html)
                        if id_match:
                            mid = id_match.group(1)
                            mp_r = await self.http.get(
                                "https://megaplay.buzz/stream/getSources",
                                params={"id": mid},
                            )
                            if mp_r.status_code == 200 and "sources" in mp_r.json():
                                mp_data = mp_r.json()
                                mp_url = mp_data.get("sources", {}).get("file", "")
                                if mp_url and mp_url not in seen_urls:
                                    seen_urls.add(mp_url)
                                    audio_type = (
                                        AudioType.DUBBED
                                        if server_type.lower() == "dub"
                                        else AudioType.SUBBED
                                    )
                                    variants.append(
                                        VideoVariant(
                                            source_ref=json.dumps({
                                                "video_url": mp_url,
                                                "quality": self.preferred_quality,
                                                "referer": "https://megaplay.buzz/",
                                            }),
                                            resolution=f"{self.preferred_quality}p",
                                            audio=audio_type,
                                        )
                                    )

                        id_2_match = re.search(r' data-ep-id="(\d+)"', main_html)
                        if id_2_match:
                            id_2 = id_2_match.group(1)
                            type_match = re.search(r"type: '(\w+)',", main_html)
                            domain_match = re.search(r"domain2_url: '(.+)',", main_html)
                            if type_match and domain_match:
                                vtype = type_match.group(1)
                                domain2 = domain_match.group(1)
                                vs_r = await self.http.get(
                                    f"{domain2}/save_data.php",
                                    params={"id": f"{id_2}-{vtype}"},
                                    headers={"referer": self.base_url},
                                )
                                if vs_r.status_code == 200:
                                    vs_data = vs_r.json().get("data", {})
                                    sources = vs_data.get("sources", [])
                                    for src in sources:
                                        src_url = src.get("url", "")
                                        if src_url and src_url not in seen_urls:
                                            seen_urls.add(src_url)
                                            audio_type = (
                                                AudioType.DUBBED
                                                if server_type.lower() == "dub"
                                                else AudioType.SUBBED
                                            )
                                            variants.append(
                                                VideoVariant(
                                                    source_ref=json.dumps({
                                                        "video_url": src_url,
                                                        "quality": self.preferred_quality,
                                                        "referer": self.base_url,
                                                    }),
                                                    resolution=f"{self.preferred_quality}p",
                                                    audio=audio_type,
                                                )
                                            )
        except Exception as exc:
            log.debug("server.list.failed", error=str(exc))

        return variants

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
        video_url = info["video_url"]
        referer = info.get("referer", self.base_url)
        quality = info.get("quality", variant.resolution)

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = dest.with_suffix(".mp4")

        if on_progress:
            await on_progress(0, 1)

        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36"
        )

        if ".m3u8" in video_url or ".mpd" in video_url:
            yt_cmd = [
                sys.executable, "-m", "yt_dlp",
                "--concurrent-fragments", "10",
                "--referer", referer,
                "--add-headers", f"Origin: {referer}",
                "--add-headers", f"Referer: {referer}",
                "--user-agent", user_agent,
                "--retries", "10",
                "--fragment-retries", "15",
                "--fixup", "force",
                "--output", str(dest),
                video_url,
            ]
            if quality:
                yt_cmd.insert(1, "--format-sort")
                yt_cmd.insert(2, f"res:{quality}")

            for attempt in range(3):
                proc = await asyncio.create_subprocess_exec(
                    *yt_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode == 0:
                    break
                msg = stderr.decode(errors="replace")[-300:]
                log.warning(
                    "yt-dlp attempt %d/3 failed (exit %d): %s",
                    attempt + 1,
                    proc.returncode,
                    msg,
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
            else:
                err = stderr.decode(errors="replace")[-500:]
                raise RuntimeError(f"yt-dlp failed after 3 attempts for {video_url}: {err}")
        else:
            ffmpeg_headers = (
                f"user-agent: {user_agent}\r\n"
                f"referer: {referer}\r\n"
                "accept: */*\r\n"
            )
            cmd = [
                "ffmpeg",
                "-headers", ffmpeg_headers,
                "-i", video_url,
                "-acodec", "copy",
                "-vcodec", "copy",
                "-loglevel", "error",
                "-y",
                str(dest),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed (exit {proc.returncode}): "
                    f"{stderr.decode(errors='replace')[:500]}"
                )

        total_bytes = dest.stat().st_size
        if on_progress:
            await on_progress(total_bytes, total_bytes)

        import hashlib
        sha = hashlib.sha256()
        sha.update(dest.read_bytes())

        return {
            "checksum": sha.hexdigest(),
            "bytes": total_bytes,
            "complete": True,
        }


def _fix_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/"):
        return f"{BASE_URL}{raw}"
    return raw
