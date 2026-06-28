import asyncio
from nekofetch.core.config import get_env
from nekofetch.sources.telegram.anilist import AnilistClient
from nekofetch.providers.metadata.tmdb import TmdbClient

async def main():
    env = get_env()
    ani = AnilistClient()
    tmdb = TmdbClient(token=env.tmdb_read_access_token, api_key=env.tmdb_api_key)
    for q in ["Hellsing", "Attack on Titan", "Fullmetal Alchemist"]:
        m = await ani.search(q)
        match = await tmdb.search(m.english or q)
        print("="*60)
        print(f"QUERY {q!r}  AniList english={m.english!r}")
        if match:
            # is the chosen backdrop english-tagged?
            imgs = await tmdb._get(f"/{match.media_type}/{match.id}/images", include_image_language="en,null")
            chosen = match.backdrop_url.split("/")[-1] if match.backdrop_url else None
            en_paths = {b['file_path'].lstrip('/') for b in imgs.get('backdrops',[]) if b.get('iso_639_1')=='en'}
            tag = "ENGLISH ✅" if chosen in en_paths else "neutral/other"
            print(f"  TMDB {match.media_type}/{match.id} backdrop={chosen} [{tag}]")
            print(f"  synopsis source = TMDB: {match.overview[:70]!r}")
        else:
            print("  NO TMDB MATCH (synopsis falls back to AniList)")
    await ani.close(); await tmdb.close()

asyncio.run(main())
