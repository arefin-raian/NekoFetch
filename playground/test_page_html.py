import httpx
import asyncio, re
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        r = await c.get(f"{BASE}/watch/naruto-shippuden-c8gov")
        soup = BeautifulSoup(r.text, "html.parser")

        # Find the episodes section
        for cls in ["episodes", "episode-list", "ep_list", "listing", "episodes-wrap"]:
            el = soup.select_one(f".{cls}")
            if el:
                print(f"Found .{cls}: {str(el)[:500]}")
        
        # Look for episode container by ID
        for id_val in ["episodes", "episode-list", "ep_list"]:
            el = soup.select_one(f"#{id_val}")
            if el:
                print(f"Found #{id_val}: {str(el)[:500]}")

        # Look for any div with episodes in class
        for div in soup.find_all("div", class_=lambda c: c and "episode" in c.lower()):
            print(f"Episode div: class={div.get('class')}, content={str(div)[:300]}")

        # Check if episode data is loaded via JS - look for scripts with episode data
        scripts = soup.find_all("script")
        for s in scripts:
            txt = s.string or ""
            if "episode" in txt.lower() and "list" in txt.lower():
                print(f"\nScript with episode list: {txt[:500]}")

        # Print the whole area after watch-main
        watch_main = soup.select_one("#watch-main")
        if watch_main:
            print(f"\nWatch main siblings after:")
            for sibling in watch_main.find_next_siblings():
                print(f"  {sibling.name}.{'.'.join(sibling.get('class', []))}: {str(sibling)[:200]}")


asyncio.run(test())
