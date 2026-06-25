from __future__ import annotations

import asyncio
from pathlib import Path

from nekofetch.sources.anikoto import AnikotoSource
from nekofetch.domain.enums import AudioType


async def main():
    downloads_dir = Path(__file__).parent / "downloads"
    downloads_dir.mkdir(exist_ok=True)

    sub_source = AnikotoSource(preferred_quality="720")
    dub_source = AnikotoSource(preferred_quality="1080")

    try:
        print("[*] Searching for Naruto...")
        results = await sub_source.search("Naruto")
        if not results:
            print("[-] No results found")
            return

        slug = results[0].source_ref
        print(f"[+] Found: {results[0].title} (slug: {slug})")

        print("[*] Getting episodes...")
        episodes = await sub_source.get_episodes(slug)
        if not episodes:
            print("[-] No episodes found")
            return

        print(f"[+] Found {len(episodes)} episodes")
        ep1 = episodes[0]
        print(f"    Episode 1 ref: {ep1.source_ref}")

        print("[*] Getting variants for sub (720p)...")
        sub_variants = await sub_source.get_variants(ep1.source_ref)
        sub_variant = next(
            (v for v in sub_variants if v.audio == AudioType.SUBBED),
            None,
        )

        print("[*] Getting variants for dub (1080p)...")
        dub_variants = await dub_source.get_variants(ep1.source_ref)
        dub_variant = next(
            (v for v in dub_variants if v.audio == AudioType.DUBBED),
            None,
        )

        if sub_variant:
            dest = downloads_dir / "Naruto_Ep01_SUBBED_720p"
            print(f"[+] Downloading sub (720p)...")
            result = await sub_source.download(sub_variant, dest)
            print(f"    Done: {result['bytes'] / 1024 / 1024:.1f} MB")
        else:
            print("[-] No subbed variant found")

        if dub_variant:
            dest = downloads_dir / "Naruto_Ep01_DUBBED_1080p"
            print(f"[+] Downloading dub (1080p)...")
            result = await dub_source.download(dub_variant, dest)
            print(f"    Done: {result['bytes'] / 1024 / 1024:.1f} MB")
        else:
            print("[-] No dubbed variant found")

    finally:
        await sub_source.close()
        await dub_source.close()

    print("[*] All done")


if __name__ == "__main__":
    asyncio.run(main())
