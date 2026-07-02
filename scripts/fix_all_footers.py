"""
Fix footers on ALL anime channels (excluding hub/main channels).
Replaces the entire footer caption with the en.json footer.
"""
import json
import sys
import asyncio
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# Hub/main channels to skip (they have their own footer format)
HUB_CHANNELS = {
    'AniXWeebs', 'AniMovie_Weebs', 'AniMovieXWeebs',
    'Ongoing_Ani_Weebs', 'Ongoing_AniXWeebs', 'Ongoing_Anime_Weebs',
    'AniXWeebs_Index', 'rai_yan_00_bio',
    'WeebsXServer', 'WeebsXGC',
}


def load_footer():
    with open('resources/language/en.json', encoding='utf-8') as f:
        data = json.load(f)
    return data['bot_footer']


async def main():
    from nekofetch.core.container import Container
    from nekofetch.sources.telegram.userbot import UserbotPool
    from pyrogram.enums import ChatType, ParseMode

    FOOTER = load_footer()
    print(f'Footer from en.json: {len(FOOTER)} chars')

    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    fixed = 0
    skipped_hub = 0
    skipped_ok = 0
    skipped_no_footer = 0
    errors = 0

    count = 0
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
            continue
        uname = getattr(chat, 'username', None)
        if not uname:
            continue
        count += 1

        # Skip hub channels
        if uname in HUB_CHANNELS:
            skipped_hub += 1
            continue

        # Find footer message
        found = False
        async for msg in client.get_chat_history(chat.id, limit=30):
            cap = msg.caption or msg.text or ''
            if not cap:
                continue
            has_footer = any(kw in cap for kw in (
                'ANIME WEEBS', 'Ani_Weebs', 'Weebs_Server',
                'AniMovie_Weebs', 'Ongoing_Ani_Weebs', 'Weebs_GC',
                'AniXWeebs', 'WeebsXServer', 'Ongoing_AniXWeebs',
                'AniMovieXWeebs', 'WeebsXGC',
            ))
            if not has_footer:
                continue
            found = True

            if cap.strip() == FOOTER.strip():
                skipped_ok += 1
                break

            try:
                if msg.caption:
                    await msg.edit_caption(FOOTER, parse_mode=ParseMode.HTML)
                else:
                    await msg.edit_text(FOOTER, parse_mode=ParseMode.HTML)
                print(f'  ✅ {uname} (msg {msg.id})')
                fixed += 1
            except Exception as e:
                print(f'  ❌ {uname} (msg {msg.id}): {e}')
                errors += 1
            break

        if not found:
            skipped_no_footer += 1

        if count % 50 == 0:
            print(f'Progress: {count} channels, {fixed} fixed...')

    print()
    print('=' * 60)
    print(f'Channels scanned:  {count}')
    print(f'Fixed:             {fixed}')
    print(f'Skipped (hub):     {skipped_hub}')
    print(f'Skipped (OK):      {skipped_ok}')
    print(f'No footer found:   {skipped_no_footer}')
    print(f'Errors:            {errors}')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
