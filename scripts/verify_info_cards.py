import asyncio, sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, "C:/Users/Admin/Documents/NekoFetch")
os.chdir("C:/Users/Admin/Documents/NekoFetch")

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.parser.html import HTML

async def verify():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()
    html_parser = HTML(client)
    
    for label, uname in [
        ('EMINENCE msg 3', 'the_eminence_in_shadow_ani_weebs'),
        ('FRUITS BASKET msg 3', 'fruits_basket_ani_weebs'),
        ('KONOSUBA msg 2', 'konosuba_ani_weebs'),
    ]:
        chat = await client.get_chat(uname)
        cid = chat.id
        print(f'\n{"="*80}')
        print(f'{label}')
        print('='*80)
        
        async for msg in client.get_chat_history(cid, limit=10):
            cap = msg.caption or ''
            if not cap:
                continue
            if 'ANIME WEEBS' in cap.upper():
                continue
            if 'Genres' in cap or 'Rating' in cap or 'Type' in cap:
                ents = msg.caption_entities or []
                html = html_parser.unparse(cap, ents)
                print(f'msg {msg.id} [{len(ents)} ents]')
                print(html[:800])
                print()
                break

asyncio.run(verify())
