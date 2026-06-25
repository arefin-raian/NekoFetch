import httpx
import asyncio
from bs4 import BeautifulSoup

async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(
            "https://anikoto.tv/search",
            params={"keyword": "Naruto", "sort": "views", "page": 1},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
            },
        )
        print(f"Status: {r.status_code}")
        print(f"URL: {r.url}")

        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("div.flw-item")
        print(f"Items found: {len(items)}")

        if items:
            for i in items[:5]:
                a = i.select_one("a")
                img = i.select_one("img")
                if a:
                    href = a.get("href", "")
                    title = a.get("title") or (img.get("alt", "") if img else "")
                    poster = img.get("data-src") or img.get("src") if img else None
                    print(f"  href: {href}, title: {title}")
        else:
            # Check for other selectors
            for sel in [".film-item", ".item", "article", ".card", "a[href*='/watch/']"]:
                alt = soup.select(sel)
                print(f"  selector '{sel}': {len(alt)}")
            print("--- Body snippet ---")
            print(r.text[:3000])

asyncio.run(test())
