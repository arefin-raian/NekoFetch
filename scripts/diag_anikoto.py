"""Live diagnostic for the AniKoto download path.

Drives the REAL extraction pipeline against the live site and pinpoints exactly
where/why a segment fetch fails — proving whether the x-requested-with header is
the 521 cause by fetching the same segment with old vs new headers.

Run: python scripts/diag_anikoto.py "Takopi's Original Sin"
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import urljoin

import httpx

from nekofetch.sources.anikoto import USER_AGENT, AnikotoSource


def _hdr_brief(resp: httpx.Response) -> str:
    h = resp.headers
    return (f"HTTP {resp.status_code} server={h.get('server','?')} "
            f"cf-ray={h.get('cf-ray','-')} cf-mitigated={h.get('cf-mitigated','-')} "
            f"ct={h.get('content-type','-')} len={h.get('content-length','-')}")


async def _probe_segment(client: httpx.AsyncClient, seg_url: str, referer: str) -> None:
    host_root = referer.rstrip("/")
    variants = {
        "NEW (browser: UA+Accept, no xhr)": {
            "User-Agent": USER_AGENT, "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer, "Origin": host_root,
        },
        "OLD (xhr header, no Accept)": {
            "User-Agent": USER_AGENT, "x-requested-with": "XMLHttpRequest",
            "Referer": referer, "Origin": host_root,
        },
        "NO referer/origin": {"User-Agent": USER_AGENT, "Accept": "*/*"},
    }
    for label, hdrs in variants.items():
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(seg_url, headers=hdrs)
            print(f"    [{label}] -> {_hdr_brief(r)}")
        except Exception as exc:  # noqa: BLE001
            print(f"    [{label}] -> ERROR {type(exc).__name__}: {exc}")


async def main(query: str) -> None:
    src = AnikotoSource()
    print(f"### 1. search({query!r})")
    stubs = await src.search(query)
    print(f"    -> {len(stubs)} results")
    if not stubs:
        print("    NO RESULTS — extraction blocked at search (Cloudflare?).")
        await src.close()
        return
    stub = stubs[0]
    print(f"    top: {stub.title}  ref={stub.source_ref}")

    print("### 2. get_episodes")
    eps = await src.get_episodes(stub.source_ref)
    print(f"    -> {len(eps)} episodes")
    if not eps:
        await src.close()
        return
    ep = eps[0]
    print(f"    ep1 ref={ep.source_ref}")

    print("### 3. get_variants (server enumeration)")
    variants = await src.get_variants(ep.source_ref)
    print(f"    -> {len(variants)} variants")
    import json
    for v in variants:
        info = json.loads(v.source_ref)
        cands = info.get("candidates", [])
        print(f"    {v.audio.value}: {len(cands)} candidate server(s)")
        for c in cands:
            print(f"      - kind={c['kind']} referer={c['referer']} url={c['video_url'][:90]}")

    print("### 4. probe m3u8 + one segment per candidate (old vs new headers)")
    for v in variants:
        info = json.loads(v.source_ref)
        for c in info.get("candidates", []):
            url, referer = c["video_url"], c["referer"]
            print(f"  candidate {c['kind']} @ {referer}")
            try:
                async with httpx.AsyncClient(timeout=25, follow_redirects=True) as cli:
                    pl = await cli.get(url, headers={"User-Agent": USER_AGENT,
                                                     "Accept": "*/*",
                                                     "Referer": referer,
                                                     "Origin": referer.rstrip("/")})
                print(f"    m3u8 -> {_hdr_brief(pl)}")
                if pl.status_code != 200 or "#EXT" not in pl.text[:200]:
                    print(f"    m3u8 body[:120]={pl.text[:120]!r}")
                    continue
                # find a media playlist if this is a master
                lines = [ln.strip() for ln in pl.text.splitlines()
                         if ln.strip() and not ln.startswith("#")]
                seg = None
                media_txt, media_url = pl.text, url
                if "#EXT-X-STREAM-INF" in pl.text and lines:
                    media_url = urljoin(url, lines[0])
                    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as cli:
                        mp = await cli.get(media_url, headers={"User-Agent": USER_AGENT,
                                                               "Accept": "*/*", "Referer": referer})
                    media_txt = mp.text
                seg_lines = [ln.strip() for ln in media_txt.splitlines()
                             if ln.strip() and not ln.startswith("#")]
                if seg_lines:
                    seg = urljoin(media_url, seg_lines[0])
                if seg:
                    print(f"    first segment: {seg[:100]}")
                    await _probe_segment(cli, seg, referer)
            except Exception as exc:  # noqa: BLE001
                print(f"    candidate probe ERROR {type(exc).__name__}: {exc}")
    await src.close()


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Takopi's Original Sin"
    asyncio.run(main(q))
