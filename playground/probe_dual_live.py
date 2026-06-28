import asyncio
from nekofetch.sources.anikoto import AnikotoSource

async def main():
    src = AnikotoSource()
    try:
        stubs = await asyncio.wait_for(src.search("Naruto"), timeout=60)
        print("matched:", stubs[0].title if stubs else None)
        eps = await asyncio.wait_for(src.get_episodes(stubs[0].source_ref), timeout=60)
        print("episodes:", len(eps))
        for ep in eps[:1]:
            plan = await asyncio.wait_for(src.dual_audio_plan(ep.source_ref), timeout=120)
            print(f"  ep{ep.number}: feasible={plan.get('feasible')} mergeable={plan.get('mergeable')} "
                  f"sub_dur={plan.get('sub_dur')} dub_dur={plan.get('dub_dur')} reason={plan.get('reason')}")
    except Exception as e:
        print("ERROR:", type(e).__name__, e)
    finally:
        await src.close()

asyncio.run(main())
