"""
Fix footers on all channels from Weebs, Weebs 2, and Ongoing Fall folders.
Replaces the entire footer caption with the one from en.json.
"""
import json
import sys
import asyncio
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

DRY_RUN = True  # Set to True to preview only


def load_footer():
    with open('resources/language/en.json', encoding='utf-8') as f:
        data = json.load(f)
    return data['bot_footer']


async def main():
    from nekofetch.core.container import Container
    from nekofetch.sources.telegram.userbot import UserbotPool
    from pyrogram.raw.functions.messages import GetDialogFilters
    from pyrogram.enums import ParseMode, ChatType

    FOOTER = load_footer()
    print(f'Loaded footer from en.json ({len(FOOTER)} chars)')
    print()

    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    # --- Step 1: Get folder peer IDs ---
    result = await client.invoke(GetDialogFilters())
    filters = result.filters if hasattr(result, 'filters') else []

    def safe_title(f):
        title = getattr(f, 'title', '')
        if hasattr(title, 'text'):
            return title.text
        return str(title) if title else ''

    target_names = {'Weebs', 'Weebs 2', 'Ongoing Fall'}
    folder_channels = {}  # channel_id (int) -> folder_name

    for f in filters:
        name = safe_title(f)
        if name not in target_names:
            continue
        peers = list(getattr(f, 'pinned_peers', [])) + list(getattr(f, 'include_peers', []))
        for peer in peers:
            cid = getattr(peer, 'channel_id', None)
            if cid:
                folder_channels[int(cid)] = name
        print(f'Folder "{name}": {len(peers)} peers')

    total_ids = len(folder_channels)
    print(f'\nTotal unique channel IDs across 3 folders: {total_ids}')
    print()

    # --- Step 2: Resolve IDs to usernames via dialogs ---
    # Iterate all dialogs and build ID -> username mapping for channels
    id_to_info = {}  # channel_id -> (username, title)
    print('Resolving channels via dialogs...')
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        if chat.type in (ChatType.CHANNEL, ChatType.SUPERGROUP):
            cid = chat.id
            if cid in folder_channels:
                # Telegram channel IDs can be negative; normalize
                id_to_info[cid] = (
                    getattr(chat, 'username', None),
                    chat.title or str(cid),
                )
                # Also try the negative variant (some APIs differ)
                if cid > 0:
                    id_to_info[-cid] = id_to_info[cid]
                else:
                    id_to_info[abs(cid)] = id_to_info[cid]
        # Break early if we've found them all
        if len(id_to_info) >= total_ids * 2:  # allowance for negative variants
            pass

    # Try matching folder IDs against our resolved IDs
    resolved = []
    for cid, folder in folder_channels.items():
        # Try direct, negative, and positive variants
        for lookup in (cid, -cid, abs(cid)):
            if lookup in id_to_info:
                uname, title = id_to_info[lookup]
                if uname:
                    resolved.append((uname, title, folder))
                    break
        else:
            print(f'  ⚠️ ID {cid} not resolved (folder: {folder})')

    print(f'Resolved {len(resolved)} channels with usernames')
    print()

    # --- Step 3: Fix footers ---
    fixed = 0
    skipped_ok = 0
    skipped_no_footer = 0
    errors = 0

    for uname, title, folder in resolved:
        try:
            chat = await client.get_chat(uname)
            # Find footer message
            async for msg in client.get_chat_history(chat.id, limit=30):
                cap = msg.caption or msg.text or ''
                if not cap:
                    continue
                # Detect footer by keywords
                has_footer = any(kw in cap for kw in (
                    'ANIME WEEBS', 'Ani_Weebs', 'Weebs_Server',
                    'AniMovie_Weebs', 'Ongoing_Ani_Weebs', 'Weebs_GC',
                ))
                if not has_footer:
                    continue

                # Check if already matches our format
                if cap.strip() == FOOTER.strip():
                    print(f'  ✅ {uname} (msg {msg.id}): already correct')
                    skipped_ok += 1
                    break

                if DRY_RUN:
                    print(f'  [DRY RUN] {uname} (msg {msg.id}): would fix ({len(cap)} -> {len(FOOTER)} chars)')
                    fixed += 1
                else:
                    try:
                        if msg.caption:
                            await msg.edit_caption(FOOTER, parse_mode=ParseMode.HTML)
                        else:
                            await msg.edit_text(FOOTER, parse_mode=ParseMode.HTML)
                        print(f'  ✅ {uname} (msg {msg.id}): FIXED ({len(cap)} -> {len(FOOTER)} chars)')
                        fixed += 1
                    except Exception as e:
                        print(f'  ❌ {uname} (msg {msg.id}): {e}')
                        errors += 1
                break  # only one footer per channel
            else:
                print(f'  ⚠️ {uname}: no footer message found in last 30 messages')
                skipped_no_footer += 1
        except Exception as e:
            print(f'  ❌ {uname}: cannot access channel - {e}')
            errors += 1

    print()
    print('=' * 60)
    print(f'Fixed:      {fixed}')
    print(f'Skipped OK: {skipped_ok}')
    print(f'No footer:  {skipped_no_footer}')
    print(f'Errors:     {errors}')
    print(f'Total:      {len(resolved)}')
    print('=' * 60)


if __name__ == '__main__':
    asyncio.run(main())
