import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.providers.metadata.series import SeriesResolver
async def main():
    cli=AnilistClient(); res=SeriesResolver(cli)
    for q in ["One Piece","Bleach","Code Geass","Mob Psycho 100","Steins;Gate","Re:Zero","Sword Art Online","Jujutsu Kaisen","Tokyo Ghoul","Fate/Zero"]:
        r=await res.resolve(q)
        print(f"{q:22} -> {[e.title for e in r.entries]}")
    await cli.close()
asyncio.run(main())
