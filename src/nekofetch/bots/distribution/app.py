from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import BotCommand, CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import AudioType
from nekofetch.infrastructure.database.postgres.models import DistributionBot
from nekofetch.services.distribution_service import DistributionService
from nekofetch.ui.components import cb, keyboard, parse_cb
from nekofetch.ui.progress import loading_animation, staged_loading
from nekofetch.ui.typography import bq, bqx

_AUDIO_LABELS = {
    AudioType.SUBBED.value: "subbed",
    AudioType.DUBBED.value: "dubbed",
    AudioType.DUAL_AUDIO.value: "dual audio",
}

DISTRIBUTION_COMMANDS = [
    BotCommand("start", "Browse the library / open a title"),
    BotCommand("help", "How to download & get access"),
]


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
        if payload.startswith("anime_"):
            await _show_title(message, payload[len("anime_"):])
            return
        if record.anime_doc_id:
            await _show_title(message, record.anime_doc_id)
        else:
            await _show_catalog(message)

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        await message.reply(
            f"{bq('<b>how it works</b>')}\n\n"
            f"{bqx('<b>◆ /start</b> — browse the library or open a title\n'
                   '<b>◆</b> pick a season → resolution → language\n'
                   '<b>◆</b> tap get season package to receive your files')}",
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
            reply_markup=keyboard([("➜ get access", cb("acc", "get"))]),
            parse_mode=ParseMode.HTML,
        )
        return False

    async def _redeem(message: Message, token: str) -> None:
        from nekofetch.services.access_service import AccessService

        try:
            until = await AccessService(container).redeem(token, message.from_user.id)
            await message.reply(
                bq(f"✓ access granted until <code>{until:%Y-%m-%d %H:%M} UTC</code>."),
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
                 f'with access unlocked:\\n{url}')}",
            parse_mode=ParseMode.HTML,
        )

    async def _passes_force_sub(message: Message) -> bool:
        from nekofetch.bots.force_sub import channels_to_join, join_keyboard

        pending = await channels_to_join(client, container, message.from_user.id)
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

        pending = await channels_to_join(client, container, q.from_user.id)
        if pending:
            await q.answer("still not subscribed to all channels.", show_alert=True)
            return
        await q.answer("thanks!")
        await q.message.delete()
        if record.anime_doc_id:
            await _show_title(q.message, record.anime_doc_id)
        else:
            await _show_catalog(q.message)

    async def _show_catalog(message: Message) -> None:
        msg = await message.reply(
            "<b>loading catalog!</b>", parse_mode=ParseMode.HTML
        )
        await loading_animation(msg, "loading catalog")
        titles = await dist.published_titles()
        if not titles:
            await msg.edit_text(
                f"{bq(f'<b>{record.name}</b>')}\n\n{bq('no content published yet.')}",
                parse_mode=ParseMode.HTML,
            )
            return
        cache = [{"id": d, "title": t} for d, t in titles]
        await fsm.set(message.from_user.id, "browse", titles=cache)
        rows = [[(t["title"], cb("d", "title", i))] for i, t in enumerate(cache)]
        await msg.edit_text(
            f"{bq(f'<b>{record.name}</b>')}\n\n{bq('choose a title:')}",
            reply_markup=keyboard(*rows),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^d\|title"))
    async def _title(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        _, data = await fsm.get(q.from_user.id)
        cache = data.get("titles", [])
        idx = int(args[1])
        if idx >= len(cache):
            await q.answer("unavailable", show_alert=True)
            return
        await q.answer()
        await _show_title(q.message, cache[idx]["id"], edit=True, title=cache[idx]["title"])

    async def _show_title(
        message: Message, anime_doc_id: str, *, edit: bool = False, title: str | None = None
    ) -> None:
        from nekofetch.services.enrichment_service import EnrichmentService

        msg = message
        if edit:
            await loading_animation(msg, "loading anime")
        else:
            msg = await message.reply(
                "<b>loading anime!</b>", parse_mode=ParseMode.HTML
            )
            await loading_animation(msg, "loading anime")

        seasons = await dist.seasons_for(anime_doc_id)
        rows = [[(f"season {s}", cb("d", "season", s))] for s in seasons] or \
               [[("no published seasons", cb("noop"))]]

        card = await EnrichmentService(container).render_card(
            anime_doc_id, anime_doc_id=anime_doc_id
        )
        if card is not None:
            await fsm.set(message.from_user.id, "title", doc_id=anime_doc_id,
                          title=_title_from_card(card) or (title or anime_doc_id))
            await _send_card(message, card, keyboard(*rows), edit=edit)
            return

        details = None
        try:
            source = container.sources.get(container.config.sources.default)
            details = await source.get_details(anime_doc_id)
        except NekoFetchError:
            pass
        await fsm.set(message.from_user.id, "title", doc_id=anime_doc_id,
                      title=(details.title if details else (title or anime_doc_id)))

        header = details.title if details else (title or anime_doc_id)
        body = [f"{bq(f'<b>{header}</b>')}"]
        if details and details.synopsis:
            body.append(details.synopsis[:400])
        if details and details.genres:
            body.append(f"<b>genres:</b> {', '.join(details.genres)}")
        body.append(f"<b>seasons:</b> {len(seasons)}")
        text = "\n\n".join(body)
        if edit:
            await msg.edit_text(text, reply_markup=keyboard(*rows), parse_mode=ParseMode.HTML)
        else:
            await msg.edit_text(text, reply_markup=keyboard(*rows), parse_mode=ParseMode.HTML)

    def _title_from_card(card) -> str | None:
        first = card.caption.splitlines()[0] if card.caption else ""
        return first.strip("* ") or None

    async def _send_card(message: Message, card, markup, *, edit: bool) -> None:
        if card.image_url:
            try:
                await message.reply_photo(card.image_url, caption=card.caption, reply_markup=markup)
                return
            except Exception:
                pass
        if edit:
            await message.edit_text(card.caption, reply_markup=markup, parse_mode=ParseMode.HTML)
        else:
            await message.reply(card.caption, reply_markup=markup, parse_mode=ParseMode.HTML)

    @client.on_callback_query(filters.regex(r"^d\|season"))
    async def _season(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        season = int(args[1])
        _, data = await fsm.get(q.from_user.id)
        doc_id = data.get("doc_id")
        await loading_animation(q.message, "retrieving seasons")
        variants = await dist.variants_for(doc_id, season)
        resolutions = sorted({r for r, _ in variants})
        await fsm.update(q.from_user.id, season=season, variants=variants)
        await q.answer()
        rows = [[(res, cb("d", "res", res))] for res in resolutions] or \
               [[("no resolutions", cb("noop"))]]
        cr = container.localizer.get("choose_resolution")
        await q.message.edit_text(
            f"{bq(f'<b>{cr}</b>')}\n\n"
            f"{bq(f'season {season}')}",
            reply_markup=keyboard(*rows),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^d\|res"))
    async def _resolution(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        res = args[1]
        _, data = await fsm.get(q.from_user.id)
        audios = sorted({a for r, a in data.get("variants", []) if r == res})
        await fsm.update(q.from_user.id, resolution=res)
        await q.answer()
        rows = [[(_AUDIO_LABELS.get(a, a.title()), cb("d", "lang", a))] for a in audios] or \
               [[("no languages", cb("noop"))]]
        cl = container.localizer.get("choose_language")
        await q.message.edit_text(
            f"{bq(f'<b>{cl}</b>')}\n\n"
            f"{bq(res)}",
            reply_markup=keyboard(*rows),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^d\|lang"))
    async def _language(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        audio = args[1]
        await fsm.update(q.from_user.id, audio=audio)
        _, data = await fsm.get(q.from_user.id)
        await q.answer()
        try:
            pkg = await dist.build_season_package(
                data["doc_id"], data["season"],
                resolution=data.get("resolution"), audio=AudioType(audio),
            )
        except NekoFetchError as exc:
            await q.message.edit_text(
                bq(container.localizer.get(exc.message_key)),
                parse_mode=ParseMode.HTML,
            )
            return
        span = f"{pkg.episode_span[0]}-{pkg.episode_span[1]}" if pkg.episode_span else "—"
        title = data["title"]
        res = data.get("resolution")
        aud_label = _AUDIO_LABELS.get(audio, audio)
        await q.message.edit_text(
            f"{bq(f'<b>{title}</b>')}\n\n"
            f"{bqx(f'<b>◆ season:</b> <code>{pkg.season}</code>\n'
                   f'<b>◆ episodes:</b> {span}\n'
                   f'<b>◆ resolution:</b> <code>{res}</code>\n'
                   f'<b>◆ language:</b> {aud_label}\n'
                   f'<b>◆ files:</b> {len(pkg.file_ids)}')}",
            reply_markup=keyboard([("📦 get season package", cb("d", "pkg"))]),
            parse_mode=ParseMode.HTML,
        )

    @client.on_callback_query(filters.regex(r"^d\|pkg"))
    async def _deliver(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.access_service import AccessService
        from nekofetch.services.log_channel_service import LogChannelService
        from nekofetch.services.storage_channel_service import StorageChannelService

        await loading_animation(q.message, "preparing package")

        if not await AccessService(container).has_access(q.from_user.id):
            await q.answer()
            await q.message.reply(
                f"{bq('<b>access required</b>')}\n\n"
                f"{bq('get an access token to download.')}",
                reply_markup=keyboard([("➜ get access", cb("acc", "get"))]),
                parse_mode=ParseMode.HTML,
            )
            return

        _, data = await fsm.get(q.from_user.id)
        await q.answer()
        audio = AudioType(data["audio"]) if data.get("audio") else None
        try:
            pkg = await dist.build_season_package(
                data["doc_id"], data["season"], resolution=data.get("resolution"), audio=audio
            )
        except NekoFetchError as exc:
            await q.message.edit_text(
                bq(container.localizer.get(exc.message_key)),
                parse_mode=ParseMode.HTML,
            )
            return

        storage = StorageChannelService(container)
        logsvc = LogChannelService(container)
        delivered_ids: list[int] = []

        pack = None
        if container.config.storage_channel.enabled and data.get("resolution") and audio:
            pack = await storage.find_pack(
                storage.key_from(data["doc_id"], data["season"], data["resolution"], audio)
            )
        title = data["title"]
        res = data.get("resolution")
        audio_val = data.get("audio")
        if pack is not None:
            await q.message.reply(
                f"{bq(f'<b>{title}</b>')}\n\n"
                f"{bq(f'season {pkg.season} — {pack.file_count} files '
                     f'| {res} | {_AUDIO_LABELS.get(audio_val, audio_val)}')}",
                parse_mode=ParseMode.HTML,
            )
            await loading_animation(q.message, "sending")
            delivered_ids = await storage.deliver(pack, q.message.chat.id)
        else:
            link = await dist.create_access_link(pkg, user_id=q.from_user.id)
            expiry_note = (
                f"\n\nthis access expires in {cfg.link_expiry_minutes} minutes."
                if link.expires_at else ""
            )
            sent = await client.send_message(
                q.message.chat.id,
                f"{bq(f'<b>{title}</b>')}\n\n"
                f"{bq(f'season {pkg.season} — {len(pkg.file_ids)} files '
                     f'| {res} | {_AUDIO_LABELS.get(audio_val, audio_val)}')}\n"
                f"{bq(f'access token: <code>{link.token}</code>{expiry_note}')}",
                protect_content=cfg.protect_content,
                parse_mode=ParseMode.HTML,
            )
            delivered_ids = [sent.id]

        await logsvc.event(
            "delivery", "season_package", bot=record.name, user=q.from_user.id,
            anime=data["title"], season=data.get("season"),
            resolution=data.get("resolution"), language=data.get("audio"),
            files=(pack.file_count if pack else len(pkg.file_ids)),
        )

        scheduler = getattr(container, "scheduler", None)
        auto_delete_on = (
            cfg.auto_delete and container.config.features.auto_delete
            and scheduler is not None and delivered_ids
        )
        if auto_delete_on or container.config.access.forward_to_saved_hint:
            hint_parts = [bq("forward these files to your <b>saved messages</b> to keep them.")]
            if auto_delete_on:
                hint_parts.append(
                    bq(f"they'll be auto-deleted here in "
                       f"{cfg.auto_delete_after_minutes} minutes.")
                )
            await q.message.reply(
                "\n\n".join(hint_parts),
                parse_mode=ParseMode.HTML,
            )

        if auto_delete_on:
            when = datetime.now(timezone.utc) + timedelta(minutes=cfg.auto_delete_after_minutes)

            async def _del(chat_id=q.message.chat.id, ids=list(delivered_ids)) -> None:
                try:
                    await client.delete_messages(chat_id, ids)
                except Exception:
                    pass

            scheduler.at(when, _del, id=f"autodel-{record.id}-{q.from_user.id}-{delivered_ids[0]}")

    return client
