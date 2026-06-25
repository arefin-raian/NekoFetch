"""Validate the rewritten AnikotoSource end-to-end through the real class."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nekofetch.sources.anikoto import AnikotoSource, _ts_is_clean  # noqa: E402
from nekofetch.domain.enums import AudioType  # noqa: E402

OUT = Path(__file__).parent / "downloads" / "validate"


async def main():
    src = AnikotoSource(preferred_quality="720")
    try:
        eps = await src.get_episodes("naruto-shippuden-c8gov")
        print(f"episodes: {len(eps)}")
        if not eps:
            print("FAIL: no episodes")
            return
        # cache ep numbers for mapper lookups
        await src._resolve_episode_refs(eps)
        ep1 = eps[0]
        print(f"ep1 ref: {ep1.source_ref}")

        variants = await src.get_variants(ep1.source_ref)
        print(f"variants: {len(variants)}")
        for v in variants:
            import json
            c = json.loads(v.source_ref)["candidates"]
            print(f"  {v.audio.name}: {len(c)} servers -> kinds={[x['kind'] for x in c]}")

        sub = next((v for v in variants if v.audio == AudioType.SUBBED), None)
        if not sub:
            print("FAIL: no sub variant")
            return
        print("\nDownloading SUB (720p) via real class...")
        res = await src.download(sub, OUT / "naruto_ep1_sub")
        print(f"  result: {res}")
        f = OUT / "naruto_ep1_sub"
        actual = next(OUT.glob("naruto_ep1_sub.*"))
        data = actual.read_bytes()
        print(f"  file: {actual.name} ({len(data)/1048576:.1f} MB)")
        if actual.suffix == ".ts":
            print(f"  TS clean: {_ts_is_clean(data)}")
    finally:
        await src.close()


asyncio.run(main())
