import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.bots.admin.handlers.requests import _media_to_franchise_dict
from nekofetch.ui.screens import confirm_franchise

async def main():
    cli = AnilistClient()
    for q in ["Hellsing", "Naruto"]:
        m = await cli.search(q)
        fd = _media_to_franchise_dict(m)
        scr = confirm_franchise(fd)
        print("="*72)
        print(f"QUERY {q!r}  image={scr.image}")
        print(scr.caption)
    await cli.close()

asyncio.run(main())
