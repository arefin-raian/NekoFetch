import httpx
import asyncio, re, json

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        # Direct hit on anime/getinfo
        r = await c.get(f"{BASE}/anime/getinfo/1498")
        print(f"getinfo status: {r.status_code}")
        print(f"getinfo body: {r.text[:1000]}")

        # Check app_vars
        r2 = await c.get(f"{BASE}/watch/naruto-shippuden-c8gov")
        m = re.search(r"app_vars\s*=\s*({[^;]+})", r2.text)
        if m:
            print(f"\napp_vars: {m.group(1)[:500]}")

        # Look for any other endpoints
        for pat in [r'url\s*[:=]\s*["\']([^"\']+)["\']', r'ajaxURL\s*[:=]\s*["\']([^"\']+)["\']',
                     r'episode_list_url\s*[:=]\s*["\']([^"\']+)["\']',
                     r'base_url\s*[:=]\s*["\']([^"\']+)["\']']:
            matches = re.findall(pat, r2.text)
            for m in matches:
                if "episode" in m.lower() or "ajax" in m.lower() or "vrf" in m.lower():
                    print(f"\nFound endpoint: {m}")


asyncio.run(test())
