"""Retry verification of flood-wait channels with generous delays.

Previous run hit FLOOD_WAIT on 39 channels because it was too fast.
This script waits 5 seconds between each check to stay within rate limits.
Uses the userbot (not bot) since we're resolving usernames.
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

from nekofetch.core.container import Container
from nekofetch.sources.telegram.userbot import UserbotPool
from pyrogram.errors import UsernameNotOccupied, UsernameInvalid, FloodWait

RESULT_PATH = os.path.expanduser("~/Documents/final_channel_verification.json")
OLD_RESULT_PATH = os.path.expanduser("~/Documents/channel_verification.json")

# All channel usernames we need to re-check (flood-wait + ones we want fresh status on)
ALL_USERNAMES = [
    "Ninety_one_Days_ani_weebs",
    "Nisekoi_ani_weebs",
    "No_Game_No_life_ani_weebs",
    "No_Longer_Allowed_Ani_Weebs",
    "Promised_Neverland_ani_weebs",
    "Samurai_Champloo_ani_weebs",
    "Snow_white_with_the_Red_Hair_ani",
    "Steins_Gate_ani_weebs",
    "Tensura_Ani_Weebs",
    "The_ossan_newbie_ani_weebs",
    "Tokyo_ghoul_ani_weebs",
    "True_beauty_ani_weebs",
    "Tsukimichi_ani_weebs",
    "Vinland_saga_ani_weebs",
    "Violet_Evergarden_ani_weebs",
    "Weebs_Server",
    "Why_nobody_remembers_me",
    "Wistoria_Wands_Sword_Ani_Weebs",
    "Your_Lie_in_April_ani_weebs",
    "ani_weebs_jujutsu_kaisen",
    "ani_weebs_solo_leveling",
    "attack_on_titan_ani_weebs",
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
    "oshi_no_ko_Dual_ani_weebs",
    "our_last_crusade_ani_weebs",
    "pluto_ani_weebs",
    "re_ZERO_ani_weebs",
]
# Don't check these - already confirmed
BANNED = {"Another_ani_weebs", "Blue_lock_Ani_weebs", "Cowboy_Bebop_ani_weebs",
           "Day_With_My_StepSister_Ani_Weebs", "Failure_Frame_Ani_weebs",
           "Fairy_Tail_Ani_Weebs", "My_wi_fe_has_no_emotion", "makeine_ani_weebs",
           "reincarnated_aristocrat_dual_aw", "shoushimin_Ani_Weebs",
           "zom100_ani_weebs", "My_Little_Monster_Ani_Weebs"}


async def main():
    container = Container.create()
    await container.startup()
    pool = UserbotPool.from_env(
        container.env.telegram_api_id,
        container.env.telegram_api_hash,
        str(container.env.session_path),
    )
    userbot = await pool.acquire()

    results = {}
    active = 0
    banned = 0
    still_flood = 0

    # Load previous results for comparison
    old_results = {}
    if os.path.exists(OLD_RESULT_PATH):
        with open(OLD_RESULT_PATH, encoding="utf-8") as f:
            old_data = json.load(f)
        old_results = old_data.get("results", {})

    print(f"Retrying {len(ALL_USERNAMES)} channels...")
    print(f"5s delay between each check to avoid flood\n")

    for i, username in enumerate(ALL_USERNAMES):
        print(f"  [{i+1}/{len(ALL_USERNAMES)}] @{username}...", end=" ", flush=True)

        try:
            try:
                chat = await userbot.get_chat(username)
                results[username] = {
                    "status": "active",
                    "urls": [f"https://t.me/{username}"],
                    "chat_id": chat.id,
                    "chat_title": chat.title if hasattr(chat, 'title') else "?",
                }
                active += 1
                print(f"✅ ACTIVE ({chat.title if hasattr(chat, 'title') else '?'})")
            except (UsernameNotOccupied, UsernameInvalid) as exc:
                err_type = type(exc).__name__
                results[username] = {
                    "status": "banned_deleted",
                    "error": err_type,
                    "urls": [f"https://t.me/{username}"],
                }
                banned += 1
                print(f"🔴 BANNED ({err_type})")
        except UsernameNotOccupied:
            results[username] = {
                "status": "banned_deleted",
                "error": "USERNAME_NOT_OCCUPIED",
                "urls": [f"https://t.me/{username}"],
            }
            banned += 1
            print("🔴 BANNED (USERNAME_NOT_OCCUPIED)")
        except UsernameInvalid:
            results[username] = {
                "status": "banned_deleted",
                "error": "USERNAME_INVALID",
                "urls": [f"https://t.me/{username}"],
            }
            banned += 1
            print("🔴 BANNED (USERNAME_INVALID)")
        except FloodWait as e:
            results[username] = {
                "status": "flood_wait",
                "error": f"FLOOD_WAIT ({e.value}s)",
                "urls": [f"https://t.me/{username}"],
            }
            still_flood += 1
            print(f"⚠️ FLOOD ({e.value}s)")
        except Exception as e:
            err_str = str(e)[:100]
            results[username] = {
                "status": "error",
                "error": err_str,
                "urls": [f"https://t.me/{username}"],
            }
            still_flood += 1
            print(f"⚠️ ERROR: {err_str}")

        # 5 second delay between checks
        if i < len(ALL_USERNAMES) - 1:
            await asyncio.sleep(5)

    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_checked": len(ALL_USERNAMES),
        "active": active,
        "banned_deleted": banned,
        "flood_error": still_flood,
        "results": results,
    }
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"  FINAL RESULTS")
    print(f"{'='*50}")
    print(f"  Active:        {active}")
    print(f"  Banned/Deleted: {banned}")
    print(f"  Still Flood:   {still_flood}")
    print(f"\n  Saved to: {RESULT_PATH}")

    # Comparison with old results
    print(f"\n{'='*50}")
    print(f"  CHANGES FROM PREVIOUS RUN")
    print(f"{'='*50}")
    for username, result in sorted(results.items()):
        old_status = old_results.get(username, {}).get("status", "unknown")
        new_status = result["status"]
        if old_status != new_status:
            print(f"  @{username}: {old_status} → {new_status}")

    await pool.close()
    await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
