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
        
        # Find #w-episodes
        soup = BeautifulSoup(r.text, "html.parser")
        wep = soup.select_one("#w-episodes")
        if wep:
            print(f"Found #w-episodes: {str(wep)[:500]}")
        else:
            print("#w-episodes NOT found in HTML")
            # Search for w-episodes anywhere in the page
            if "w-episodes" in r.text:
                idx = r.text.index("w-episodes")
                print(f"'w-episodes' found at byte {idx}")
                print(r.text[max(0,idx-200):idx+500])
            else:
                print("'w-episodes' not in HTML at all")
        
        # Let me check the main.js to see how episodes are loaded
        js_r = await c.get(f"{BASE}/anikoto/js/main.js?v=1.111")
        js = js_r.text
        
        # Find episode loading function
        idx = js.find("episode")
        if idx >= 0:
            print(f"\n'main.js' episode logic at byte {idx}:")
            print(js[max(0,idx-100):idx+500])


asyncio.run(test())
