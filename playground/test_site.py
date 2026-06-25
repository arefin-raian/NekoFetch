import httpx
import asyncio, re
from bs4 import BeautifulSoup

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        # --- Search via filter ---
        r = await c.get(f"{BASE}/filter", params={"keyword": "Naruto", "sort": "views"})
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".item a[href*='/watch/']")
        print(f"Search results: {len(items)}")
        slugs = []
        for a in items[:5]:
            href = a.get("href", "")
            # /watch/some-slug or /watch/some-slug/ep-123
            match = re.match(rf"{re.escape(BASE)}/watch/([^/]+)", href)
            if match:
                slug = match.group(1)
                if slug not in slugs:
                    slugs.append(slug)
                    print(f"  slug: {slug}")
        
        if not slugs:
            print("No slugs found. Dumping first item HTML:")
            first_item = soup.select_one(".item")
            if first_item:
                print(str(first_item)[:500])
            return

        slug = slugs[0]
        print(f"\nUsing slug: {slug}")

        # --- Get details / episode page ---
        r2 = await c.get(f"{BASE}/watch/{slug}")
        print(f"Watch page status: {r2.status_code}")

        # Find anime ID
        id_match = re.search(r'/anime/getinfo/(\d+)', r2.text)
        if not id_match:
            id_match = re.search(r'data-id="(\d+)"', r2.text)
        if id_match:
            vid = id_match.group(1)
            print(f"Anime ID: {vid}")

            # Get episodes
            r3 = await c.get(f"{BASE}/ajax/episode/list/{vid}?vrf=")
            print(f"Episodes AJAX status: {r3.status_code}")
            data = r3.json()
            html_code = data.get("result", "")
            ep_soup = BeautifulSoup(html_code, "html.parser")

            # Try different selectors for episodes
            ep_links = ep_soup.select("a[data-ids]")
            print(f"Episode links with data-ids: {len(ep_links)}")
            ep_lis = ep_soup.find_all("li")
            print(f"Episode li items: {len(ep_lis)}")

            if ep_links:
                first = ep_links[0]
                print(f"\nFirst episode:")
                print(f"  title: {first.get('title')}")
                print(f"  href: {first.get('href')}")
                print(f"  data-ids: {first.get('data-ids')}")
                print(f"  data-mal: {first.get('data-mal')}")
                print(f"  data-timestamp: {first.get('data-timestamp')}")
                
                data_ids = first.get("data-ids", "")
                data_mal = first.get("data-mal", "")
                data_ts = first.get("data-timestamp", "")
                
                # --- Try getting variants ---
                # Method 1: Mapper API
                print(f"\n--- Trying mapper API ---")
                r4 = await c.get(
                    f"https://mapper.mewcdn.online/api/mal/{data_mal}/1/{data_ts}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                        "referer": BASE,
                        "origin": BASE,
                    },
                )
                print(f"Mapper status: {r4.status_code}")
                if r4.status_code == 200:
                    kiwi_data = r4.json()
                    print(f"Mapper keys: {list(kiwi_data.keys())[:10]}")
                    for k in kiwi_data:
                        if "Stream" in k:
                            print(f"  Stream key: {k}")
                            for ak in ("sub", "dub"):
                                if ak in kiwi_data[k]:
                                    print(f"    {ak}: present")
                                    print(f"    data: {str(kiwi_data[k][ak])[:300]}")
                else:
                    print(f"Mapper response: {r4.text[:500]}")

                # Method 2: Server list
                print(f"\n--- Trying server list ---")
                r5 = await c.get(f"{BASE}/ajax/server/list", params={"servers": data_ids})
                print(f"Server list status: {r5.status_code}")
                if r5.status_code == 200:
                    srv_data = r5.json()
                    srv_soup = BeautifulSoup(srv_data.get("result", ""), "html.parser")
                    types = srv_soup.find_all("div", class_="type")
                    print(f"Server types: {len(types)}")
                    for t in types:
                        print(f"  type: {t.get('data-type')}")
                        lis = t.find_all("li")
                        print(f"    items: {len(lis)}")
                        for li in lis[:2]:
                            print(f"    data-link-id: {li.get('data-link-id')}")
        else:
            print("No anime ID found")
            # Print relevant parts
            for pat in [r'/anime/getinfo/', r'data-id=', r'anime/getinfo']:
                matches = re.findall(pat, r2.text)
                print(f"  pattern '{pat}': {len(matches)} matches")


asyncio.run(test())
