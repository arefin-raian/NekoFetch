import asyncio
from nekofetch.core.config import get_env
from nekofetch.providers.metadata.tmdb import TmdbClient

async def main():
    env = get_env()
    cli = TmdbClient(token=env.tmdb_read_access_token, api_key=env.tmdb_api_key)
    # Raw images for Hellsing TV (16830)
    imgs = await cli._get("/tv/16830/images", include_image_language="en,null")
    bd = imgs.get("backdrops", [])
    en = [b for b in bd if b.get("iso_639_1")=="en"]
    neutral = [b for b in bd if b.get("iso_639_1") in (None,"")]
    print(f"tv/16830 backdrops total={len(bd)} english={len(en)} neutral={len(neutral)}")
    for b in en[:5]:
        print(f"  EN vote={b.get('vote_average')} {b.get('file_path')}")
    chosen = await cli._english_backdrop(16830, "tv")
    print("OUR CHOICE:", chosen)
    # Full search path
    for q in ["Hellsing", "Attack on Titan", "Naruto"]:
        r = await cli.search(q)
        print(f"\nSEARCH {q!r} -> id={r.id} type={r.media_type} title={r.title!r}")
        print(f"  backdrop_url={r.backdrop_url}")
        print(f"  overview[:90]={r.overview[:90]!r}")
    await cli.close()

asyncio.run(main())
