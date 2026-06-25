import httpx
import asyncio, re, json
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        slug = "naruto-shippuden-c8gov"
        r = await c.get(f"{BASE}/watch/{slug}")
        soup = BeautifulSoup(r.text, "html.parser")

        # Look for episode data embedded in the page
        # Check for script tags with JSON
        scripts = soup.find_all("script")
        for s in scripts:
            txt = s.string or ""
            if any(x in txt.lower() for x in ["episode", "anime_id", "data-id", "getinfo", "vrf"]):
                print(f"Relevant script: {txt[:500]}")
                print("---")

        # Look for any data attributes on the page
        for el in soup.find_all(attrs={"data-id": True}):
            print(f"Element with data-id: tag={el.name}, data-id={el['data-id']}")
            print(f"  Other attrs: {dict(el.attrs)}")

        # Try to get CSRF token
        csrf = soup.select_one('meta[name="csrf-token"]')
        if csrf:
            print(f"CSRF token: {csrf.get('content')}")

        # Check if there's a different episode endpoint
        for link in soup.find_all("link"):
            if "episode" in str(link).lower():
                print(f"Link: {link}")

        # Look at the whole body for anime/episode related patterns
        body = r.text
        patterns = [
            r"episode/list/\d+",
            r"getinfo/\d+",
            r"vrf\s*[:=]\s*['\"][^'\"]+['\"]",
            r"ajax/episode",
            r"data-vrf",
        ]
        for pat in patterns:
            matches = re.findall(pat, body)
            if matches:
                print(f"Pattern '{pat}': {matches[:5]}")


asyncio.run(test())
