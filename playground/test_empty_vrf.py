import httpx
import asyncio

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
            "referer": f"{BASE}/",
        })

        # Try with empty VRF
        r = await c.post(
            f"{BASE}/ajax/episode/list/1498",
            data={"style": "default", "vrf": ""},
        )
        print(f"POST empty vrf: {r.status_code}")
        print(f"  body: {r.text[:500]}")

        # Try with POST and different content types
        r2 = await c.post(
            f"{BASE}/ajax/episode/list/1498",
            data="style=default&vrf=",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        print(f"\nPOST form-encoded empty vrf: {r2.status_code}")
        print(f"  body: {r2.text[:500]}")

        # Try GET with query params
        r3 = await c.get(
            f"{BASE}/ajax/episode/list/1498",
            params={"style": "default", "vrf": ""},
        )
        print(f"\nGET with query params: {r3.status_code}")
        print(f"  body: {r3.text[:500]}")

        # Try GET with just ?vrf= like the original code
        r4 = await c.get(f"{BASE}/ajax/episode/list/1498?vrf=")
        print(f"\nGET with ?vrf= : {r4.status_code}")
        print(f"  body: {r4.text[:500]}")

        # Try the anime/getinfo/ endpoint which was used in the page
        # Maybe it returns episode data
        r5 = await c.get(f"{BASE}/anime/getinfo/1498")
        print(f"\nGET anime/getinfo/1498: {r5.status_code}")
        print(f"  body: {r5.text[:1000]}")


asyncio.run(test())
