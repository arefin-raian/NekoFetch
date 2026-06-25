import httpx
import asyncio
from bs4 import BeautifulSoup

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
        # Try the filter search endpoint
        r = await c.get(f"{BASE}/filter", params={"keyword": "Naruto", "sort": "views", "page": 1})
        print(f"Filter status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("div.flw-item")
        print(f"flw-item items: {len(items)}")

        # Try various selectors
        for sel in [".film-item", "article", ".item", ".card", "a[href*='/watch/']", ".flw-item", ".ss-list", ".splide__slide"]:
            found = soup.select(sel)
            print(f"  '{sel}': {len(found)}")

        # Try home page
        r2 = await c.get(f"{BASE}/home")
        print(f"\nHome status: {r2.status_code}")
        soup2 = BeautifulSoup(r2.text, "html.parser")
        items2 = soup2.select("div.flw-item")
        print(f"Home flw-item items: {len(items2)}")

        if not items2:
            # Print section with anime listings
            for cls in ["film-list", "anime-list", "listing", "items", "block_area-content"]:
                el = soup2.select(f".{cls}")
                if el:
                    print(f"  Found .{cls}: {len(el)}")
                    print(f"  Sample: {str(el[0])[:500]}")
            
            # Maybe it's different tags
            print("\nLooking for watch links...")
            watch_links = soup2.select("a[href*='/watch/']")
            print(f"  Watch links: {len(watch_links)}")
            if watch_links:
                for link in watch_links[:5]:
                    print(f"    {link.get('href')} - {link.get('title', 'no title')}")


asyncio.run(test())
