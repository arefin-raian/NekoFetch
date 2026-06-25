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

        # Search for function o definition pattern
        for pat in [r'[,;{]\s*o\s*=\s*function', r'[,;{]\s*o\s*=\s*\(', r'function\s+o\s*\(', r'var\s+o\s*=', r'let\s+o\s*=', r'const\s+o\s*=']:
            for m in re.finditer(pat, js):
                start = max(0, m.start())
                end = min(len(js), m.end() + 500)
                print(f"Found '{pat}' at byte {m.start()}:")
                print(js[start:end])
                print("---")

        # Also look at the module definition pattern
        # The code might look like: function(t,i,o){ ... } where o is defined inside
        # Search for the wrapper that contains o(this.Ee)
        idx = js.find('"vrf",o(this.Ee)')
        if idx >= 0:
            # Find the function/module that contains this
            # Look backwards for the module definition
            pre = js[max(0,idx-5000):idx]
            # Find "function(" backwards
            last_func = pre.rfind("function(")
            if last_func >= 0:
                print(f"\nModule function at byte {max(0,idx-5000)+last_func}:")
                print(js[max(0,idx-5000)+last_func:idx+100])


asyncio.run(test())
