import httpx
import asyncio
from bs4 import BeautifulSoup

DOMAINS = [
    "https://anikoto.net",
    "https://anikoto.cz",
    "https://anikoto.me",
    "https://anikoto.se",
]


async def test_domain(domain):
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(
                f"{domain}/search",
                params={"keyword": "Naruto", "sort": "views", "page": 1},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "x-requested-with": "XMLHttpRequest",
                },
            )
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("div.flw-item")
            print(f"{domain}: status={r.status_code}, items={len(items)}")
            if items:
                a = items[0].select_one("a")
                print(f"  First: {a.get('href')} - {a.get('title')}")
            else:
                print(f"  Body[:300]: {r.text[:300]}")
    except Exception as e:
        print(f"{domain}: ERROR - {e}")


async def main():
    await asyncio.gather(*[test_domain(d) for d in DOMAINS])


asyncio.run(main())
