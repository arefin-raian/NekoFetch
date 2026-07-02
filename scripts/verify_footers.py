"""Quick verify footer fix on sample channels."""
import asyncio, sys, os, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

with open('resources/language/en.json', encoding='utf-8') as f:
    EN_FOOTER = json.load(f)['bot_footer']

async def verify():
    c = Container.create(); await c.startup()
    pool = UserbotPool.from_env(c.env.telegram_api_id, c.env.telegram_api_hash, str(c.env.session_path))
    client = await pool.acquire()

    for u in ['fruits_basket_ani_weebs', 'Nisekoi_ani_weebs', 'naruto_shippuden_ani_weebs', 'chainsaw_man_aw']:
        chat = await client.get_chat(u)
        async for m in client.get_chat_history(chat.id, limit=20):
            cap = m.caption or m.text or ''
            if 'ANIME WEEBS' in cap:
                match = 'MATCH' if cap.strip() == EN_FOOTER.strip() else 'MISMATCH'
                print(f'{u} (msg {m.id}): {match}')
                break

asyncio.run(verify())
