import asyncio
from nekofetch.sources.kickassanime import KickAssAnimeSource
from nekofetch.sources.anikoto import AnikotoSource
async def main():
    # AoT: english 'Attack on Titan', romaji 'Shingeki no Kyojin'
    for cls,name in [(KickAssAnimeSource,"kaa"),(AnikotoSource,"anikoto")]:
        s=cls()
        try:
            cov=await asyncio.wait_for(s.coverage("Attack on Titan","Shingeki no Kyojin"),timeout=90)
            print(f"  [{name}] avail={cov.available} matched={cov.matched_title!r} total={cov.total_episodes} sub={cov.sub_episodes} dub={cov.dub_episodes}")
        except Exception as e: print(f"  [{name}] ERR {type(e).__name__}: {e}")
        finally: await s.close()
asyncio.run(main())
