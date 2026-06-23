from __future__ import annotations

import asyncio

from pyrogram.errors import MessageNotModified
from pyrogram.types import Message

from nekofetch.core.constants import BAR_EMPTY, BAR_FILLED


def bar(percent: float, *, width: int = 10) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent / 100 * width)
    return f"{BAR_FILLED * filled}{BAR_EMPTY * (width - filled)} {int(percent)}%"


def labeled(label: str, percent: float, *, width: int = 10) -> str:
    return f"{label}\n\n{bar(percent, width=width)}"


def labeled_html(label: str, percent: float, *, width: int = 10) -> str:
    return (
        f"<blockquote><b>{label}</b>\n\n"
        f"<code>{bar(percent, width=width)}</code></blockquote>"
    )


async def loading_animation(msg: Message, label: str, steps: int = 3, delay: float = 0.35) -> None:
    for i in range(1, steps + 1):
        try:
            await msg.edit_text(f"<code>{label}{'!' * i}</code>", parse_mode="html")
        except MessageNotModified:
            pass
        await asyncio.sleep(delay)


async def staged_loading(msg: Message, stages: list[str], delay_per_stage: float = 0.4) -> None:
    for stage in stages:
        for dots in range(1, 4):
            try:
                await msg.edit_text(f"<code>{stage}{'!' * dots}</code>", parse_mode="html")
            except MessageNotModified:
                pass
            await asyncio.sleep(delay_per_stage / 3)


def queue_block_html(
    *,
    anime_title: str,
    status: str,
    progress: float,
    speed_bps: float,
    eta_seconds: int | None,
    current_episode: int | None = None,
    downloaded_bytes: int = 0,
    total_bytes: int = 0,
    job_id: int | None = None,
) -> str:
    bar_str = bar(progress)
    ep_line = f"\n<b>ᴇᴘɪsᴏᴅᴇ:</b> <code>S{current_episode:02d}</code>" if current_episode else ""
    size_line = ""
    if total_bytes > 0:
        size_line = f"\n<b>sɪᴢᴇ:</b> <code>{human_bytes(downloaded_bytes)} / {human_bytes(total_bytes)}</code>"
    id_line = f"  <code>#{job_id}</code>" if job_id else ""

    return (
        f"<blockquote>"
        f"📥 <b>{anime_title}</b>{id_line}"
        f"{ep_line}\n"
        f"<b>sᴛᴀᴛᴜs:</b> <code>{status}</code>\n"
        f"<b>ᴘʀᴏɢʀᴇss:</b> <code>{bar_str}</code>\n"
        f"<b>sᴘᴇᴇᴅ:</b> <code>{human_speed(speed_bps)}</code>\n"
        f"<b>ᴇᴛᴀ:</b> <code>{human_eta(eta_seconds)}</code>"
        f"{size_line}"
        f"</blockquote>"
    )


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def human_speed(bps: float) -> str:
    return f"{human_bytes(bps)}/s"


def human_eta(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}h {m:02d}m"
    return f"{m:02d}m {s:02d}s"
