"""Debug footer mismatches - show exact differences."""
import asyncio, sys, os, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

with open('resources/language/en.json', encoding='utf-8') as f:
    EN_FOOTER = json.load(f)['bot_footer']

async def debug():
    c = Container.create(); await c.startup()
    pool = UserbotPool.from_env(c.env.telegram_api_id, c.env.telegram_api_hash, str(c.env.session_path))
    client = await pool.acquire()

    for u in ['fruits_basket_ani_weebs', 'chainsaw_man_aw']:
        chat = await client.get_chat(u)
        async for m in client.get_chat_history(chat.id, limit=20):
            cap = m.caption or m.text or ''
            if 'ANIME WEEBS' in cap:
                print(f'=== {u} (msg {m.id}) ===')
                print(f'Channel len: {len(cap)}, EN len: {len(EN_FOOTER)}')
                print(f'Channel newlines: {cap.count(chr(10))}, EN newlines: {EN_FOOTER.count(chr(10))}')
                print(f'Channel dashes: {cap.count(chr(0x2500))}, EN dashes: {EN_FOOTER.count(chr(0x2500))}')
                
                # Show first difference
                if cap != EN_FOOTER:
                    for i, (a, b) in enumerate(zip(cap, EN_FOOTER)):
                        if a != b:
                            ctx = 20
                            start = max(0, i - ctx)
                            print(f'Diff at char {i}:')
                            print(f'  Channel: ...{repr(cap[start:i+ctx])}...')
                            print(f'  EN JSON: ...{repr(EN_FOOTER[start:i+ctx])}...')
                            print(f'  Channel char[{i}]: U+{ord(cap[i]):04X} {repr(cap[i])}')
                            print(f'  EN char[{i}]:    U+{ord(EN_FOOTER[i]):04X} {repr(EN_FOOTER[i])}')
                            break
                    else:
                        if len(cap) < len(EN_FOOTER):
                            print(f'Channel is shorter: missing {repr(EN_FOOTER[len(cap):len(cap)+50])}')
                        else:
                            print(f'Channel has extra: {repr(cap[len(EN_FOOTER):len(EN_FOOTER)+50])}')
                print()
                break

asyncio.run(debug())
