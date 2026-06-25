"""One-shot userbot session provisioner.

Run THIS YOURSELF in a terminal (not through the bot) so the interactive prompts
work and your credentials never pass through chat:

    .venv/Scripts/python.exe playground/tg_login.py

It reads TELEGRAM_API_ID / TELEGRAM_API_HASH from .env, logs you in (phone, code,
2FA password if set), prints a session string, and can append it to .env as
TELEGRAM_USERBOT_SESSION. For multiple accounts, run it once per account and put
them in TELEGRAM_USERBOT_ACCOUNTS as a JSON list:

    TELEGRAM_USERBOT_ACCOUNTS=[{"name":"primary","session_string":"..."},
                               {"name":"backup","session_string":"..."}]

The pool auto-selects whichever account is available and falls back if one fails.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

ENV = Path(__file__).parent.parent / ".env"


def load_env() -> dict:
    env: dict = {}
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


async def main() -> None:
    env = load_env()
    try:
        api_id = int(env["TELEGRAM_API_ID"])
        api_hash = env["TELEGRAM_API_HASH"]
    except (KeyError, ValueError):
        print("TELEGRAM_API_ID / TELEGRAM_API_HASH missing from .env")
        return

    from pyrogram import Client

    print("=" * 64)
    print(" NekoFetch — Telegram userbot login")
    print("=" * 64)
    print(" You'll be asked for, in order:")
    print("   1. An account label (just press Enter for 'primary')")
    print("   2. Your phone number WITH country code, e.g. +8801XXXXXXXXX")
    print("   3. Confirm the number (type y)")
    print("   4. The login code Telegram sends to your app")
    print("   5. Your 2-step-verification password (only if you set one)")
    print(" Nothing is shown to anyone else; the session is saved to .env.")
    print("=" * 64)
    name = input("\n1) Account label [primary]: ").strip() or "primary"
    print("   (next, Pyrogram will ask for your phone number + code)\n")
    async with Client(name, api_id=api_id, api_hash=api_hash, in_memory=True) as app:
        session = await app.export_session_string()
        me = await app.get_me()
        print(f"\nLogged in as {me.first_name} (@{me.username}) id={me.id}")
        print("\n=== SESSION STRING (keep secret) ===\n" + session + "\n")

    choice = input(
        "Save to .env?  [1] single TELEGRAM_USERBOT_SESSION  "
        "[2] add to TELEGRAM_USERBOT_ACCOUNTS  [N] skip: "
    ).strip().lower()
    if choice == "1":
        with ENV.open("a", encoding="utf-8") as f:
            f.write(f"\nTELEGRAM_USERBOT_SESSION={session}\n")
        print("Appended TELEGRAM_USERBOT_SESSION to .env")
    elif choice == "2":
        existing = env.get("TELEGRAM_USERBOT_ACCOUNTS", "")
        accounts = json.loads(existing) if existing else []
        accounts.append({"name": name, "session_string": session})
        # rewrite the key in .env
        lines = [ln for ln in ENV.read_text(encoding="utf-8").splitlines()
                 if not ln.startswith("TELEGRAM_USERBOT_ACCOUNTS=")]
        lines.append("TELEGRAM_USERBOT_ACCOUNTS=" + json.dumps(accounts))
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated TELEGRAM_USERBOT_ACCOUNTS ({len(accounts)} account(s))")
    else:
        print("Not saved — add it via your own secure process.")


if __name__ == "__main__":
    asyncio.run(main())
