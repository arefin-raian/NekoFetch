import httpx
import asyncio
from bs4 import BeautifulSoup

# Replicate exactly what AnikotoSource does
BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
        },
        follow_redirects=True,
    ) as c:
        # Test search
        r = await c.get(f"{BASE}/search", params={"keyword": "Naruto", "sort": "views", "page": 1})
        print(f"Search status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("div.flw-item")
        print(f"Items: {len(items)}")
        if items:
            for i in items[:3]:
                a = i.select_one("a")
                img = i.select_one("img")
                if a:
                    print(f"  href={a.get('href')}, title={a.get('title') or (img.get('alt','') if img else '')}")
            first_slug = items[0].select_one("a").get("href", "").strip("/").split("/")[-1]
            print(f"\nFirst slug: {first_slug}")

            # Test get_details
            r2 = await c.get(f"{BASE}/watch/{first_slug}")
            print(f"\nDetails status: {r2.status_code}")

            # Test getinfo ID extraction
            import re
            search = re.search(rf'{re.escape(BASE)}/anime/getinfo/(\d+)', r2.text)
            if not search:
                search = re.search(r'/anime/getinfo/(\d+)', r2.text)
            if search:
                vid = search.group(1)
                print(f"Video ID: {vid}")

                # Test episode list
                r3 = await c.get(f"{BASE}/ajax/episode/list/{vid}?vrf=")
                print(f"Episodes status: {r3.status_code}")
                data = r3.json()
                html_code = data.get("result", "")
                ep_soup = BeautifulSoup(html_code, "html.parser")
                ep_items = ep_soup.find_all("li", {"data-html": "true"})
                print(f"Episode count: {len(ep_items)}")
                if ep_items:
                    first_ep = ep_items[0].find("a")
                    if first_ep:
                        print(f"First ep title: {first_ep.get('title')}")
                        print(f"  data-ids: {first_ep.get('data-ids')}")
                        print(f"  data-mal: {first_ep.get('data-mal')}")
                        print(f"  data-timestamp: {first_ep.get('data-timestamp')}")
            else:
                print("No video ID found")
                # Print body snippet for debugging
                print(r2.text[:1000])
        else:
            print("No items found. Body snippet:")
            print(r.text[:2000])


asyncio.run(test())
