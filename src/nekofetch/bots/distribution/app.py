from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.infrastructure.database.postgres.models import BotContentPost, DistributionBot
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.localization.messages import M
from nekofetch.services.distribution_service import DistributionService
from nekofetch.ui.components import cb, keyboard, parse_cb
from nekofetch.ui.progress import loading_animation, staged_loading
from nekofetch.ui.typography import bq, bqx

DISTRIBUTION_COMMANDS = [
    BotCommand("start", "Browse the library / open a title"),
    BotCommand("help", "How to download & get access"),
]

# Redis key for per-user last-activity tracking (grace period extension)
_K_USER_LAST_ACTIVITY = "nf:dist:lastact:{bot_id}:{user_id}"


async def publish_distribution_commands(client: Client) -> None:
    await client.set_bot_commands(DISTRIBUTION_COMMANDS)


def build_distribution_bot(
    container: Container, record: DistributionBot, token: str
) -> Client:
    client = Client(
        name=f"nf-dist-{record.id}",
        api_id=container.env.telegram_api_id,
        api_hash=container.env.telegram_api_hash,
        bot_token=token,
        workdir=str(container.env.session_path),
    )
    client.container = container
    client.bot_record = record

    dist = DistributionService(container)
    fsm = FSM(container.redis, bot=f"dist:{record.id}")
    cfg = container.config.distribution
    ui_cfg = container.config.ui

    # ── helpers ────────────────────────────────────────────────────────────────

    async def _load_posts() -> list[BotContentPost]:
        """Load this bot's content posts in order."""
        from sqlalchemy import select

        async with session_scope(container.pg_sessionmaker) as session:
            rows = (
                await session.execute(
                    select(BotContentPost)
                    .where(BotContentPost.bot_id == record.id)
                    .order_by(BotContentPost.order)
                )
            ).scalars().all()
            return list(rows)

    def _build_buttons(post: BotContentPost) -> InlineKeyboardMarkup | None:
        """Build inline keyboard from stored button_data.

        For now, buttons are placeholders — they show the correct layout
        but tapping them shows a 'coming soon' message.
        """
        bd = post.button_data
        if not bd:
            return None

        rows: list[list[InlineKeyboardButton]] = []

        if bd.get("type") == "flat":
            quals = bd.get("qualities", [])
            row = [
                InlineKeyboardButton(
                    q,
                    callback_data=cb("d", "placeholder", q),
                )
                for q in quals
            ]
            if row:
                rows.append(row)

        elif bd.get("type") == "separate_audio":
            sections = bd.get("sections", [])
            for sec in sections:
                # Language label (visual only, arrow pointing down)
                rows.append([
                    InlineKeyboardButton(
                        sec.get("label", "English"),
                        callback_data=cb("d", "nolink"),
                    )
                ])
                # Quality buttons under this language
                qrow = [
                    InlineKeyboardButton(
                        q,
                        callback_data=cb("d", "placeholder", sec.get("language"), q),
                    )
                    for q in sec.get("qualities", [])
                ]
                if qrow:
                    rows.append(qrow)

        # Movie: single download-now button.
        if post.post_type == "movie_card":
            from nekofetch.localization.messages import t as _t
            rows.append([
                InlineKeyboardButton(
                    _t(M.BOT_DOWNLOAD_NOW_BTN),
                    callback_data=cb("d", "placeholder", "download"),
                )
            ])

        return InlineKeyboardMarkup(rows) if rows else None

    async def _send_posts(chat_id: int) -> list[int]:
        """Send all content posts for this bot, with divider stickers between sections."""
        posts = await _load_posts()
        sent_ids: list[int] = []
        divider_id = container.config.bot.divider_sticker_id

        for i, post in enumerate(posts):
            # Divider sticker between major sections (not before the first post).
            if i > 0 and divider_id:
                try:
                    div = await client.send_sticker(chat_id, divider_id)
                    sent_ids.append(div.id)
                except Exception:
                    pass

            markup = _build_buttons(post)
            try:
                if post.image_url:
                    msg = await client.send_photo(
                        chat_id, post.image_url,
                        caption=post.caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    msg = await client.send_message(
                        chat_id, post.caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                    )
                sent_ids.append(msg.id)

                if post.is_pinned:
                    try:
                        await client.pin_chat_message(chat_id, msg.id, disable_notification=True)
                    except Exception:
                        pass
            except Exception as exc:
                from nekofetch.core.logging import get_logger
                get_logger(__name__).warning(
                    "dist.send_post.failed", post_type=post.post_type, error=str(exc)
                )
                continue

        return sent_ids

    async def _track_activity(user_id: int) -> None:
        """Update the user's last activity timestamp (for per-user-with-grace retention)."""
        if container.redis:
            import time
            key = _K_USER_LAST_ACTIVITY.format(bot_id=record.id, user_id=user_id)
            await container.redis.set(key, str(int(time.time())))

    async def _schedule_cleanup(chat_id: int, user_id: int, sent_ids: list[int]) -> None:
        """Schedule auto-delete with per-user grace extension.

        The cleanup checks the user's last-activity timestamp before deleting.
        If they've interacted recently (within half the retention period), the
        cleanup is rescheduled for later.
        """
        scheduler = getattr(container, "scheduler", None)
        if scheduler is None or not sent_ids:
            return
        retention_days = container.config.bot.delivery_retention_days
        if retention_days <= 0:
            return
        retention_secs = retention_days * 86400
        half_retention = retention_secs // 2

        grace_key = _K_USER_LAST_ACTIVITY.format(bot_id=record.id, user_id=user_id)

        async def _delayed_cleanup() -> None:
            import time

            if not container.redis:
                return
            # Check if user has been active recently — extend grace if so.
            raw = await container.redis.get(grace_key)
            if raw:
                try:
                    last_act = int(raw)
                    now = int(time.time())
                    elapsed = now - last_act
                    # If they interacted within the last half-retention period,
                    # reschedule cleanup instead of deleting.
                    if elapsed < half_retention:
                        extend = half_retention + (half_retention - elapsed)
                        new_when = datetime.now(timezone.utc) + timedelta(seconds=extend)
                        scheduler.at(
                            new_when,
                            _delayed_cleanup,
                            id=f"dist-cleanup-{record.id}-{chat_id}-{sent_ids[0]}",
                        )
                        return
                except (ValueError, TypeError):
                    pass

            # Delete the delivered posts.
            try:
                await client.delete_messages(chat_id, sent_ids)
            except Exception:
                pass

        when = datetime.now(timezone.utc) + timedelta(seconds=retention_secs)
        scheduler.at(
            when,
            _delayed_cleanup,
            id=f"dist-cleanup-{record.id}-{chat_id}-{sent_ids[0]}",
        )

    # ── /start ──────────────────────────────────────────────────────────────────

    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        start_sticker = await client.send_sticker(
            chat_id=message.chat.id, sticker=ui_cfg.start_sticker_id
        )

        msg = await message.reply(
            "<b>connecting!</b>", parse_mode=ParseMode.HTML
        )
        await staged_loading(
            msg,
            ["connecting", "checking access", "preparing"],
            delay_per_stage=ui_cfg.loading_dot_delay * 3,
        )

        await asyncio.sleep(ui_cfg.sticker_delete_delay)
        await start_sticker.delete()
        await msg.delete()

        if not await _passes_force_sub(message):
            return

        parts = (message.text or "").split(maxsplit=1)
        payload = parts[1].strip() if len(parts) > 1 else ""

        if payload.startswith("token_"):
            await _redeem(message, payload[len("token_"):])
        if not await _ensure_access(message):
            return

        # Track activity for retention grace period.
        await _track_activity(message.from_user.id)

        # Deliver stored content posts.
        sent_ids = await _send_posts(message.chat.id)
        if sent_ids:
            await _schedule_cleanup(message.chat.id, message.from_user.id, sent_ids)

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        await message.reply(
            f"{bq('<b>how it works</b>')}\n\n"
            f"{bqx('<b>/start</b> — browse the library or open a title\n'
                   '<b>pick</b> a season > resolution > language\n'
                   '<b>tap</b> get season package to receive your files')}",
            parse_mode=ParseMode.HTML,
        )

    async def _bot_username(self_message: Message) -> str | None:
        if record.username:
            return record.username
        try:
            me = await client.get_me()
            return me.username
        except Exception:
            return None

    # ── access ──────────────────────────────────────────────────────────────────

    async def _ensure_access(message: Message) -> bool:
        from nekofetch.services.access_service import AccessService

        status = await AccessService(container).ensure_and_check(
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        if status.has_access:
            return True
        await message.reply(
            f"{bq('<b>access required</b>')}\n\n"
            f"{bq('your access has expired. tap below to get a new access token.')}",
            reply_markup=keyboard([("get access", cb("acc", "get"))]),
            parse_mode=ParseMode.HTML,
        )
        return False

    async def _redeem(message: Message, token: str) -> None:
        from nekofetch.services.access_service import AccessService

        try:
            until = await AccessService(container).redeem(token, message.from_user.id)
            from nekofetch.core.timefmt import to_display
            await message.reply(
                bq(f"access granted until <code>{to_display(until)}</code>."),
                parse_mode=ParseMode.HTML,
            )
        except NekoFetchError as exc:
            await message.reply(
                bq(container.localizer.get(exc.message_key)),
                parse_mode=ParseMode.HTML,
            )

    @client.on_callback_query(filters.regex(r"^acc\|get"))
    async def _get_access(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.access_service import AccessService

        await q.answer()
        username = await _bot_username(q.message)
        if not username:
            await q.message.reply(
                bq("couldn't build an access link right now. try again later."),
                parse_mode=ParseMode.HTML,
            )
            return
        url = await AccessService(container).generate_token(q.from_user.id, bot_username=username)
        days = container.config.access.token_days
        await q.message.reply(
            f"{bq(f'<b>get {days} days access</b>')}\n\n"
f"{bq(f'complete this link, then you\'ll return to the bot '
     f'with access unlocked:\n{url}')}",
            parse_mode=ParseMode.HTML,
        )

    # ── force sub ───────────────────────────────────────────────────────────────

    async def _passes_force_sub(message: Message) -> bool:
        from nekofetch.bots.force_sub import channels_to_join, join_keyboard

        pending = await channels_to_join(
            client, container, message.from_user.id, dist=True
        )
        if not pending:
            return True
        join_msg = "please join the channel(s) below, then tap i ve joined."
        await message.reply(
            f"{bq('<b>join required</b>')}\n\n"
            f"{bq(join_msg)}",
            reply_markup=join_keyboard(pending, retry_callback="fsub|retry"),
            parse_mode=ParseMode.HTML,
        )
        return False

    @client.on_callback_query(filters.regex(r"^fsub\|retry"))
    async def _fsub_retry(_: Client, q: CallbackQuery) -> None:
        from nekofetch.bots.force_sub import channels_to_join

        pending = await channels_to_join(client, container, q.from_user.id, dist=True)
        if pending:
            await q.answer(container.localizer.get(M.DIST_NOT_SUBSCRIBED), show_alert=True)
            return
        await q.answer(container.localizer.get(M.DIST_SUBSCRIBED_THANKS))
        await q.message.delete()
        # Re-send posts after force-sub is resolved.
        sent_ids = await _send_posts(q.message.chat.id)
        if sent_ids:
            await _schedule_cleanup(q.message.chat.id, q.from_user.id, sent_ids)

    # ── placeholder buttons (visual only — no actual download yet) ──────────────

    @client.on_callback_query(filters.regex(r"^d\|placeholder"))
    async def _placeholder(_: Client, q: CallbackQuery) -> None:
        from nekofetch.localization.messages import M as _M, t as _t
        await q.answer(_t(_M.BOT_COMING_SOON), show_alert=True)

    @client.on_callback_query(filters.regex(r"^d\|nolink"))
    async def _nolink(_: Client, q: CallbackQuery) -> None:
        # A language header isn't a link — tapping it previews the instruction to
        # pick a quality from the row beneath it.
        await q.answer(_t(_M.BOT_CHOOSE_QUALITY), show_alert=True)

    return client
