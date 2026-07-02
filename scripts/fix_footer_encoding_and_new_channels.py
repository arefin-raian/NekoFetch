"""
Fix two things:
1. en.json footer — corrupted small caps characters (from the earlier Python script)
2. Footers on newly discovered channels from Weebs/Weebs 2/Ongoing Fall folders
"""
import json
import sys
import asyncio
import os

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DRY_RUN = False  # Set to True to preview only

# ---------- CORRECT SMALL CAPS MAP ----------
# The original footer text (from git) uses these characters:
CORRECT_TITLE_LINE = (
    '<blockquote expandable><b>ANIME WEEBS - '
    '\ua730\u1d07\u1d07\u029f '
    '\u1d1b\u029c\u1d07 '
    '\ua731\u1d1b\u1d0f\u0280\u028f, '
    '\u029f\u026a\u1d20\u1d07 '
    '\u1d1b\u029c\u1d07 '
    '\u1d00\u0280\u1d1b'
    '</b></blockquote>'
)

# Build the full footer matching en.json structure
CORRECT_FOOTER = (
    CORRECT_TITLE_LINE + '\n'
    '\u2500' * 53 + '\n'
    '<b>\u2b25 A\u0274\u026a\u1d0d\u1d07: </b>'
    '<a href="https://t.me/AniXWeebs"><b>@A\u0274\u026aXW\u1d07\u1d07\u0299s</b></a><b>\n'
    '\u2b25 N\u1d07\u1d1b\u0280\u1d0f\u0280\u1d0b: </b>'
    '<a href="https://t.me/WeebsXServer"><b>@W\u1d07\u1d07\u0299sXS\u1d07\u0280\u1d20\u1d07\u0280</b></a><b>\n'
    '\u2b25 O\u0274\u0262\u1d0f\u026a\u0274\u0262: </b>'
    '<a href="https://t.me/Ongoing_AniXWeebs"><b>@O\u0274\u0262\u1d0f\u026a\u0274\u0262_A\u0274\u026aXW\u1d07\u1d07\u0299s</b></a><b>\n'
    '\u2b25 A\u0274\u026a\u1d0d\u1d07 M\u1d0f\u1d20\u026a\u1d07s: </b>'
    '<a href="https://t.me/AniMovieXWeebs"><b>@A\u0274\u026aM\u1d0f\u1d20\u026a\u1d07XW\u1d07\u1d07\u0299s</b></a>\n'
    '\u2500' * 53 + '\n'
    '<blockquote expandable><b>V\u026as\u026a\u1d1b </b>'
    '<a href="https://t.me/WeebsXGC">@W\u1d07\u1d07\u0299sXGC</a>'
    ' <b>\u0262\u1d0f\u0280 \u1d0d\u1d0f\u0280\u1d07 \u026a\u0274\u0262\u1d0f</b></blockquote>'
)


def fix_enjson():
    """Fix the corrupted small caps in en.json footer."""
    enjson_path = 'resources/language/en.json'
    with open(enjson_path, encoding='utf-8') as f:
        data = json.load(f)

    old_footer = data.get('bot_footer', '')
    print(f'Current footer length: {len(old_footer)}')

    # Check if it's already correct
    if '\u1d1b\u029c\u1d07' in old_footer and '\ua731\u1d1b\u1d0f\u0280\u028f' in old_footer:
        print('Footer appears correct already — skipping en.json fix.')
        return

    # Check for the corrupted characters
    corrupted_chars = ['\u1d05', '\u1d1c', '\u1d04', '\u0299', '\u1d00\u0280\u1d1c']
    needs_fix = False
    for c in corrupted_chars:
        if c in old_footer:
            needs_fix = True
            break

    if needs_fix:
        print('EN.JSON FOOTER IS CORRUPTED — fixing...')
        if DRY_RUN:
            print('[DRY RUN] Would replace footer.')
            print('New footer preview:')
            print(CORRECT_FOOTER[:200] + '...')
        else:
            data['bot_footer'] = CORRECT_FOOTER
            with open(enjson_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print('✅ en.json footer fixed.')
    else:
        print('Footer characters look OK.')

    # Verify by re-reading
    with open(enjson_path, encoding='utf-8') as f:
        data2 = json.load(f)
    footer = data2['bot_footer']
    # Check key expected characters
    expected = ['\ua730', '\u1d07', '\u029f', '\u1d1b', '\u029c']  # ꜰ, ᴇ, ʟ, ᴛ, ʜ
    missing = [e for e in expected if e not in footer]
    if missing:
        print(f'WARNING: Still missing expected chars: {missing}')
    else:
        print('✅ Verified: all expected small caps present.')

    # Show what we have now
    print('\n--- Current footer (first 300 chars) ---')
    print(CORRECT_FOOTER[:300])


async def fix_new_channels():
    """Fix footers on channels from Weebs, Weebs 2, Ongoing Fall folders."""
    from nekofetch.core.container import Container
    from nekofetch.sources.telegram.userbot import UserbotPool
    from pyrogram.raw.functions.messages import GetDialogFilters
    from pyrogram.raw.types import InputPeerChannel, PeerChannel
    from pyrogram.enums import ParseMode

    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    # Get folders
    result = await client.invoke(GetDialogFilters())
    filters = result.filters if hasattr(result, 'filters') else []

    def safe_title(f):
        title = getattr(f, 'title', '')
        if hasattr(title, 'text'):
            return title.text
        return str(title) if title else ''

    target_names = {'Weebs', 'Weebs 2', 'Ongoing Fall'}

    # Collect all channel IDs from target folders
    all_channels = {}  # id -> folder_name
    for f in filters:
        name = safe_title(f)
        if name in target_names:
            peers = getattr(f, 'pinned_peers', []) + getattr(f, 'include_peers', [])
            for peer in peers:
                if hasattr(peer, 'channel_id'):
                    all_channels[int(peer.channel_id)] = name
            print(f'Folder "{name}": {len(peers)} peers')

    print(f'\nTotal unique channels across 3 folders: {len(all_channels)}')

    # Resolve channel IDs to usernames
    resolved = {}
    for cid, folder in all_channels.items():
        try:
            peer = InputPeerChannel(channel_id=cid, access_hash=0)
            # Try resolving via get_chat
            chat = await client.get_chat(cid)
            username = getattr(chat, 'username', None)
            if username:
                resolved[username] = (chat.title or str(cid), folder, cid)
        except Exception as e:
            # Try via PeerChannel
            try:
                chat = await client.get_chat(PeerChannel(channel_id=cid))
                username = getattr(chat, 'username', None)
                if username:
                    resolved[username] = (chat.title or str(cid), folder, cid)
            except Exception:
                pass

    print(f'Resolved {len(resolved)} channels with usernames')

    # Already-fixed channels from previous runs (54 publishable channels)
    already_fixed = set()
    # We'll detect by checking if the footer already has the correct format

    fixed_count = 0
    skipped_count = 0
    error_count = 0

    for uname, (title, folder, cid) in resolved.items():
        try:
            chat = await client.get_chat(uname)
            # Find the footer message (last message or the one with "ANIME WEEBS")
            async for msg in client.get_chat_history(chat.id, limit=20):
                cap = msg.caption or msg.text or ''
                if not cap:
                    continue
                if 'ANIME WEEBS' not in cap and 'Aɴɪᴍᴇ' not in cap and 'AniXWeebs' not in cap and 'Ani_Weebs' not in cap:
                    continue

                # Check if already has correct format
                if '<blockquote expandable><b>ANIME WEEBS' in cap and 'WeebsXGC' in cap:
                    print(f'  ✅ {uname} (msg {msg.id}): already correct')
                    skipped_count += 1
                    break

                # Check if needs fixing
                if not DRY_RUN:
                    try:
                        await msg.edit_caption(CORRECT_FOOTER, parse_mode=ParseMode.HTML)
                        print(f'  ✅ {uname} (msg {msg.id}): FIXED')
                        fixed_count += 1
                    except Exception as e:
                        # Try editing via text if no caption
                        try:
                            await msg.edit_text(CORRECT_FOOTER, parse_mode=ParseMode.HTML)
                            print(f'  ✅ {uname} (msg {msg.id}): FIXED (text)')
                            fixed_count += 1
                        except Exception as e2:
                            print(f'  ❌ {uname} (msg {msg.id}): FAILED - {e2}')
                            error_count += 1
                else:
                    print(f'  [DRY RUN] {uname} (msg {msg.id}): would fix')
                    fixed_count += 1
                break  # Only fix one footer per channel
            else:
                print(f'  ⚠️ {uname}: no footer message found')
                skipped_count += 1
        except Exception as e:
            print(f'  ❌ {uname}: error accessing channel - {e}')
            error_count += 1

    print(f'\n--- Summary ---')
    print(f'Fixed: {fixed_count}')
    print(f'Skipped: {skipped_count}')
    print(f'Errors: {error_count}')
    print(f'Total channels processed: {len(resolved)}')


if __name__ == '__main__':
    print('=== STEP 1: Fix en.json footer encoding ===')
    fix_enjson()

    print('\n=== STEP 2: Fix new channel footers ===')
    asyncio.run(fix_new_channels())
