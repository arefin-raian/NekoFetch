import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient

async def main():
    cli = AnilistClient()
    for q in ["Attack on Titan", "Hellsing", "Monogatari", "Fate/Zero", "A Certain Magical Index"]:
        m = await cli.search(q)
        if not m:
            print(f"{q:26} -> NO MATCH"); continue
        ft = await cli.franchise_totals(m.id)
        print(f"{q:26} base={m.english!r}")
        print(f"{'':26}  seasons={ft.seasons} ({ft.episodes} eps) movies={ft.movies} "
              f"ovas={ft.ovas} onas={ft.onas} specials={ft.specials} | nodes={ft.nodes}")
    await cli.close()

asyncio.run(main())
