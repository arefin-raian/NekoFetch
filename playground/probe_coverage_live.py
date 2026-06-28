import asyncio
from nekofetch.sources.kickassanime import KickAssAnimeSource
from nekofetch.sources.anikoto import AnikotoSource

async def main():
    for title in ["Naruto"]:
        print("="*60, "\nTITLE:", title)
        for cls, name in [(KickAssAnimeSource, "kickassanime"), (AnikotoSource, "anikoto")]:
            src = cls()
            try:
                cov = await asyncio.wait_for(src.coverage(title), timeout=90)
                print(f"  [{name}] available={cov.available} matched={cov.matched_title!r}")
                print(f"           total={cov.total_episodes} sub={cov.sub_episodes} dub={cov.dub_episodes} approx={cov.approximate} note={cov.note}")
            except Exception as e:
                print(f"  [{name}] ERROR: {type(e).__name__}: {e}")
            finally:
                await src.close()

asyncio.run(main())
