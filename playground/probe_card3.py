import asyncio
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.bots.admin.handlers.requests import _media_to_franchise_dict
from nekofetch.ui.screens import confirm_franchise

async def main():
    cli = AnilistClient()
    for q in ["Attack on Titan"]:
        m = await cli.search(q)
        fd = _media_to_franchise_dict(m)
        ft = await cli.franchise_totals(m.id)
        fd.update(franchise_seasons=ft.seasons, franchise_episodes=ft.episodes or None,
                  franchise_movies=ft.movies, franchise_ovas=ft.ovas,
                  franchise_onas=ft.onas, franchise_specials=ft.specials)
        fd["synopsis_url"]="https://www.themoviedb.org/tv/1429"
        scr = confirm_franchise(fd, backdrop_path="https://img/bd.jpg")
        print(scr.caption)
    await cli.close()
asyncio.run(main())
