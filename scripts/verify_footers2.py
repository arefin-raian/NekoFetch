"""Verify footers by round-tripping through Pyrogram's HTML parser."""
import asyncio, sys, os, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.parser.html import HTML

with open('resources/language/en.json', encoding='utf-8') as f:
    EN = json.load(f)['bot_footer']

async def verify():
    c = Container.create(); await c.startup()
    pool = UserbotPool.from_env(c.env.telegram_api_id, c.env.telegram_api_hash, str(c.env.session_path))
    client = await pool.acquire()
    hp = HTML(client)

    for u in ['fruits_basket_ani_weebs', 'Nisekoi_ani_weebs', 'chainsaw_man_aw', 'naruto_shippuden_ani_weebs']:
        chat = await client.get_chat(u)
        async for m in client.get_chat_history(chat.id, limit=20):
            cap = m.caption or m.text or ''
            if 'ANIME WEEBS' not in cap:
                continue
            ents = m.caption_entities or m.entities or []
            html = hp.unparse(cap, ents)
            match = 'MATCH' if html.strip() == EN.strip() else 'MISMATCH'
            print(f'{u} (msg {m.id}): {match} [{len(html)} vs {len(EN)} chars]')
            if match == 'MISMATCH':
                for i, (a, b) in enumerate(zip(html, EN)):
                    if a != b:
                        ctx = 30
                        print(f'  Diff at {i}:')
                        print(f'    Ch: {repr(html[max(0,i-ctx):i+ctx])}')
                        print(f'    En: {repr(EN[max(0,i-ctx):i+ctx])}')
                        break
            break

asyncio.run(verify())
