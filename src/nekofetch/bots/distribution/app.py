"""Distribution bot — the public, searchable content library interface.

Flow:

    /start -> (bound title or catalog) -> Season -> Resolution -> Language -> Episodes
           -> Get Season Package -> protected/temporary delivery (+ optional auto-delete)

Navigation context is held in a per-bot Redis FSM so callback data stays compact and
the experience survives restarts. Delivery serves a season *package* (season-centric),
honoring protect_content, temporary_links, and auto_delete from configuration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from nekofetch.bots.fsm import FSM
from nekofetch.core.constants import DIAMOND_FILLED
from nekofetch.core.container import Container
from nekofetch.core.exceptions import NekoFetchError
from nekofetch.domain.enums import AudioType
from nekofetch.infrastructure.database.postgres.models import DistributionBot
from nekofetch.services.distribution_service import DistributionService
from nekofetch.ui.components import cb, keyboard, parse_cb

_AUDIO_LABELS = {
    AudioType.SUBBED.value: "Subbed",
    AudioType.DUBBED.value: "Dubbed",
    AudioType.DUAL_AUDIO.value: "Dual Audio",
}


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
    client.container = container          # type: ignore[attr-defined]
    client.bot_record = record            # type: ignore[attr-defined]

    dist = DistributionService(container)
    fsm = FSM(container.redis, bot=f"dist:{record.id}")
    cfg = container.config.distribution

    # ── entry ──
    @client.on_message(filters.command("start"))
    async def _start(_: Client, message: Message) -> None:
        if not await _passes_force_sub(message):
            return
        if record.anime_doc_id:
            await _show_title(message, record.anime_doc_id)
        else:
            await _show_catalog(message)

    async def _passes_force_sub(message: Message) -> bool:
        from nekofetch.bots.force_sub import channels_to_join, join_keyboard

        pending = await channels_to_join(client, container, message.from_user.id)
        if not pending:
            return True
        await message.reply(
            "**Join Required**\n\nPlease join the channel(s) below, then tap “I've Joined”.",
            reply_markup=join_keyboard(pending, retry_callback="fsub|retry"),
        )
        return False

    @client.on_callback_query(filters.regex(r"^fsub\|retry"))
    async def _fsub_retry(_: Client, q: CallbackQuery) -> None:
        from nekofetch.bots.force_sub import channels_to_join

        pending = await channels_to_join(client, container, q.from_user.id)
        if pending:
            await q.answer("Still not subscribed to all channels.", show_alert=True)
            return
        await q.answer("Thanks!")
        await q.message.delete()
        if record.anime_doc_id:
            await _show_title(q.message, record.anime_doc_id)
        else:
            await _show_catalog(q.message)

    async def _show_catalog(message: Message) -> None:
        titles = await dist.published_titles()
        if not titles:
            await message.reply(f"**{record.name}**\n\nNo content published yet.")
            return
        cache = [{"id": d, "title": t} for d, t in titles]
        await fsm.set(message.from_user.id, "browse", titles=cache)
        rows = [[(t["title"], cb("d", "title", i))] for i, t in enumerate(cache)]
        await message.reply(f"**{record.name}**\n\nChoose a title:", reply_markup=keyboard(*rows))

    @client.on_callback_query(filters.regex(r"^d\|title"))
    async def _title(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        _, data = await fsm.get(q.from_user.id)
        cache = data.get("titles", [])
        idx = int(args[0])
        if idx >= len(cache):
            await q.answer("Unavailable", show_alert=True)
            return
        await q.answer()
        await _show_title(q.message, cache[idx]["id"], edit=True, title=cache[idx]["title"])

    async def _show_title(
        message: Message, anime_doc_id: str, *, edit: bool = False, title: str | None = None
    ) -> None:
        from nekofetch.services.enrichment_service import EnrichmentService

        seasons = await dist.seasons_for(anime_doc_id)
        rows = [[(f"Season {s}", cb("d", "season", s))] for s in seasons] or \
               [[("No published seasons", cb("noop"))]]

        # Preferred path: rich enrichment card. Returns None (and we fall back) until the
        # metadata scraper is implemented — no code here changes when you implement it.
        card = await EnrichmentService(container).render_card(
            anime_doc_id, anime_doc_id=anime_doc_id
        )
        if card is not None:
            await fsm.set(message.from_user.id, "title", doc_id=anime_doc_id,
                          title=_title_from_card(card) or (title or anime_doc_id))
            await _send_card(message, card, keyboard(*rows), edit=edit)
            return

        # Fallback: basic details from the content source (current behaviour).
        details = None
        try:
            source = container.sources.get(container.config.sources.default)
            details = await source.get_details(anime_doc_id)
        except NekoFetchError:
            pass
        await fsm.set(message.from_user.id, "title", doc_id=anime_doc_id,
                      title=(details.title if details else (title or anime_doc_id)))

        header = details.title if details else (title or anime_doc_id)
        body = [f"**{header}**"]
        if details and details.synopsis:
            body.append(details.synopsis[:400])
        if details and details.genres:
            body.append("Genres: " + ", ".join(details.genres))
        body.append(f"Seasons: {len(seasons)}")
        text = "\n\n".join(body)
        if edit:
            await message.edit_text(text, reply_markup=keyboard(*rows))
        else:
            await message.reply(text, reply_markup=keyboard(*rows))

    def _title_from_card(card) -> str | None:
        # The card caption's first line is "**Title**"; cheap to recover for FSM state.
        first = card.caption.splitlines()[0] if card.caption else ""
        return first.strip("* ") or None

    async def _send_card(message: Message, card, markup, *, edit: bool) -> None:
        """Render the enrichment card; attach the header image when one is available."""
        if card.image_url:
            # Replace the message with a photo card (edit can't switch text->photo).
            try:
                await message.reply_photo(card.image_url, caption=card.caption, reply_markup=markup)
                return
            except Exception:  # noqa: BLE001 - bad/unreachable image URL: fall back to text
                pass
        if edit:
            await message.edit_text(card.caption, reply_markup=markup)
        else:
            await message.reply(card.caption, reply_markup=markup)

    @client.on_callback_query(filters.regex(r"^d\|season"))
    async def _season(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        season = int(args[0])
        _, data = await fsm.get(q.from_user.id)
        doc_id = data.get("doc_id")
        variants = await dist.variants_for(doc_id, season)
        resolutions = sorted({r for r, _ in variants})
        await fsm.update(q.from_user.id, season=season, variants=variants)
        await q.answer()
        rows = [[(res, cb("d", "res", res))] for res in resolutions] or \
               [[("No resolutions", cb("noop"))]]
        await q.message.edit_text(
            f"**{container.localizer.get('choose_resolution')}**\n\nSeason {season}",
            reply_markup=keyboard(*rows),
        )

    @client.on_callback_query(filters.regex(r"^d\|res"))
    async def _resolution(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        res = args[0]
        _, data = await fsm.get(q.from_user.id)
        audios = sorted({a for r, a in data.get("variants", []) if r == res})
        await fsm.update(q.from_user.id, resolution=res)
        await q.answer()
        rows = [[(_AUDIO_LABELS.get(a, a.title()), cb("d", "lang", a))] for a in audios] or \
               [[("No languages", cb("noop"))]]
        await q.message.edit_text(
            f"**{container.localizer.get('choose_language')}**\n\n{res}",
            reply_markup=keyboard(*rows),
        )

    @client.on_callback_query(filters.regex(r"^d\|lang"))
    async def _language(_: Client, q: CallbackQuery) -> None:
        _, args = parse_cb(q.data)
        audio = args[0]
        await fsm.update(q.from_user.id, audio=audio)
        _, data = await fsm.get(q.from_user.id)
        await q.answer()
        try:
            pkg = await dist.build_season_package(
                data["doc_id"], data["season"],
                resolution=data.get("resolution"), audio=AudioType(audio),
            )
        except NekoFetchError as exc:
            await q.message.edit_text(container.localizer.get(exc.message_key))
            return
        span = f"{pkg.episode_span[0]}-{pkg.episode_span[1]}" if pkg.episode_span else "—"
        await q.message.edit_text(
            f"**{data['title']}**\n\n"
            f"{DIAMOND_FILLED} Season {pkg.season}\n"
            f"{DIAMOND_FILLED} Episodes: {span}\n"
            f"{DIAMOND_FILLED} Resolution: {data.get('resolution')}\n"
            f"{DIAMOND_FILLED} Language: {_AUDIO_LABELS.get(audio, audio)}\n"
            f"{DIAMOND_FILLED} Files: {len(pkg.file_ids)}",
            reply_markup=keyboard([("➜ Get Season Package", cb("d", "pkg"))]),
        )

    @client.on_callback_query(filters.regex(r"^d\|pkg"))
    async def _deliver(_: Client, q: CallbackQuery) -> None:
        from nekofetch.services.log_channel_service import LogChannelService
        from nekofetch.services.storage_channel_service import StorageChannelService

        _, data = await fsm.get(q.from_user.id)
        await q.answer()
        audio = AudioType(data["audio"]) if data.get("audio") else None
        try:
            pkg = await dist.build_season_package(
                data["doc_id"], data["season"], resolution=data.get("resolution"), audio=audio
            )
        except NekoFetchError as exc:
            await q.message.edit_text(container.localizer.get(exc.message_key))
            return

        storage = StorageChannelService(container)
        logsvc = LogChannelService(container)
        delivered_ids: list[int] = []

        # Primary path: copy the database-channel pack (the season package) to the user.
        pack = None
        if container.config.storage_channel.enabled and data.get("resolution") and audio:
            pack = await storage.find_pack(
                storage.key_from(data["doc_id"], data["season"], data["resolution"], audio)
            )
        if pack is not None:
            await q.message.reply(
                f"**Season Package**\n\n{data['title']} — Season {pkg.season}\n"
                f"{pack.file_count} files | {data.get('resolution')} | "
                f"{_AUDIO_LABELS.get(data.get('audio'), data.get('audio'))}"
            )
            delivered_ids = await storage.deliver(pack, q.message.chat.id)
        else:
            # Fallback: temporary access token (no pack stored / storage channel disabled).
            link = await dist.create_access_link(pkg, user_id=q.from_user.id)
            expiry_note = (
                f"\n\nThis access expires in {cfg.link_expiry_minutes} minutes."
                if link.expires_at else ""
            )
            sent = await client.send_message(
                q.message.chat.id,
                f"**Season Package Ready**\n\n{data['title']} — Season {pkg.season}\n"
                f"{len(pkg.file_ids)} files | {data.get('resolution')} | "
                f"{_AUDIO_LABELS.get(data.get('audio'), data.get('audio'))}\n"
                f"Access token: `{link.token}`{expiry_note}",
                protect_content=cfg.protect_content,
            )
            delivered_ids = [sent.id]

        await logsvc.event(
            "delivery", "season_package", bot=record.name, user=q.from_user.id,
            anime=data["title"], season=data.get("season"),
            resolution=data.get("resolution"), language=data.get("audio"),
            files=(pack.file_count if pack else len(pkg.file_ids)),
        )

        # Optional auto-delete of everything delivered.
        scheduler = getattr(container, "scheduler", None)
        if cfg.auto_delete and container.config.features.auto_delete and scheduler is not None and delivered_ids:
            when = datetime.now(timezone.utc) + timedelta(minutes=cfg.auto_delete_after_minutes)

            async def _del(chat_id=q.message.chat.id, ids=list(delivered_ids)) -> None:
                try:
                    await client.delete_messages(chat_id, ids)
                except Exception:  # noqa: BLE001
                    pass

            scheduler.at(when, _del, id=f"autodel-{record.id}-{q.from_user.id}-{delivered_ids[0]}")

    return client
