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
        print(f"main.js size: {len(js)} bytes")

        # Search for episode-related AJAX calls
        for pat in [r'episode/list/\d+', r'ajax/episode', r'getinfo/\d+', r'w-episodes', 
                     r'\.load\(', r'fetch\(', r'\.get\(', r'\.post\(',
                     r'loadEpisode', r'load_episode', r'episodes']:
            matches = list(re.finditer(pat, js))
            if matches:
                for m in matches[:3]:
                    start = max(0, m.start() - 100)
                    end = min(len(js), m.end() + 300)
                    snippet = js[start:end]
                    print(f"\nPattern '{pat}' at byte {m.start()}:")
                    print(snippet[:400])
                    print("---")

        # Also search for mapper.js 
        mapper_r = await c.get(f"{BASE}/anikoto/js/mapper.js?v=1780003801_1bcedbb6")
        mjs = mapper_r.text
        print(f"\n\nmapper.js size: {len(mjs)} bytes")
        for pat in [r'episode/list', r'getinfo', r'ajax/', r'/api/']:
            for m in re.finditer(pat, mjs):
                start = max(0, m.start() - 50)
                end = min(len(mjs), m.end() + 200)
                print(f"Pattern '{pat}': {mjs[start:end][:300]}")
                break


asyncio.run(test())
