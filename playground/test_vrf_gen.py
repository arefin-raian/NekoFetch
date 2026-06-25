import httpx
import asyncio, re

BASE = "https://anikototv.to"


async def test():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        c.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        })

        # Get mapper.js
        mapper_r = await c.get(f"{BASE}/anikoto/js/mapper.js?v=1780003801_1bcedbb6")
        mjs = mapper_r.text
        print("=== mapper.js full ===")
        print(mjs)
        print("\n\n")

        # Get main.js - find VRF generation
        js_r = await c.get(f"{BASE}/anikoto/js/main.js?v=1.111")
        js = js_r.text

        # Find the VRF function - it's used as o(this.Ee) where o is a function
        # Search for function definitions around the episode loading code
        idx = js.find("ajax/episode/list")
        if idx >= 0:
            print(f"Found at {idx}")
            print(js[max(0,idx-2000):idx+2000])


asyncio.run(test())
