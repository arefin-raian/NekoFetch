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

        # Get the o() function with context
        idx = 54829
        # Go back to find the beginning of the module/function containing o
        start = max(0, idx - 200)
        end = min(len(js), idx + 2000)
        
        snippet = js[start:end]
        print("=== Function o() and surrounding context ===")
        print(snippet)
        print("\n\n")

        # Also get function r() which is used by o
        idx_r = js.find("function r(){var t=[arguments]")
        if idx_r >= 0:
            start_r = max(0, idx_r - 200)
            end_r = min(len(js), idx_r + 2000)
            print("=== Function r() and surrounding context ===")
            print(js[start_r:end_r])
        
        # Get the a.F2, a.u1, a.u$, a.T7 functions
        # Search for a.F2 definition
        for pat in [r'a\.F2\s*=\s*function', r'a\.u1\s*=\s*function', r'a\.u\$\s*=\s*function', r'a\.T7\s*=\s*function', r'a\.q_\s*=\s*function']:
            for m in re.finditer(pat, js):
                start_m = max(0, m.start())
                end_m = min(len(js), m.end() + 500)
                print(f"\n=== {pat} ===")
                print(js[start_m:end_m])


asyncio.run(test())
