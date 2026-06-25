import httpx
import asyncio, re, json
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        # Check what the first search result actually is
        r = await c.get(f"{BASE}/filter", params={"keyword": "Naruto", "sort": "views"})
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".item")
        print(f"Total items: {len(items)}")
        for item in items[:10]:
            a = item.select_one("a[href*='/watch/']")
            if a:
                href = a.get("href", "")
                img = item.select_one("img")
                alt = img.get("alt", "") if img else ""
                print(f"  {href} -> {alt}")

        # Try searching for "Naruto Shippuden" specifically
        print("\n--- Searching 'Naruto Shippuden' ---")
        r2 = await c.get(f"{BASE}/filter", params={"keyword": "Naruto Shippuden", "sort": "views"})
        soup2 = BeautifulSoup(r2.text, "html.parser")
        items2 = soup2.select(".item a[href*='/watch/']")
        print(f"Results: {len(items2)}")
        for a in items2[:5]:
            print(f"  {a.get('href')}")

        naruto_slug = None
        for a in items2:
            href = a.get("href", "")
            m = re.search(r'/watch/([^/]+)', href)
            if m:
                naruto_slug = m.group(1)
                print(f"\nUsing slug: {naruto_slug}")
                break

        if not naruto_slug:
            print("Could not find Naruto Shippuden")
            return

        # Get the watch page
        r3 = await c.get(f"{BASE}/watch/{naruto_slug}")
        print(f"Watch page status: {r3.status_code}")

        id_match = re.search(r'/anime/getinfo/(\d+)', r3.text)
        if not id_match:
            id_match = re.search(r'data-id="(\d+)"', r3.text)
        
        if id_match:
            vid = id_match.group(1)
            print(f"Anime ID: {vid}")

            # Get episodes raw
            r4 = await c.get(f"{BASE}/ajax/episode/list/{vid}?vrf=")
            data = r4.json()
            html_code = data.get("result", "")
            print(f"Episodes HTML length: {len(html_code)}")
            print(f"Episodes HTML first 500: {html_code[:500]}")

            if html_code:
                ep_soup = BeautifulSoup(html_code, "html.parser")
                # Try to find any links
                all_links = ep_soup.find_all("a")
                print(f"All links in ep HTML: {len(all_links)}")
                for link in all_links[:5]:
                    print(f"  href={link.get('href')}, title={link.get('title')}, data-ids={link.get('data-ids')}")
                
                # Try li elements
                all_lis = ep_soup.find_all("li")
                print(f"All li in ep HTML: {len(all_lis)}")
                for li in all_lis[:3]:
                    print(f"  li: {str(li)[:200]}")
        else:
            print("No ID found. Searching for ID patterns...")
            for m in re.finditer(r'(data-id|data-ids|getinfo)[^"\']*["\']([^"\']+)["\']', r3.text):
                print(f"  {m.group(1)} = {m.group(2)}")


asyncio.run(test())
