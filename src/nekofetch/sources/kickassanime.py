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
import time
import urllib.parse
from pathlib import Path
from urllib.parse import parse_qs, urljoin

import httpx

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
from nekofetch.sources._mux import (
    WANTED_AUDIO,
    assemble_final,
    audio_label,
    normalize_audio_lang,
)
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
    if not raw.startswith("http") and base:
        from urllib.parse import urljoin
        return urljoin(base, raw)
    return re.sub(r"^(https?)//+", r"\1://", raw)


# ISO 639-1 → 639-2 mapping for MKV language metadata
_LANG_MAP: dict[str, str] = {
    "ja": "jpn", "jp": "jpn",
    "en": "eng", "us": "eng",
    "es": "spa",
    "ko": "kor",
    "zh": "zho", "cn": "zho",
    "fr": "fra",
    "de": "deu",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "ar": "ara",
    "hi": "hin",
    "th": "tha",
    "vi": "vie",
    "id": "ind",
    "ms": "msa",
    "tl": "tgl",
}


def _to_iso6392(code: str) -> str:
    return _LANG_MAP.get(code.lower(), code)


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
                timeout=RECOMMENDED_TIMEOUT,
                limits=RECOMMENDED_LIMITS,
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

        seen: set[tuple[int, str]] = set()
        episodes: list[Episode] = []

        for lang in languages:
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

                    ep_key = (num, lang)
                    if ep_key not in seen:
                        seen.add(ep_key)
                        display = f"Ep. {ep_str}"
                        if ep_title:
                            display += f" - {ep_title}"
                        episodes.append(
                            Episode(
                                source_ref=f"{slug}/{lang}/ep-{ep_str}-{ep_slug}",
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

    async def _episode_numbers(self, slug: str, lang: str) -> set[int]:
        """Episode numbers available for one audio language (cheap listing call)."""
        nums: set[int] = set()
        page = 1
        while True:
            try:
                resp = await self.http.get(
                    f"{self.api_url}/{slug}/episodes?page={page}&lang={lang}"
                )
            except httpx.HTTPError:
                break
            if resp.status_code != 200:
                break
            data = resp.json()
            result = data.get("result", [])
            if not result:
                break
            for ep in result:
                s = ep.get("episode_string", "")
                if s.replace(".", "", 1).isdigit():
                    nums.add(int(float(s)))
            pages = data.get("pages", [])
            if page >= len(pages):
                break
            page += 1
        return nums

    async def coverage(self, *titles: str) -> SourceCoverage:
        """Per-language episode counts — exposes sub/dub variance directly.

        Matches by AniList English + Romaji so we never report the wrong show.
        """
        from nekofetch.sources._match import find_verified_match

        stub = await find_verified_match(self, list(titles))
        if not stub:
            return SourceCoverage(source=self.name, matched_title=titles[0] if titles else "",
                                  source_ref="", available=False, note="no confident match")
        slug = stub.source_ref.strip("/")
        langs = await self._fetch_languages(slug)
        per_lang: dict[str, set[int]] = {}
        for lang in langs:
            per_lang[lang] = await self._episode_numbers(slug, lang)
        all_nums: set[int] = set().union(*per_lang.values()) if per_lang else set()
        sub = sum(len(n) for lg, n in per_lang.items() if lg.lower().startswith("ja"))
        dub = sum(len(n) for lg, n in per_lang.items() if lg.lower().startswith("en"))
        return SourceCoverage(
            source=self.name, matched_title=stub.title, source_ref=slug,
            total_episodes=len(all_nums), seasons=1,
            sub_episodes=sub, dub_episodes=dub,
            available=bool(all_nums),
        )

    async def get_variants(self, episode_ref: str) -> list[VideoVariant]:
        slug, ep_path = episode_ref.split("/", 1) if "/" in episode_ref else (episode_ref, "")
        if not ep_path:
            return []

        # ep_path may be "<locale>/ep-N-<slug>" or just "ep-N-<slug>".
        lang = self.preferred_lang
        parts = ep_path.split("/")
        if len(parts) >= 2 and re.match(r"^[a-z]{2}(-[\w]+)?$", parts[0]):
            lang = parts[0]
            ep_path = "/".join(parts[1:])

        stream = await self._resolve_stream(slug, ep_path)
        if not stream:
            return []

        ep_num = self._ep_num(ep_path)
        audio_type = AudioType.DUBBED if lang == self.second_lang else AudioType.SUBBED
        lang_label = "english" if lang.startswith("en") else "japanese"

        variants: list[VideoVariant] = []
        for q in stream["qualities"]:
            variants.append(
                VideoVariant(
                    source_ref=json.dumps({
                        "video_url": _fix_url(stream["hls"]),
                        "server": stream["server"],
                        "quality": q,
                        "player_url": stream["player_url"],
                        "subtitles": stream["subtitles"],
                        # context for cross-language (separate-variant) merging:
                        "kaa_slug": slug,
                        "kaa_locale": lang,
                        "kaa_ep_num": ep_num,
                    }),
                    resolution=q,
                    audio=audio_type,
                    languages=[lang_label],
                    subtitles=[s[0] for s in stream["subtitles"]],
                )
            )
        return variants

    @staticmethod
    def _ep_num(ep_path: str) -> str:
        m = re.search(r"ep-([\d.]+)", ep_path)
        return m.group(1) if m else "1"

    async def _resolve_stream(self, slug: str, ep_path: str) -> dict | None:
        """Resolve one episode (slug + ep-path) to a playable stream.

        Returns ``{hls, player_url, server, qualities, subtitles}`` for the first
        working server, or ``None``. Tries the JSON API then the page-scrape
        fallback, so it works across modern and older page layouts.
        """
        ep_part = ep_path.replace("ep-", "episode/ep-")
        url = f"{self.api_url}/{slug}/{ep_part}"
        resp = await self._retry_get(url, {"Referer": f"{self.base_url}/"}, retries=3)
        if resp.status_code == 200:
            servers = resp.json().get("servers", [])
        else:
            log.warning("get_variants.api_failed", url=url, status=resp.status_code)
            servers = await self._scrape_servers_from_page(f"{self.base_url}/{slug}/{ep_path}")

        for server in servers:
            video = await self._extract_video(server.get("src", ""), server.get("name", ""))
            if not video:
                continue
            hls_url = video.get("hls", "") or video.get("dash", "")
            if not hls_url:
                continue
            player_url = video.get("player_url", server.get("src", ""))
            origin_host = urllib.parse.urlparse(player_url).hostname
            probe_referer = f"https://{origin_host}/" if origin_host else None
            return {
                "hls": hls_url,
                "player_url": player_url,
                "server": server.get("name", ""),
                "qualities": await self._probe_qualities(hls_url, referer=probe_referer),
                "subtitles": [
                    (s.get("name", ""), _fix_url(s.get("src", "")))
                    for s in video.get("subtitles", [])
                ],
            }
        return None


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
            result = self._parse_new_player(clean)
            if result:
                result["player_url"] = final_url
            return result

        if "cid: '" not in html:
            return None

        result = await self._extract_legacy(html, final_url, server_name)
        if result:
            result["player_url"] = final_url
        return result

    @staticmethod
    def _js_obj_to_json(raw: str) -> str:
        """Convert a JS-style object literal to strict JSON by quoting bare keys and single-quoted strings."""
        s = re.sub(r"(?<=[{,])\s*([a-zA-Z_]\w*)\s*(?=:)", r'"\1"', raw)
        s = re.sub(r"'([^']*?)'", r'"\1"', s)
        return s

    async def _scrape_servers_from_page(self, page_url: str) -> list[dict]:
        """Fallback: extract server list from episode page HTML when the JSON API is blocked."""
        try:
            resp = await self._retry_get(page_url, {"Referer": f"{self.base_url}/"}, retries=2)
            if resp.status_code != 200:
                return []
            html = resp.text
        except httpx.HTTPError:
            return []

        servers: list[dict] = []

        # Pattern 1: embedded JSON in a script tag — servers array or object
        for pattern in (
            r'<script[^>]*>[^<]*?servers\s*=\s*(\[[\s\S]*?\])\s*;',
            r'<script[^>]*>[^<]*?window\.__DATA__\s*=\s*(\{[\s\S]*?\})\s*;',
            r'servers:\s*(\[[\s\S]*?\])',
        ):
            m = re.search(pattern, html)
            if m:
                raw = m.group(1).rstrip(",")
                for attempt in (raw, self._js_obj_to_json(raw)):
                    try:
                        data = json.loads(attempt)
                        if isinstance(data, list):
                            if data and "src" in data[0]:
                                return data
                        elif isinstance(data, dict):
                            sv = data.get("servers") or data.get("serverList") or data.get("sources") or []
                            if sv and "src" in sv[0]:
                                return sv
                    except (json.JSONDecodeError, TypeError):
                        continue

        # Pattern 2: data-server / data-src attributes on page elements
        for sm in re.finditer(
            r'data-server=["\']([^"\']+)["\'][^>]*data-src=["\']([^"\']+)["\']',
            html,
        ):
            servers.append({"name": sm.group(1), "src": sm.group(2)})
        if servers:
            return servers

        # Pattern 3: krussdomi player links in the page
        seen: set[str] = set()
        for sm in re.finditer(r'href="(https://krussdomi\.com/cat-player/player[^"]+)"', html):
            url = sm.group(1)
            if url not in seen:
                seen.add(url)
                name = "VidStreaming"
                servers.append({"name": name, "src": url})
        if servers:
            return servers

        return []

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

    async def _probe_qualities(self, url: str, referer: str | None = None) -> list[str]:
        if ".mpd" in url:
            return [self.preferred_quality]

        if ".m3u8" in url:
            try:
                resp = await self.http.get(
                    url,
                    headers={"Referer": referer or "https://kaa.lt/"},
                )
                resp.raise_for_status()
                lines = resp.text.splitlines()
                qualities: list[str] = []
                for i, line in enumerate(lines):
                    if line.startswith("#EXT-X-STREAM-INF"):
                        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
                        if m:
                            qualities.append(f"{m.group(1)}p")
                if not qualities:
                    for i, line in enumerate(lines):
                        if line.startswith("#EXT-X-STREAM-INF"):
                            if i + 1 < len(lines):
                                q = re.search(r"(\d+)p", lines[i + 1])
                                if q:
                                    qualities.append(f"{q.group(1)}p")
                return sorted(
                    set(qualities), key=lambda x: int(x.rstrip("p")), reverse=True
                ) or [self.preferred_quality]
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
        player_url = info.get("player_url", "")
        subs = info.get("subtitles", [])

        dest.parent.mkdir(parents=True, exist_ok=True)
        if on_progress:
            await on_progress(0, 1)

        # Episode language only hints the fallback label when a stream has no
        # separate audio renditions (embedded audio of unknown language).
        default_lang = "en" if variant.audio == AudioType.DUBBED else "ja"

        if ".m3u8" in video_url:
            out, extra = await self._download_hls(
                video_url, dest, player_url=player_url, subtitles=subs,
                quality=quality, on_progress=on_progress, default_lang=default_lang,
                locale=info.get("kaa_locale", ""),
            )
        else:
            out, extra = await self._download_direct(
                video_url, dest, player_url, subs, on_progress,
            )

        total = out.stat().st_size
        if on_progress:
            await on_progress(total, total)

        sha = hashlib.sha256()
        sha.update(out.read_bytes())

        return {
            "checksum": sha.hexdigest(),
            "bytes": total,
            "complete": True,
            "container": out.suffix.lstrip("."),
            **extra,
        }

    async def _retry_get(self, url: str, headers: dict, retries: int = 5) -> httpx.Response:
        for attempt in range(retries):
            resp = await self.http.get(url, headers=headers)
            if resp.status_code < 500:
                return resp
            await asyncio.sleep(min(2 ** attempt, 10))
        return resp

    async def _download_hls(
        self,
        manifest_url: str,
        dest: Path,
        *,
        player_url: str = "",
        subtitles: list | None = None,
        quality: str = "1080p",
        on_progress: ProgressCallback | None = None,
        default_lang: str = "ja",
        locale: str = "",
    ) -> tuple[Path, dict]:
        """Download video + ja/en/hi audio + subtitles, mux into one MKV.

        Handles BOTH delivery shapes:
          1. one master with multiple ``#EXT-X-MEDIA:TYPE=AUDIO`` renditions
             (modern multi-audio) — pick the ja/en/hi renditions; video is silent.
          2. separate per-language sources selected via the Sub/Dub dropdown
             (older/alternative) — the base video carries one embedded audio, and
             the other languages are downloaded from their own streams and merged.
        Subtitles are cleaned/styled/branded; ffmpeg muxes everything into one
        ``.mkv`` with per-track language metadata, labelled SUBBED / DUBBED /
        Dual Audio / Multi Audio by which of ja/en/hi ended up present.
        """
        origin_host = urllib.parse.urlparse(player_url).hostname if player_url else "krussdomi.com"
        headers = {
            "Accept": "*/*",
            "Origin": f"https://{origin_host}",
            "Referer": f"https://{origin_host}/",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
            ),
        }
        warnings: list[str] = []
        stem = dest.stem
        q = quality.rstrip("p")
        names = {"ja": "Japanese", "en": "English", "hi": "Hindi"}

        # Parse audio renditions in THIS manifest only. Dual/Multi is determined
        # solely by how many language-tagged audio tracks live in one manifest —
        # we never merge separate Sub/Dub variants (they can be different edits).
        master_txt = (await self._retry_get(manifest_url, headers)).text
        tagged: dict[str, tuple[str, str]] = {}   # canon -> (name, uri)
        untagged: list[tuple[str, str]] = []      # (name, uri) with no/foreign lang
        for line in master_txt.splitlines():
            if not line.startswith("#EXT-X-MEDIA:TYPE=AUDIO"):
                continue
            uri = re.search(r'URI="([^"]+)"', line)
            if not uri:
                continue
            au_url = urljoin(manifest_url, uri.group(1))
            name_m = re.search(r'NAME="([^"]+)"', line)
            lang_m = re.search(r'LANGUAGE="([^"]+)"', line)
            canon = normalize_audio_lang(lang_m.group(1) if lang_m else "")
            if canon and canon not in tagged:
                tagged[canon] = (name_m.group(1) if name_m else names[canon], au_url)
            elif not canon:
                untagged.append((name_m.group(1) if name_m else "Audio", au_url))

        stats: dict = {}
        video_ts = await download_hls_ts(
            self.http, manifest_url, headers, q,
            dest.with_name(f".{stem}.video"), on_progress, stats=stats,
        )

        covered: set[str] = set()
        audio_files: list[tuple[Path, str, str]] = []
        embedded_audio: tuple[str, str] | None = None
        primary = normalize_audio_lang(locale) or default_lang

        if len(tagged) >= 2:
            # Genuine multi-audio manifest -> Dual / Multi (ja/en/hi only).
            for i, canon in enumerate(c for c in WANTED_AUDIO if c in tagged):
                name, au_url = tagged[canon]
                try:
                    ap = await download_hls_ts(
                        self.http, au_url, headers, q,
                        dest.with_name(f".{stem}.audio{i}.{canon}"),
                    )
                    audio_files.append((ap, name, canon))
                    covered.add(canon)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"audio rendition '{name}' failed: {exc}")
        elif len(tagged) == 1:
            # Single language-tagged rendition; video is silent.
            canon, (name, au_url) = next(iter(tagged.items()))
            ap = await download_hls_ts(
                self.http, au_url, headers, q, dest.with_name(f".{stem}.audio.{canon}"),
            )
            audio_files.append((ap, name, canon))
            covered.add(canon)
        elif untagged:
            # One audio group with no language (e.g. Solo Leveling's "Default");
            # it is this episode's single language -> SUBBED/DUBBED.
            name, au_url = untagged[0]
            ap = await download_hls_ts(
                self.http, au_url, headers, q, dest.with_name(f".{stem}.audio.{primary}"),
            )
            audio_files.append((ap, names.get(primary, name), primary))
            covered.add(primary)
        else:
            # No separate audio groups -> audio is embedded in the video stream.
            embedded_audio = (names.get(primary, primary.upper()), primary)
            covered.add(primary)

        label = audio_label(covered)

        # --- subtitles ---
        sub_tracks: list[tuple[str, str, Path]] = []
        sub_info: list[dict] = []
        if subtitles:
            pairs = [
                (s[0], s[1]) for s in subtitles
                if isinstance(s, (list, tuple)) and len(s) >= 2
            ]
            sub_info = await download_subtitles(self.http, pairs, headers, dest)
            for s in sub_info:
                if s.get("saved"):
                    lang_m = re.search(r"\((\w[\w-]*)\)", s.get("label", ""))
                    lang = lang_m.group(1) if lang_m else "und"
                    sub_tracks.append((s["label"], lang, Path(s["saved"])))

        # --- mux ---
        if not find_ffmpeg():
            out = maybe_remux(video_ts, dest)
            warnings.append("ffmpeg not found — saved video-only .ts (no mux)")
            return out, {"stats": stats, "subtitles": sub_info, "label": label,
                         "audio_tracks": len(audio_files), "warnings": warnings}

        mkv, sub_meta = await assemble_final(
            video_ts, audio_files, sub_tracks, dest, title=f"{stem} [{label}]",
            embedded_audio=embedded_audio,
        )
        audio_tracks = []
        if embedded_audio is not None:
            audio_tracks.append({"name": embedded_audio[0], "lang": embedded_audio[1],
                                 "source": "embedded"})
        audio_tracks += [{"name": n, "lang": lng, "source": "external"}
                         for _p, n, lng in audio_files]
        return mkv, {
            "stats": stats,
            "label": label,
            "subtitles": sub_meta or sub_info,
            "audio_tracks": audio_tracks,
            "warnings": warnings,
        }

    async def _download_direct(
        self,
        url: str,
        dest: Path,
        player_url: str,
        subtitles: list | None,
        on_progress: ProgressCallback | None,
    ) -> tuple[Path, dict]:
        """Stream a progressive (mp4) file straight to disk, no ffmpeg."""
        origin_host = urllib.parse.urlparse(player_url).hostname if player_url else "kaa.lt"
        headers = {
            "Accept": "*/*",
            "Origin": f"https://{origin_host}",
            "Referer": f"https://{origin_host}/",
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
            ),
        }
        out = dest.with_suffix(Path(url.split("?")[0]).suffix or ".mp4")
        total = 0
        async with self.http.stream("GET", url, headers=headers) as resp:
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

        sub_info: list[dict] = []
        if subtitles:
            pairs = [
                (s[0], s[1]) for s in subtitles
                if isinstance(s, (list, tuple)) and len(s) >= 2
            ]
            sub_info = await download_subtitles(self.http, pairs, headers, out)
        return out, {"stats": {"bytes": total}, "subtitles": sub_info, "warnings": []}
