import httpx
import asyncio, re

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        js_r = await c.get(f"{BASE}/anikoto/js/main.js?v=1.111")
        js = js_r.text

        # Find the function "o" definition by looking at the surrounding context
        # The function call is o(this.Ee) where this.Ee is the anime ID
        # Let me search for where o is defined

        # First, let me find all occurrences of "o(" 
        # Actually let me look at the code differently
        # The code uses modules/webpack pattern. Let me find the actual function

        # Let me search for the vrf generation pattern
        # Common patterns: a VRF is often an MD5/CRC or similar of the ID + salt
        # Let me search for "vrf" in the JS

        for m in re.finditer(r'[^a-zA-Z]vrf[^a-zA-Z]', js):
            start = max(0, m.start() - 200)
            end = min(len(js), m.end() + 300)
            snippet = js[start:end]
            print(f"VRF at byte {m.start()}:")
            print(snippet)
            print("---")

        # Also look for the o function specifically
        # The code has: "vrf",o(this.Ee)
        # Let me search near that area
        idx = js.find('"vrf",o(')
        if idx >= 0:
            print(f"\nFound 'vrf\",o(' at byte {idx}")
            # Look backwards to find function definition
            pre = js[max(0,idx-3000):idx+100]
            print(pre)


asyncio.run(test())
