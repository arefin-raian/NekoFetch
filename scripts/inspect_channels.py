"""Dump the structure of reference channels via the userbot session.

I can't open your Telegram channels from the dev environment, so run this with your
userbot session and paste the output back — it shows each channel's pinned message,
recent messages, inline-button layouts, and media types, which is what I need to
mirror the watch-guide / season-structure / button formats.

    python scripts/inspect_channels.py @haikyu_ani_weebs -2207914188 @rent_a_girlfriend_aw

Pass channel @usernames or numeric ids (the ones from your message). With no args it
uses the built-in reference list.
"""

from __future__ import annotations

import asyncio
import sys

from nekofetch.core.container import Container

_DEFAULT = [
    "@haikyu_ani_weebs", "@Link_click_ani_weebs", "@komi_cant_communicate_ani_weebs",
    "@jojo_bizzare_adventure_ani_weebs", "@assasination_clsroom", "@rent_a_girlfriend_aw",
]


def _btns(msg) -> str:
    kb = getattr(msg, "reply_markup", None)
    rows = getattr(kb, "inline_keyboard", None)
    if not rows:
        return ""
    out = []
    for row in rows:
        out.append(" | ".join(
            f"[{b.text}{'→url' if getattr(b, 'url', None) else ''}]" for b in row
        ))
    return "\n        buttons: " + " / ".join(out)


def _kind(msg) -> str:
    for k in ("photo", "video", "document", "sticker", "animation", "audio"):
        if getattr(msg, k, None):
            return k
    return "text"


async def dump(client, ref: str) -> None:
    print(f"\n{'='*70}\nCHANNEL: {ref}")
    try:
        chat = await client.get_chat(ref)
        print(f"  title={chat.title!r}  type={chat.type}  members={getattr(chat,'members_count','?')}")
        if getattr(chat, "pinned_message", None):
            pm = chat.pinned_message
            print(f"  PINNED: {(pm.text or pm.caption or '')[:300]!r}{_btns(pm)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR opening {ref}: {exc}")
        return
    try:
        n = 0
        async for msg in client.get_chat_history(ref, limit=12):
            body = (msg.text or msg.caption or "").replace("\n", "\\n")[:400]
            print(f"  --- msg {msg.id} [{_kind(msg)}]\n        {body!r}{_btns(msg)}")
            n += 1
        if not n:
            print("  (no readable history — not a member?)")
    except Exception as exc:  # noqa: BLE001
        print(f"  history error: {exc}")


async def main(refs: list[str]) -> None:
    container = Container.create()
    await container.startup()
    from nekofetch.sources.telegram.userbot import UserbotPool

    pool = UserbotPool.from_env(container.env.telegram_api_id,
                                container.env.telegram_api_hash,
                                str(container.env.session_path))
    try:
        client = await pool.acquire()
        for ref in refs:
            await dump(client, ref)
    finally:
        await pool.close()
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or _DEFAULT))
