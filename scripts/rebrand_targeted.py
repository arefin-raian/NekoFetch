"""Targeted rebrand — ONLY checks known active download channels.

Uses the verified channel list from earlier, not all 200+ dialogs.
Replaces @Ani_Weebs → @AniXWeebs with HTML <a> links.
"""
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime

logging.disable(logging.CRITICAL)
os.environ["LOG_LEVEL"] = "CRITICAL"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from pyrogram.enums import ChatType, ParseMode

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool

RESULT_PATH = os.path.expanduser("~/Documents/rebrand_results.json")

# ALL known active download channels from our verification
# These are confirmed ACTIVE channels that should have the old footer
ACTIVE_CHANNELS = [
    # Fully confirmed active (25 from original + 30 from flood-wait retry)
    "Akame_ga_kill_ani_weebs",
    "Barakamon_ani_weebs",
    "Batman_Ninja_vs_yakuzaleague",
    "Black_Clover_Ani_weebs",
    "Blue_Spring_Ride_ani_weebs",
    "Code_geass_ani_weebs",
    "Death_note_ani_weebs",
    "Erased_ani_weebs",
    "Fire_Force_ani_weebs",
    "God_of_Highschool",
    "Grand_blue_ani_weebs",
    "Hunter_X_Hunter_ani_weebs",
    "Hyouka_ani_weebs",
    "ID_Invaded_ani_weebs",
    "Kuroko_Basketball_ani_weebs",
    "Malevolent_Spirits",
    "Mob_psycho_100_ani_weebs",
    "Monster_ani_weebs",
    "My_hero_Academia_1080p_480p",
    "Nana_ani_weebs",
    "the_angel_next_door_ani_weebs",
    "the_eminence_in_shadow_ani_weebs",
    "the_new_gate_dual_ani_weebs",
    "uzumaki_ani_weebs",
    "wind_breaker_dual_ani_weebs",
    # Recovered from flood-wait (30 channels)
    "Ninety_one_Days_ani_weebs",
    "Nisekoi_ani_weebs",
    "No_Game_No_life_ani_weebs",
    "Promised_Neverland_ani_weebs",
    "Samurai_Champloo_ani_weebs",
    "Snow_white_with_the_Red_Hair_ani",
    "Steins_Gate_ani_weebs",
    "The_ossan_newbie_ani_weebs",
    "Tokyo_ghoul_ani_weebs",
    "Vinland_saga_ani_weebs",
    "Violet_Evergarden_ani_weebs",
    "Weebs_Server",
    "Your_Lie_in_April_ani_weebs",
    "ani_weebs_jujutsu_kaisen",
    "ani_weebs_solo_leveling",
    "classroom_ofthe_Elite_ani_weebs",
    "demon_slayer_dual_ani_weebs",
    "frieren_ani_weebs",
    "fruits_basket_ani_weebs",
    "haikyu_ani_weebs",
    "hellsing_ultimate_ani_weebs",
    "jobless_reincarnation_Ani_weebs",
    "kaiju_no_8_multi_ani_weebs",
    "kenichi_ani_weebs",
    "konosuba_ani_weebs",
    "mashle_dual_ani_weebs",
    "naruto_shippuden_ani_weebs",
    "one_punch_man_ani_weebs",
    "our_last_crusade_ani_weebs",
    "pluto_ani_weebs",
]

# Channel IDs we know from verification (add these too)
ACTIVE_IDS = [
    -1002178506397,  # frieren_ani_weebs
]

# @username replacements
REPLACEMENTS = [
    ("Ani_Weebs", "AniXWeebs"),
    ("Weebs_Server", "WeebsXServer"),
    ("Ongoing_Ani_Weebs", "Ongoing_AniXWeebs"),
    ("AniMovie_Weebs", "AniMovieXWeebs"),
    ("Weebs_GC", "Weebs_GC"),
]

# Small caps unicode mapping
SC = {
    '\u1d00': 'a', '\u0299': 'b', '\u1d04': 'c', '\u1d05': 'd',
    '\u1d07': 'e', '\ua730': 'f', '\u0262': 'g', '\u029c': 'h',
    '\u026a': 'i', '\u1d0a': 'j', '\u1d0b': 'k', '\u029f': 'l',
    '\u1d0d': 'm', '\u0274': 'n', '\u1d0f': 'o', '\u1d18': 'p',
    '\u01eb': 'q', '\u0280': 'r', '\ua731': 's', '\u1d1b': 't',
    '\u1d1c': 'u', '\u1d20': 'v', '\u1d21': 'w', '\u028f': 'y', '\u1d22': 'z',
}

def build_regex(old_uname: str) -> re.Pattern:
    """Build regex matching @old_uname with any mix of regular/small-caps letters."""
    pattern = '@'
    for c in old_uname:
        if c == '_':
            pattern += '_'
        elif c.isalpha():
            cl = c.lower()
            sc_chars = [k for k, v in SC.items() if v == cl]
            group = c + cl.upper() + ''.join(sc_chars)
            pattern += f'[{group}]'
        else:
            pattern += re.escape(c)
    return re.compile(pattern)

PATTERNS = []
for old_uname, new_uname in REPLACEMENTS:
    pat = build_regex(old_uname)
    repl = f'<a href="https://t.me/{new_uname}">@{new_uname}</a>'
    PATTERNS.append((pat, repl))

def replace_in_text(text: str) -> tuple[str, bool]:
    """Replace @old_uname with HTML links. Returns (new_text, changed)."""
    if not text:
        return text, False
    changed = False
    for pat, repl in PATTERNS:
        if pat.search(text):
            text = pat.sub(repl, text)
            changed = True
    return text, changed

async def main():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    client = await pool.acquire()

    results = {"timestamp": datetime.now().isoformat(), "total_edited": 0, "channels": {}}
    total = len(ACTIVE_CHANNELS) + len(ACTIVE_IDS)
    idx = 0

    # Process by username
    for username in ACTIVE_CHANNELS:
        idx += 1
        print(f"[{idx}/{total}] @{username}...", end=" ", flush=True)
        ch_res = {"edited": 0, "ids": []}

        try:
            async for msg in client.get_chat_history(username, limit=100):
                text = msg.text or msg.caption or ""
                if not text:
                    continue
                new_text, changed = replace_in_text(text)
                if changed and new_text != text:
                    try:
                        await client.edit_message_text(
                            username, msg.id, new_text,
                            parse_mode=ParseMode.HTML,
                        )
                        ch_res["edited"] += 1
                        ch_res["ids"].append(msg.id)
                        print("✏️", end="", flush=True)
                        await asyncio.sleep(2)
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value + 1)
                        print("⏳", end="", flush=True)
                    except RPCError as e:
                        if "MESSAGE_NOT_MODIFIED" in str(e):
                            pass
                        elif "CHAT_ADMIN_REQUIRED" in str(e) or "USER_NOT_PARTICIPANT" in str(e):
                            print("🔒", end="", flush=True)
                            break
                        else:
                            print("❌", end="", flush=True)
                            await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️({str(e)[:40]})", end="", flush=True)

        print(f" {ch_res['edited']} edits")
        results["channels"][f"@{username}"] = ch_res
        results["total_edited"] += ch_res["edited"]
        await asyncio.sleep(1)

    # Process by ID
    for cid in ACTIVE_IDS:
        idx += 1
        print(f"[{idx}/{total}] channel {cid}...", end=" ", flush=True)
        ch_res = {"edited": 0, "ids": []}

        try:
            async for msg in client.get_chat_history(cid, limit=100):
                text = msg.text or msg.caption or ""
                if not text:
                    continue
                new_text, changed = replace_in_text(text)
                if changed and new_text != text:
                    try:
                        await client.edit_message_text(
                            cid, msg.id, new_text,
                            parse_mode=ParseMode.HTML,
                        )
                        ch_res["edited"] += 1
                        ch_res["ids"].append(msg.id)
                        print("✏️", end="", flush=True)
                        await asyncio.sleep(2)
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value + 1)
                        print("⏳", end="", flush=True)
                    except RPCError as e:
                        if "MESSAGE_NOT_MODIFIED" in str(e):
                            pass
                        elif "CHAT_ADMIN_REQUIRED" in str(e):
                            print("🔒", end="", flush=True)
                            break
                        else:
                            print("❌", end="", flush=True)
                            await asyncio.sleep(1)
        except Exception as e:
            print(f"⚠️({str(e)[:40]})", end="", flush=True)

        print(f" {ch_res['edited']} edits")
        results["channels"][str(cid)] = ch_res
        results["total_edited"] += ch_res["edited"]
        await asyncio.sleep(1)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nDone! Edited {results['total_edited']} messages across {idx} channels")
    print(f"Saved to: {RESULT_PATH}")

    await pool.close()
    await container.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
