import httpx
import asyncio, re
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        # Naruto Shippuden main series slug
        slug = "naruto-shippuden-c8gov"
        print(f"Using slug: {slug}")

        # Get watch page
        r = await c.get(f"{BASE}/watch/{slug}")
        print(f"Watch page status: {r.status_code}")

        # Find anime ID - look for various patterns
        # Check if there's a data-id on the page
        for m in re.finditer(r'data-id\s*=\s*["\'](\d+)["\']', r.text):
            print(f"  data-id found: {m.group(1)}")
        for m in re.finditer(r'/anime/getinfo/(\d+)', r.text):
            print(f"  getinfo found: {m.group(1)}")

        id_match = re.search(r'/anime/getinfo/(\d+)', r.text) or re.search(r'data-id\s*=\s*["\'](\d+)["\']', r.text)
        if not id_match:
            print("No ID found. Looking at page structure...")
            # Print some of the page
            for script in r.text.split("<script"):
                if "getinfo" in script or "data-id" in script or "episode" in script.lower():
                    print(f"  script snippet: {script[:300]}")
            # Try to find the main container
            soup = BeautifulSoup(r.text, "html.parser")
            for cls in ["anime", "details", "main", "content"]:
                el = soup.select_one(f".{cls}")
                if el:
                    print(f"  Found .{cls}: {str(el)[:300]}")
            return

        vid = id_match.group(1)
        print(f"Anime ID: {vid}")

        # Try episodes endpoint with different approaches
        for url in [
            f"{BASE}/ajax/episode/list/{vid}",
            f"{BASE}/ajax/episode/list/{vid}?vrf=",
        ]:
            r2 = await c.get(url)
            print(f"\nEpisodes URL: {url}")
            print(f"  Status: {r2.status_code}")
            try:
                data = r2.json()
                html_code = data.get("result", "")
                print(f"  Result HTML length: {len(html_code)}")
                if html_code and "bad request" not in html_code.lower():
                    print(f"  First 300: {html_code[:300]}")
                    break
                else:
                    print(f"  Response: {str(data)[:300]}")
            except:
                print(f"  Not JSON: {r2.text[:300]}")


asyncio.run(test())
