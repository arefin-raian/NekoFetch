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

        # Check if the episode list endpoint is actually at a different URL
        # Maybe the anime ID needs to come from a different source
        
        # Let me look at the full page to find the actual episode loading code
        r = await c.get(f"{BASE}/watch/naruto-shippuden-c8gov")
        
        # Look for the script that loads episodes
        # Search for ".episodes" or "episode/list" in all scripts
        soup = BeautifulSoup(r.text, "html.parser")
        for s in soup.find_all("script"):
            txt = s.string or ""
            # Look for episode loading logic
            if "episode" in txt.lower() and ("load" in txt.lower() or "ajax" in txt.lower() or "fetch" in txt.lower() or "get" in txt.lower()):
                print(f"Found relevant script:")
                # Extract just the relevant parts
                lines = txt.split("\n")
                for i, line in enumerate(lines):
                    if any(x in line.lower() for x in ["episode", "ajax", "fetch", "getinfo", "load"]):
                        print(f"  L{i}: {line[:200]}")
                print("---")

        # Also try a different approach - maybe episodes are loaded from a different URL
        # based on what I saw: document.querySelector(".episodes a.active")
        # The episodes class container must exist - let me find it
        
        # Look at the full HTML for .episodes
        print("\n--- Searching for .episodes container ---")
        ep_container = soup.select_one(".episodes")
        if ep_container:
            print(f"Found .episodes: {str(ep_container)[:500]}")
        else:
            print("No .episodes container in HTML")

        # Check the aside main content
        aside = soup.select_one("aside.main")
        if aside:
            print(f"\nAside HTML snippet: {str(aside)[:1000]}")


asyncio.run(test())
