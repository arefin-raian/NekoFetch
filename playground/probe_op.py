import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient
async def main():
    cli=AnilistClient()
    m=await cli.search("One Piece")
    for r in m.relations:
        if "MONSTER" in (r.titles[0].upper() if r.titles else "") or r.relation=="ALTERNATIVE":
            print(f"[{r.relation}] fmt={r.format} eps={r.episodes} -> {r.titles}")
    await cli.close()
asyncio.run(main())
