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
        
        # Find all external scripts
        soup = BeautifulSoup(r.text, "html.parser")
        scripts = soup.find_all("script", src=True)
        js_files = [s["src"] for s in scripts if s.get("src") and "anikoto" in s["src"]]
        print("JS files loaded:")
        for js in js_files:
            print(f"  {js}")

        # Also check inline scripts for episode loading
        for s in soup.find_all("script"):
            txt = s.string or ""
            if "episode" in txt.lower() or ".episodes" in txt:
                # Extract the key code
                for line in txt.split(";"):
                    line = line.strip()
                    if any(x in line.lower() for x in ["episode", ".episodes", "server", "getinfo"]):
                        if len(line) < 300:
                            print(f"  Code: {line}")

        # Check watch-second for episode list placeholder
        aside = soup.select_one("aside.main")
        if aside:
            html = str(aside)
            # Find where episodes would be
            idx = html.find("episode")
            if idx >= 0:
                print(f"\n'episode' found in aside at pos {idx}:")
                print(html[max(0,idx-200):idx+300])


asyncio.run(test())
