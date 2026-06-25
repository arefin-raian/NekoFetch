import httpx
import asyncio, re, json
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
            "referer": f"{BASE}/",
        })

        # Get episode list
        r = await c.post(
            f"{BASE}/ajax/episode/list/1498",
            data={"style": "default", "vrf": ""},
        )
        data = r.json()
        html_code = data.get("result", "")
        soup = BeautifulSoup(html_code, "html.parser")
        
        # Find episode links
        ep_links = soup.select("a[data-ids]")
        print(f"Episode links found: {len(ep_links)}")

        if ep_links:
            first = ep_links[0]
            print(f"\nFirst episode:")
            print(f"  title: {first.get('title')}")
            print(f"  href: {first.get('href')}")
            print(f"  data-ids: {first.get('data-ids')}")
            print(f"  data-mal: {first.get('data-mal')}")
            print(f"  data-timestamp: {first.get('data-timestamp')}")
            print(f"  data-num: {first.get('data-num')}")
            print(f"  data-slug: {first.get('data-slug')}")

            data_ids = first.get("data-ids", "")
            data_mal = first.get("data-mal", "")
            data_ts = first.get("data-timestamp", "")
            data_slug = first.get("data-slug", "1")

            # Try mapper API
            print(f"\n--- Trying mapper API ---")
            mapper_url = f"https://mapper.nekostream.site/api/mal/{data_mal}/{data_slug}/{data_ts}"
            print(f"  URL: {mapper_url}")
            r2 = await c.get(mapper_url)
            print(f"  Status: {r2.status_code}")
            if r2.status_code == 200:
                mapper_data = r2.json()
                print(f"  Keys: {list(mapper_data.keys())}")
                for k in mapper_data:
                    if k != "status":
                        print(f"  Server '{k}':")
                        server = mapper_data[k]
                        for ak in ("sub", "dub"):
                            if ak in server:
                                url_info = server[ak]
                                if isinstance(url_info, dict):
                                    print(f"    {ak}: url={url_info.get('url','')[:100]}")
                                else:
                                    print(f"    {ak}: {str(url_info)[:100]}")
            else:
                print(f"  Response: {r2.text[:300]}")

            # Try server list
            print(f"\n--- Trying server list ---")
            r3 = await c.get(f"{BASE}/ajax/server/list", params={"servers": data_ids})
            print(f"  Status: {r3.status_code}")
            if r3.status_code == 200:
                srv_data = r3.json()
                srv_soup = BeautifulSoup(srv_data.get("result", ""), "html.parser")
                types = srv_soup.find_all("div", class_="type")
                print(f"  Server types: {len(types)}")
                for t in types:
                    print(f"    type={t.get('data-type')}")
                    for li in t.find_all("li"):
                        print(f"      data-link-id={li.get('data-link-id')}, data-ep-id={li.get('data-ep-id')}")
        else:
            print("Full response HTML:")
            print(html_code[:2000])


asyncio.run(test())
