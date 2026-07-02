import asyncio, sys, os
sys.path.insert(0, 'C:/Users/Admin/Documents/NekoFetch')
os.chdir('C:/Users/Admin/Documents/NekoFetch')

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.enums import MessageEntityType
from pyrogram.parser.html import HTML

async def extract():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()
    
    for label, uname in [
        ('FIXED - Eminence', 'the_eminence_in_shadow_ani_weebs'),
        ('BROKEN - Fruits Basket', 'fruits_basket_ani_weebs'),
    ]:
        chat = await client.get_chat(uname)
        cid = chat.id
        print(f'\n{"="*80}')
        print(f'{label}')
        print(f'ID: {cid}')
        print('='*80)
        
        count = 0
        async for msg in client.get_chat_history(cid, limit=5):
            cap = msg.caption or ''
            if not cap:
                continue
            count += 1
            ents = msg.caption_entities or []
            print(f'\n--- MSG {msg.id} (media_group_id={msg.media_group_id}) [{len(ents)} entities] ---')
            for e in ents:
                start = e.offset
                end = start + e.length
                text = cap[start:end]
                extra = ''
                if e.type == MessageEntityType.TEXT_LINK:
                    extra = f' url={e.url}'
                elif e.type == MessageEntityType.BOLD:
                    extra = ' [BOLD]'
                elif e.type == MessageEntityType.ITALIC:
                    extra = ' [ITALIC]'
                elif e.type == MessageEntityType.CODE:
                    extra = ' [CODE]'
                elif e.type == MessageEntityType.PRE:
                    extra = f' [PRE lang={e.language}]'
                elif e.type == MessageEntityType.BLOCKQUOTE:
                    extra = ' [BLOCKQUOTE]'
                elif e.type == MessageEntityType.EXPANDABLE_BLOCKQUOTE:
                    extra = ' [EXPANDABLE_BLOCKQUOTE]'
                print(f'  ent [{start}:{end}] type={e.type.name}{extra} | {text!r}')
            
            parser = HTML(client)
            html_text = parser.unparse(cap, ents)
            print(f'  HTML (last 600 chars):')
            print(f'  {html_text[-600:].replace(chr(10), chr(10)+"  ")}')
            print()
            if count >= 2:
                break

asyncio.run(extract())
