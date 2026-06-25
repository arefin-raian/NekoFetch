"""Prove the fix end-to-end: resolve -> recurse playlist -> demask segments -> clean .ts"""
import asyncio
import base64
import re
import httpx
from urllib.parse import urljoin
from pathlib import Path
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"
MAPPER_API = "https://mapper.nekostream.site/api/mal/"
ANIME_ID = 1498
REFERER = "https://vibeplayer.site/"
OUT = Path(__file__).parent / "downloads" / "FIXED_sub.ts"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def ts_start(seg: bytes) -> int:
    """First offset where the 188-byte MPEG-TS grid locks (strips fake img header)."""
    n = len(seg)
    for s in [n % 188 + 188 * i for i in range(4)] + list(range(0, min(n, 8192))):
        if s < n and seg[s] == 0x47:
            hits = sum(1 for k in range(s, min(n, s + 188 * 40), 188) if seg[k] == 0x47)
            if hits >= 38:
                return s
    return 0


async def resolve_media_playlist(c, master, want="1080"):
    """Walk master -> variant. Returns (media_url, media_text)."""
    txt = (await c.get(master, headers={"referer": REFERER})).text
    if "#EXT-X-STREAM-INF" not in txt:
        return master, txt
    lines = txt.splitlines()
    variants = []  # (height, url)
    for i, ln in enumerate(lines):
        if ln.startswith("#EXT-X-STREAM-INF"):
            m = re.search(r"RESOLUTION=\d+x(\d+)", ln)
            h = int(m.group(1)) if m else 0
            variants.append((h, urljoin(master, lines[i + 1].strip())))
    variants.sort()
    pick = next((u for h, u in variants if str(h) == want), variants[-1][1])
    return await resolve_media_playlist(c, pick, want)


async def resolve_sub_url(c):
    r = await c.post(f"{BASE}/ajax/episode/list/{ANIME_ID}", data={"style": "default", "vrf": ""})
    ep = BeautifulSoup(r.json()["result"], "html.parser").select("a[data-ids]")[0]
    md = (await c.get(f"{MAPPER_API}{ep.get('data-mal')}/{ep.get('data-slug')}/{ep.get('data-timestamp')}")).json()
    for k in md:
        if "Stream" not in k:
            continue
        code = md[k].get("sub")
        code = code.get("url") if isinstance(code, dict) else code
        if not code:
            continue
        u = (await c.get(f"{BASE}/ajax/server", params={"get": code})).json().get("result", {}).get("url", "")
        if "#" in u:
            return base64.b64decode(u.split("#")[1]).decode()
    raise RuntimeError("no sub url")


async def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": UA, "x-requested-with": "XMLHttpRequest",
                                          "referer": f"{BASE}/"}) as c:
        master = await resolve_sub_url(c)
        media, mt = await resolve_media_playlist(c, master, want="720")
        segs = [urljoin(media, ln.strip()) for ln in mt.splitlines()
                if ln.strip() and not ln.startswith("#")]
        print(f"media: {media}\nsegments: {len(segs)}")

        sem = asyncio.Semaphore(10)

        async def grab(i, su):
            async with sem:
                for _ in range(3):
                    try:
                        raw = (await c.get(su, headers={"referer": REFERER})).content
                        return i, raw[ts_start(raw):]
                    except Exception:
                        await asyncio.sleep(1)
                return i, b""

        results = await asyncio.gather(*(grab(i, su) for i, su in enumerate(segs)))
        clean = bytearray()
        for _, chunk in sorted(results):
            clean += chunk
        OUT.write_bytes(clean)

        rem = len(clean) % 188
        start = rem if clean[rem:rem + 1] == b"\x47" else 0
        rng = range(start, len(clean) - 188, 188)
        hits = sum(1 for k in rng if clean[k] == 0x47)
        n = len(rng)
        print(f"wrote {OUT.name}: {len(clean)/1048576:.1f} MB")
        print(f"TS sync integrity: {100*hits/n:.2f}%  ({'CLEAN' if hits/n > 0.999 else 'BROKEN'})")


asyncio.run(main())
