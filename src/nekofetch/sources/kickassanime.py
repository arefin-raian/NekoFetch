"""KickAssAnime source — search, browse, and download from kickassanime.

Uses the same public API as the Tachiyomi extension:
  - Trending / search  ──>  GET /api/trending, POST /api/fsearch
  - Details            ──>  GET /api/show/{slug}
  - Episodes           ──>  GET /api/show/{slug}/language
                            GET /api/show/{slug}/episodes?page=N&lang=X
  - Video servers      ──>  GET /api/show/{slug}/episode/ep-{N}-{slug}
  - Video extraction   ──>  AES-256-CBC decryption of server payloads
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from urllib.parse import parse_qs

import httpx

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

BASE_URL = "https://kaa.lt"

LOCALE_MAP: dict[str, str] = {
    "ja-JP": "Japanese",
    "en-US": "English",
    "es-ES": "Spanish (España)",
    "ko-KR": "Korean",
    "zh-CN": "Chinese (Simplified)",
}

SERVER_AES_KEYS: dict[str, bytes] = {
    "VidStreaming": b"e13d38099bf562e8b9851a652d2043d3",
    "DuckStream": b"4504447b74641ad972980a6b8ffd7631",
    "BirdStream": b"4b14d0ff625163e3c9c7a47926484bf2",
    "CatStream": b"",
}


def _unpad_pkcs7(data: bytes) -> bytes:
    pad = data[-1]
    return data[: -pad]


def _decrypt_aes_256_cbc(key: bytes, iv: bytes, encrypted: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    return _unpad_pkcs7(padded)


def _sha1(data: str) -> str:
    return hashlib.sha1(data.encode()).hexdigest()


def _fix_url(raw: str, base: str | None = None) -> str:
    raw = raw.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("/") and base:
        from urllib.parse import urlparse

        parsed = urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{raw}"
    return re.sub(r"^(https?)//+", r"\1://", raw)


class KickAssAnimeSource(AnimeSource):
    name = "kickassanime"

    def __init__(
        self,
        base_url: str = BASE_URL,
        preferred_lang: str = "ja-JP",
        second_lang: str = "en-US",
        preferred_quality: str = "1080p",
        preferred_server: str = "VidStreaming",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}/api/show"
        self.preferred_lang = preferred_lang
        self.second_lang = second_lang
        self.preferred_quality = preferred_quality
        self.preferred_server = preferred_server
        self._http: httpx.AsyncClient | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Linux; Android 10; K) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/129.0.0.0 Mobile Safari/537.36"
                    ),
                    "Accept": "application/json, text/plain, */*",
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
            try:
                resp = await self.http.get(f"{self.api_url}/{slug}")
                resp.raise_for_status()
                doc = resp.json()
                poster = doc.get("poster", {}) if isinstance(doc.get("poster"), dict) else {}
                poster_slug = poster.get("hq") if isinstance(poster, dict) else None
                return [
                    AnimeStub(
                        source_ref=slug,
                        title=doc.get("title_en") or doc.get("title", ""),
                        poster_url=f"{self.base_url}/image/poster/{poster_slug}.webp" if poster_slug else None,
                        year=doc.get("year"),
                    )
                ]
            except httpx.HTTPError:
                return []

        if query.strip():
            payload = json.dumps({"page": 1, "query": query})
            headers = {
                "Content-Type": "application/json",
                "Referer": f"{BASE_URL}/search?q={query}",
            }
            try:
                resp = await self.http.post(f"{BASE_URL}/api/fsearch", content=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return self._parse_anime_list(data.get("result", []))
            except httpx.HTTPError:
                pass

        return await self._popular()

    async def _popular(self) -> list[AnimeStub]:
        try:
            resp = await self.http.get(f"{self.api_url}/trending?page=1")
            resp.raise_for_status()
            data = resp.json()
            return self._parse_anime_list(data.get("result", []))
        except httpx.HTTPError:
            return []

    def _parse_anime_list(self, items: list) -> list[AnimeStub]:
        results = []
        for item in items:
            slug = item.get("slug", "")
            poster = item.get("poster", {})
            poster_slug = poster.get("hq") if isinstance(poster, dict) else None
            results.append(
                AnimeStub(
                    source_ref=slug,
                    title=item.get("title_en") or item.get("title", ""),
                    poster_url=f"{self.base_url}/image/poster/{poster_slug}.webp" if poster_slug else None,
                    year=item.get("year"),
                )
            )
        return results

    async def get_details(self, source_ref: str) -> AnimeDetails:
        slug = source_ref.strip("/")
        resp = await self.http.get(f"{self.api_url}/{slug}")
        resp.raise_for_status()
        doc = resp.json()

        poster = doc.get("poster", {}) if isinstance(doc.get("poster"), dict) else {}
        poster_slug = poster.get("hq") if isinstance(poster, dict) else None

        return AnimeDetails(
            source_ref=slug,
            title=doc.get("title_en") or doc.get("title", ""),
            alt_titles=list(dict.fromkeys(t for t in (doc.get("title_en"), doc.get("title")) if t and doc.get("title_en") != doc.get("title"))),
            synopsis=doc.get("synopsis"),
            genres=doc.get("genres", []),
            release_date=str(doc["year"]) if doc.get("year") else None,
            poster_url=f"{self.base_url}/image/poster/{poster_slug}.webp" if poster_slug else None,
            season_count=1 if doc.get("season") else 0,
            episode_count=0,
        )

    async def get_episodes(self, source_ref: str) -> list[Episode]:
        slug = source_ref.strip("/")

        languages = await self._fetch_languages(slug)
        lang_order = sorted(
            languages,
            key=lambda x: (
                x != self.preferred_lang,
                x != self.second_lang,
            ),
        )

        seen: set[str] = set()
        episodes: list[Episode] = []

        for lang in lang_order:
            if episodes:
                break
            page = 1
            while True:
                resp = await self.http.get(f"{self.api_url}/{slug}/episodes?page={page}&lang={lang}")
                if resp.status_code != 200:
                    break
                data = resp.json()
                result = data.get("result", [])
                if not result:
                    break
                for ep in result:
                    ep_str = ep.get("episode_string", "")
                    ep_slug = ep.get("slug", "")
                    ep_title = ep.get("title")
                    num = int(float(ep_str)) if ep_str.replace(".", "", 1).isdigit() else 0

                    ep_key = f"{num}"
                    if ep_key not in seen:
                        seen.add(ep_key)
                        display = f"Ep. {ep_str}"
                        if ep_title:
                            display += f" - {ep_title}"
                        episodes.append(
                            Episode(
                                source_ref=f"{slug}/ep-{ep_str}-{ep_slug}",
                                season=1,
                                number=num,
                                title=display,
                            )
                        )

                pages = data.get("pages", [])
                if page >= len(pages):
                    break
                page += 1

        return sorted(episodes, key=lambda e: e.number)

    async def _fetch_languages(self, slug: str) -> list[str]:
        try:
            resp = await self.http.get(f"{self.api_url}/{slug}/language")
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", [])
        except httpx.HTTPError:
            return ["ja-JP"]

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        slug, ep_path = episode_ref.split("/", 1) if "/" in episode_ref else (episode_ref, "")
        if not ep_path:
            return []

        ep_part = ep_path.replace("ep-", "episode/ep-")
        url = f"{self.api_url}/{slug}/{ep_part}"

        resp = await self.http.get(url)
        resp.raise_for_status()
        data = resp.json()
        servers = data.get("servers", [])

        variants: list[VideoVariant] = []

        for server in servers:
            name = server.get("name", "")
            src = server.get("src", "")

            video = await self._extract_video(src, name)
            if video is None:
                continue

            hls_url = video.get("hls", "") or video.get("dash", "")
            if not hls_url:
                continue

            qualities = await self._probe_qualities(hls_url)
            subs = video.get("subtitles", [])

            for q in qualities:
                variants.append(
                    VideoVariant(
                        source_ref=json.dumps({
                            "video_url": _fix_url(hls_url),
                            "server": name,
                            "quality": q,
                            "subtitles": [(s.get("name", ""), _fix_url(s.get("src", ""))) for s in subs],
                        }),
                        resolution=q,
                        audio=AudioType.SUBBED,
                        subtitles=[s.get("language", "") for s in subs],
                    )
                )

        return variants

    async def _extract_video(self, src: str, server_name: str) -> dict | None:
        final_url = src.replace("/vast", "/cat-player/player") if "/vast" in src else src

        try:
            resp = await self.http.get(final_url)
            resp.raise_for_status()
            html = resp.text
        except httpx.HTTPError:
            return None

        clean = html.replace("&quot;", '"')

        if '"manifest":[0,' in clean:
            return self._parse_new_player(clean)

        if "cid: '" not in html:
            return None

        return await self._extract_legacy(html, final_url, server_name)

    def _parse_new_player(self, clean_html: str) -> dict | None:
        m = re.search(r'manifest":\[0,"(?:https?:)?(//[^"]+)"', clean_html)
        if not m:
            return None

        manifest_url = _fix_url(m.group(1))

        subs = []
        for sm in re.finditer(r'"language":\[\d+,"([^"]+)"][^}]+?"name":\[\d+,"([^"]*)"][^}]+?"src":\[\d+,"([^"]+)"', clean_html):
            lang = sm.group(1)
            sub_name = sm.group(2)
            raw_url = sm.group(3).replace("\\/", "/")
            subs.append({"name": f"{sub_name} ({lang})", "language": lang, "src": _fix_url(raw_url)})

        return {
            "hls": manifest_url if ".m3u8" in manifest_url else "",
            "dash": manifest_url if ".mpd" in manifest_url else "",
            "subtitles": subs,
        }

    async def _extract_legacy(self, html: str, final_url: str, server_name: str) -> dict | None:
        key = SERVER_AES_KEYS.get(server_name)
        is_bird = server_name == "BirdStream"

        parsed = urllib.parse.urlparse(final_url)
        host = parsed.hostname

        mid_param = "mid" if server_name == "DuckStream" else "id"
        qs = parse_qs(parsed.query)
        query = qs.get(mid_param, [None])[0]
        if not query:
            return None

        try:
            hex_data = html.split("cid: '")[1].split("'")[0]
            decoded = bytes.fromhex(hex_data).decode()
            parts = decoded.split("|")
        except (IndexError, ValueError):
            return None

        cid_ip = parts[0] if len(parts) > 0 else ""
        cid_route = parts[1].replace("player.php", "source.php") if len(parts) > 1 else ""

        timestamp = str(int(time.time()) + 60)

        order = ["IP", "USERAGENT", "ROUTE", "MID", "KEY"] if is_bird else ["IP", "USERAGENT", "ROUTE", "MID", "TIMESTAMP", "KEY"]

        sig_parts = {
            "IP": cid_ip,
            "USERAGENT": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            "ROUTE": cid_route,
            "MID": query,
            "TIMESTAMP": timestamp,
            "KEY": key.decode() if key else "",
        }
        sig_str = "".join(sig_parts[k] for k in order if k in sig_parts)
        sig = _sha1(sig_str)

        source_url = f"https://{host}{cid_route}?{mid_param}={query}"
        if not is_bird:
            source_url += f"&e={timestamp}"
        source_url += f"&s={sig}"

        try:
            source_resp = await self.http.get(
                source_url,
                headers={"Referer": final_url, "Origin": f"https://{host}"},
            )
            source_resp.raise_for_status()
            body = source_resp.text
        except httpx.HTTPError:
            return None

        try:
            raw = body.split(':"')[1].split('"')[0].replace("\\", "")
            encrypted_data, iv_hex = raw.rsplit(":", 1)
        except (IndexError, ValueError):
            return None

        iv = bytes.fromhex(iv_hex)
        encrypted_bytes = encrypted_data.encode()

        if not key:
            return None

        try:
            decrypted = _decrypt_aes_256_cbc(key, iv, encrypted_bytes)
            return json.loads(decrypted)
        except Exception:
            return None

    async def _probe_qualities(self, url: str) -> list[str]:
        if ".mpd" in url:
            return [self.preferred_quality]

        if ".m3u8" in url:
            try:
                resp = await self.http.get(url)
                resp.raise_for_status()
                lines = resp.text.splitlines()
                qualities = []
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                        if m:
                            qualities.append(f"{m.group(1)}p")
                        elif i + 1 < len(lines):
                            q = re.search(r"(\d+)p", lines[i + 1])
                            if q:
                                qualities.append(f"{q.group(1)}p")
                return sorted(set(qualities), key=lambda x: int(x.rstrip("p")), reverse=True) or [self.preferred_quality]
            except httpx.HTTPError:
                return [self.preferred_quality]

        return [self.preferred_quality]

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
        quality = info.get("quality", variant.resolution)
        server = info.get("server", "VidStreaming")

        dest.parent.mkdir(parents=True, exist_ok=True)

        if quality != self.preferred_quality and ".m3u8" in video_url:
            try:
                resp = await self.http.get(video_url)
                resp.raise_for_status()
                lines = resp.text.splitlines()
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        if f"RESOLUTION=x{quality.rstrip('p')}" in line or re.search(r"RESOLUTION=\d+x\d+", line):
                            if i + 1 < len(lines):
                                quality_url = _fix_url(lines[i + 1], video_url)
                                if quality_url.startswith("http"):
                                    video_url = quality_url
                                    break
            except httpx.HTTPError:
                pass

        ext = ".mp4"
        if ".m3u8" in video_url:
            ext = ".mp4"
        elif ".mpd" in video_url:
            ext = ".mp4"

        dest = dest.with_suffix(ext)

        ffmpeg_args = [
            "ffmpeg",
            "-y",
            "-i", video_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc" if ext == ".mp4" else "copy",
            str(dest),
        ]

        process = await asyncio.create_subprocess_exec(
            *ffmpeg_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {process.returncode}): {stderr.decode(errors='replace')[:500]}")

        total = dest.stat().st_size
        if on_progress:
            await on_progress(total, total)

        sha = hashlib.sha256()
        sha.update(dest.read_bytes())

        return {
            "checksum": sha.hexdigest(),
            "bytes": total,
            "complete": True,
        }
