import httpx
import asyncio, re, json, base64
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


def get_mapper_api() -> str:
    return "https://mapper.nekostream.site/api/mal/"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
            "referer": f"{BASE}/",
        })

        # Step 1: Search Naruto
        slug = "naruto-shippuden-c8gov"
        anime_id = 1498

        # Step 2: Get episode list
        r = await c.post(
            f"{BASE}/ajax/episode/list/{anime_id}",
            data={"style": "default", "vrf": ""},
        )
        data = r.json()
        html_code = data.get("result", "")
        soup = BeautifulSoup(html_code, "html.parser")
        ep_links = soup.select("a[data-ids]")

        # Episode 1
        ep1 = ep_links[0]
        data_mal = ep1.get("data-mal", "")    # 1735
        data_slug = ep1.get("data-slug", "1")  # 1
        data_ts = ep1.get("data-timestamp", "")  # 1729202118
        print(f"Episode 1: mal={data_mal}, slug={data_slug}, ts={data_ts}")

        # Step 3: Get mapper data
        mapper_url = f"{get_mapper_api()}{data_mal}/{data_slug}/{data_ts}"
        r2 = await c.get(mapper_url)
        mapper_data = r2.json()
        print(f"\nMapper data keys: {list(mapper_data.keys())}")

        # Step 4: Get video URLs via ajax/server
        for stream_key in mapper_data:
            if "Stream" not in stream_key:
                continue
            for audio_key in ("sub", "dub"):
                if audio_key not in mapper_data[stream_key]:
                    continue
                
                url_data = mapper_data[stream_key][audio_key]
                server_code = url_data["url"] if isinstance(url_data, dict) else url_data
                if not server_code:
                    continue
                
                r3 = await c.get(
                    f"{BASE}/ajax/server",
                    params={"get": server_code},
                )
                if r3.status_code == 200:
                    result = r3.json().get("result", {})
                    result_url = result.get("url", "")
                    if "#" in result_url:
                        decoded = base64.b64decode(result_url.split("#")[1]).decode("utf-8")
                        print(f"\n  {stream_key}/{audio_key}:")
                        print(f"    Video URL: {decoded[:150]}...")
                        
                        # Also check if we can get skip data
                        skip_data = result.get("skip_data")
                        if skip_data:
                            print(f"    Skip data: {skip_data}")


asyncio.run(test())
