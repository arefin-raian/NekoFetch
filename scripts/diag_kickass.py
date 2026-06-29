"""Live diagnostic for the KickAssAnime path — mirror of diag_anikoto.

search -> get_episodes -> get_variants (server resolution) -> probe a real segment.
Reveals extraction breakage (0 episodes / 0 servers) and segment reachability.
"""

from __future__ import annotations

import asyncio
import json
import sys
from urllib.parse import urljoin

import httpx

from nekofetch.sources.kickassanime import KickAssAnimeSource


def _brief(r: httpx.Response) -> str:
    h = r.headers
    return (f"HTTP {r.status_code} server={h.get('server','?')} "
            f"cf-ray={h.get('cf-ray','-')} cf-mitigated={h.get('cf-mitigated','-')} "
            f"ct={h.get('content-type','-')}")


async def main(query: str) -> None:
    src = KickAssAnimeSource()
    print(f"### 1. search({query!r})")
    stubs = await src.search(query)
    print(f"    -> {len(stubs)} results")
    if not stubs:
        await src.close(); return
    stub = stubs[0]
    print(f"    top: {stub.title}  ref={stub.source_ref}")

    print("### 2. get_episodes")
    eps = await src.get_episodes(stub.source_ref)
    print(f"    -> {len(eps)} episodes")
    if not eps:
        await src.close(); return
    ep = eps[0]
    print(f"    ep1 ref={ep.source_ref}")

    print("### 3. get_variants (server/stream resolution)")
    variants = await src.get_variants(ep.source_ref)
    print(f"    -> {len(variants)} variants")
    for v in variants[:6]:
        info = json.loads(v.source_ref)
        print(f"    {v.audio.value} {v.resolution}: server={info.get('server')} "
              f"hls={info.get('video_url','')[:80]}")

    print("### 4. probe m3u8 + first segment of variant[0]")
    if variants:
        info = json.loads(variants[0].source_ref)
        url = info["video_url"]
        from urllib.parse import urlparse
        ref = f"https://{urlparse(info.get('player_url') or url).hostname}/"
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                pl = await c.get(url, headers={"Referer": ref, "Origin": ref.rstrip("/")})
            print(f"    m3u8 -> {_brief(pl)}")
            if pl.status_code == 200 and "#EXT" in pl.text[:200]:
                lines = [l.strip() for l in pl.text.splitlines() if l.strip() and not l.startswith('#')]
                media_url, media_txt = url, pl.text
                if "#EXT-X-STREAM-INF" in pl.text and lines:
                    media_url = urljoin(url, lines[0])
                    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                        media_txt = (await c.get(media_url, headers={"Referer": ref})).text
                segs = [l.strip() for l in media_txt.splitlines() if l.strip() and not l.startswith('#')]
                print(f"    media playlist: {len(segs)} segments")
                if segs:
                    seg = urljoin(media_url, segs[0])
                    for label, hdrs in (("with referer", {"Referer": ref, "Origin": ref.rstrip('/')}),
                                        ("no referer", {})):
                        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
                            r = await c.get(seg, headers=hdrs)
                        print(f"      seg [{label}] -> {_brief(r)} bytes={len(r.content)}")
            else:
                print(f"    m3u8 body[:120]={pl.text[:120]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"    probe ERROR {type(exc).__name__}: {exc}")
    await src.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Takopi's Original Sin"))
