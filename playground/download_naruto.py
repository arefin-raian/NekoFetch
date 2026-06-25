"""Download Naruto Shippuden Episode 1 - Sub (720p) & Dub (1080p)."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"
MAPPER_API = "https://mapper.nekostream.site/api/mal/"
NARUTO_SLUG = "naruto-shippuden-c8gov"
ANIME_ID = 1498
DL_DIR = Path(__file__).parent / "downloads"


async def fetch_json(client: httpx.AsyncClient, url: str, **kwargs):
    r = await client.get(url, **kwargs)
    r.raise_for_status()
    return r.json()


async def download_with_ytdlp(url: str, dest: Path, referer: str, quality: str = ""):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = dest.with_suffix(".mp4")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--concurrent-fragments", "10",
        "--referer", referer,
        "--add-headers", f"Origin: {referer}",
        "--add-headers", f"Referer: {referer}",
        "--user-agent", (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36"
        ),
        "--retries", "10",
        "--fragment-retries", "15",
        "--fixup", "force",
        "--output", str(dest),
        url,
    ]
    if quality:
        cmd.insert(3, "--format-sort")
        cmd.insert(4, f"res:{quality}")

    for attempt in range(3):
        print(f"  yt-dlp attempt {attempt + 1}/3...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            size_mb = dest.stat().st_size / (1024 * 1024)
            print(f"  Done: {size_mb:.1f} MB")
            return
        err = stderr.decode(errors="replace")[-500:]
        print(f"  yt-dlp failed (exit {proc.returncode}): {err}")
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)

    raise RuntimeError(f"yt-dlp failed after 3 attempts for {url}")


async def get_video_url(client: httpx.AsyncClient, mal_id: str, ep_slug: str, ts: str, audio: str) -> str | None:
    """Get the video URL for a specific episode and audio type from mapper API."""
    mapper_url = f"{MAPPER_API}{mal_id}/{ep_slug}/{ts}"
    try:
        mapper_data = await fetch_json(client, mapper_url)
    except Exception as e:
        print(f"  Mapper API failed: {e}")
        return None

    for stream_key in mapper_data:
        if "Stream" not in stream_key:
            continue
        audio_data = mapper_data[stream_key].get(audio)
        if not audio_data:
            continue

        server_code = audio_data["url"] if isinstance(audio_data, dict) else audio_data
        if not server_code:
            continue

        try:
            r = await client.get(f"{BASE}/ajax/server", params={"get": server_code})
            r.raise_for_status()
            result = r.json().get("result", {})
            result_url = result.get("url", "")
            if "#" in result_url:
                decoded = base64.b64decode(result_url.split("#")[1]).decode("utf-8")
                return decoded
        except Exception as e:
            print(f"  Server resolve failed: {e}")
            continue

    return None


async def main():
    DL_DIR.mkdir(parents=True, exist_ok=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
        "referer": f"{BASE}/",
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as c:
        # ---- Step 1: Get episode list ----
        print("[1] Fetching episode list...")
        r = await c.post(
            f"{BASE}/ajax/episode/list/{ANIME_ID}",
            data={"style": "default", "vrf": ""},
        )
        r.raise_for_status()
        ep_data = r.json()
        ep_soup = BeautifulSoup(ep_data.get("result", ""), "html.parser")
        ep_links = ep_soup.select("a[data-ids]")
        print(f"    Found {len(ep_links)} episodes")

        if not ep_links:
            print("[-] No episodes found!")
            return

        ep1 = ep_links[0]
        mal_id = ep1.get("data-mal", "")
        ep_slug = ep1.get("data-slug", "1")
        ts = ep1.get("data-timestamp", "")
        print(f"    Episode 1: mal={mal_id}, slug={ep_slug}, ts={ts}")

        # ---- Step 2: Get sub video URL (720p) ----
        print("\n[2] Resolving sub video URL...")
        sub_url = await get_video_url(c, mal_id, ep_slug, ts, "sub")
        if sub_url:
            print(f"    Sub URL: {sub_url[:100]}...")
        else:
            print("[-] No sub URL found")

        # ---- Step 3: Get dub video URL (1080p) ----
        print("\n[3] Resolving dub video URL...")
        dub_url = await get_video_url(c, mal_id, ep_slug, ts, "dub")
        if dub_url:
            print(f"    Dub URL: {dub_url[:100]}...")
        else:
            print("[-] No dub URL found")

        # ---- Step 4: Download sub (720p) ----
        if sub_url:
            print("\n[4] Downloading SUB (720p)...")
            await download_with_ytdlp(
                sub_url,
                DL_DIR / "Naruto_Shippuden_Ep01_SUB_720p",
                referer="https://vibeplayer.site/",
                quality="720",
            )

        # ---- Step 5: Download dub (1080p) ----
        if dub_url:
            print("\n[5] Downloading DUB (1080p)...")
            await download_with_ytdlp(
                dub_url,
                DL_DIR / "Naruto_Shippuden_Ep01_DUB_1080p",
                referer="https://vibeplayer.site/",
                quality="1080",
            )

    print("\n[*] All done!")


if __name__ == "__main__":
    asyncio.run(main())
