import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.providers.metadata.series import SeriesResolver

async def main():
    cli = AnilistClient()
    res = SeriesResolver(cli)
    for q in ["Hellsing", "Naruto", "Attack on Titan", "Fullmetal Alchemist", "Demon Slayer"]:
        m = await cli.search(q)
        print("="*70)
        print(f"QUERY: {q!r}")
        if not m:
            print("  NO MATCH"); continue
        print(f"  base titles (order) = {m.titles}")
        print(f"  format={m.format} year={m.year} eps={m.episodes}")
        print(f"  franchise: seasons={m.franchise_seasons} movies={m.franchise_movies} ovas={m.franchise_ovas} onas={m.franchise_onas} specials={m.franchise_specials} totaleps={m.franchise_episodes}")
        print("  relations:")
        for r in m.relations:
            print(f"    [{r.relation:12}] fmt={str(r.format):8} eps={r.episodes} titles={r.titles}")
        resolution = await res.resolve(q)
        print(f"  RESOLVER -> {[e.title for e in resolution.entries]}")
    await cli.close()

asyncio.run(main())
