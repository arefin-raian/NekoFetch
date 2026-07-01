"""Human-readable documentation for every configurable field.

The Settings panel uses this so an admin never has to read source code to know
what a setting does, what values are valid, or which variables a template
supports. Keyed by ``"<section>.<field>"``. Fields without an entry fall back to
a description derived from their name + current type.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldDoc:
    desc: str                                   # what the setting does
    options: tuple[str, ...] = ()               # valid values (enum-like fields)
    placeholders: dict[str, str] = field(default_factory=dict)  # template vars
    example: str | None = None                  # a sample value
    html: bool = False                          # template supports HTML


# ── shared placeholder sets ──
_PACK = {
    "{title}": "anime title", "{season}": "season number",
    "{resolution}": "e.g. 1080p", "{language}": "Sub / Dub / Dual",
    "{episode_from}": "first episode no.", "{episode_to}": "last episode no.",
    "{group}": "release/brand group",
}
_RENAME = {
    "{title}": "anime title", "{season}": "season no.", "{episode}": "episode no.",
    "{resolution}": "e.g. 1080p", "{audio}": "Sub / Dub / Dual", "{group}": "brand tag",
}
_MAIN = {
    "{title}": "anime title", "{tag}": "hashtag-safe title", "{episodes}": "episode count",
    "{qualities}": "available resolutions", "{languages}": "available audio",
    "{genres}": "genre list", "{overview}": "synopsis",
}


FIELD_DOCS: dict[str, FieldDoc] = {
    # ── storage channel ──
    "storage_channel.header_template": FieldDoc(
        desc="Header posted above each storage pack.",
        placeholders=_PACK, html=True,
        example="{title} — Season {season} [{resolution}] [{language}]"),
    "storage_channel.copy_mode": FieldDoc(
        desc="How files are delivered to users from the storage channel.",
        options=("copy", "forward"),
        example="copy  (copy = clean, no 'forwarded from' tag; forward = keeps source tag)"),
    "storage_channel.include_header_in_delivery": FieldDoc(
        desc="Include the pack header message when delivering to a user."),
    "storage_channel.include_sticker_in_delivery": FieldDoc(
        desc="Include the end-of-pack sticker when delivering to a user."),

    # ── rename / metadata ──
    "rename.template": FieldDoc(
        desc="Filename pattern applied to every processed episode.",
        placeholders=_RENAME,
        example="{title} S{season}E{episode} [{resolution}] [{audio}] - {group}"),
    "metadata.supported_containers": FieldDoc(
        desc="Container extensions metadata editing applies to (comma-separated).",
        example="mkv, mp4, avi, mov"),

    # ── distribution / publishing ──
    "distribution.mode": FieldDoc(
        desc="How published content is packaged for delivery.",
        options=("season_package", "single_file"),
        example="season_package  (one pack per season) vs single_file (per episode)"),
    "distribution.link_expiry_minutes": FieldDoc(
        desc="Minutes a generated access link stays valid.", example="60"),
    "distribution.auto_delete_after_minutes": FieldDoc(
        desc="Delete delivered files from the user's chat after N minutes (0 = never).",
        example="60"),

    # ── main channel ──
    "main_channel.caption_template": FieldDoc(
        desc="Caption for each anime posted to the public main channel.",
        placeholders=_MAIN, html=True,
        example="{title}『 #{tag} 』\\n⌬ EPISODES : {episodes}"),
    "main_channel.index_button_text": FieldDoc(
        desc="Label of the Index button (small caps Unicode supported).", example="ɪɴᴅᴇx"),
    "main_channel.download_button_text": FieldDoc(
        desc="Label of the Download button (small caps Unicode supported).", example="ᴅᴏᴡɴʟᴏᴀᴅ"),

    # ── index channel ──
    "index_channel.letter_header_template": FieldDoc(
        desc="Header rendered for each first-letter index post.",
        placeholders={"{letter}": "the index letter", "{entries}": "titles under it"},
        html=True, example="•──────• {letter} •──────•"),
    "index_channel.entry_template": FieldDoc(
        desc="One catalog line per title in the index.",
        placeholders={"{title}": "anime title"}, html=True, example="⦿ {title}"),

    # ── branding ──
    "branding.channel_name": FieldDoc(
        desc="Your brand/channel name shown in cards.", example="Anime Weebs"),
    "branding.footer_text": FieldDoc(desc="Footer line appended to posts.", example="Anime Weebs"),
    "branding.watermark_text": FieldDoc(
        desc="Subtitle watermark text inserted into releases.", example="@AniXWeebs"),
    "branding.metadata_author": FieldDoc(
        desc="Author tag written into file metadata.", example="Anime Weebs"),

    # ── watermark ──
    "watermark.type": FieldDoc(desc="Watermark kind.", options=("text", "image")),
    "watermark.corner": FieldDoc(
        desc="Where the watermark sits on the frame.",
        options=("bottom_right", "bottom_left", "top_right", "top_left")),
    "watermark.opacity": FieldDoc(desc="Watermark opacity, 0.0–1.0.", example="0.6"),
    "watermark.scale": FieldDoc(
        desc="Watermark size as a fraction of frame width.", example="0.12"),

    # ── sources ──
    "sources.enabled": FieldDoc(
        desc="Active download sources (comma-separated, order = priority).",
        options=("local", "telegram", "anikoto", "kickassanime", "nyaa"),
        example="local, telegram, anikoto, kickassanime, nyaa"),
    "sources.default": FieldDoc(
        desc="Fallback source when an assignment can't be resolved.",
        options=("local", "telegram", "anikoto", "kickassanime", "nyaa"), example="telegram"),

    # ── acquisition ──
    "acquisition.resolutions": FieldDoc(
        desc="Resolutions to fetch when a request pins none (comma-separated).",
        example="360p, 540p, 720p, 1080p"),
    "acquisition.languages": FieldDoc(
        desc="Audio tracks to fetch when unspecified. english→Dub, japanese→Sub.",
        options=("english", "japanese", "hindi"), example="english, japanese"),

    # ── security / force-sub ──
    "security.force_subscribe": FieldDoc(
        desc="Require users to join channels before using the NekoFetch admin bot."),
    "security.force_subscribe_channels": FieldDoc(
        desc="Channel IDs users must join for admin bot (comma-separated -100… ids).",
        example="-1001234567890, -1009876543210"),
    "security.dist_force_subscribe": FieldDoc(
        desc="Require users to join channels before using distribution bots (separate from admin)."),
    "security.dist_force_subscribe_channels": FieldDoc(
        desc="Channel IDs users must join for distribution bots (comma-separated -100… ids).",
        example="-1001234567890, -1009876543210"),
    "security.rate_limit_per_minute": FieldDoc(
        desc="Max actions per user per minute.", example="20"),

    # ── bot / distribution bots ──
    "bot.auto_create_on_publish": FieldDoc(
        desc="Auto-create a distribution bot when content is published."),
    "bot.avatar_source": FieldDoc(
        desc="Which poster rank to use for the bot's profile photo.",
        options=("tmdb_rank1", "tmdb_rank0", "anilist_cover"),
        example="tmdb_rank1  (rank=1 = different from file thumbnail)"),
    "bot.delivery_retention_days": FieldDoc(
        desc="Days before bot-delivered messages auto-delete per user (0 = never).",
        example="7"),
    "bot.health_check_interval_minutes": FieldDoc(
        desc="Minutes between bot ban-detection health checks (0 = disabled).",
        example="60"),
    "bot.footer_image_url": FieldDoc(
        desc="Image shown on the footer post of every distribution bot. URL or Telegram file_id; empty = no image.",
        example="https://files.catbox.moe/example.png"),
    "bot.footer_text": FieldDoc(
        desc="Override the built-in footer text (empty = use the en.json template). Unicode small-caps and special characters are supported.",
        example="ANIME WEEBS — feel the story, live the art"),
    "bot.divider_sticker_id": FieldDoc(
        desc="Sticker sent between content sections (info → seasons → guide → footer). Telegram file_id; empty = no dividers.",
        example="CAACAgUAAxkBAAI5pmpE1uh9_sD-z2tYJ3wlado6vS29AAIY..."),

    # ── access / shortlink ──
    "access.trial_days": FieldDoc(desc="Free-trial length in days.", example="3"),
    "access.token_days": FieldDoc(desc="How many days a renewed token grants.", example="3"),
    "shortlink.provider": FieldDoc(
        desc="URL shortener used to gate tokens.", options=("linkvertise",)),

    # ── log channel ──
    "log_channel.cover_image": FieldDoc(
        desc="Cover image (URL or file_id) atop the control center. Empty = none.",
        example="https://example.com/cover.png"),
    "log_channel.discussion_ttl_minutes": FieldDoc(
        desc="Idle minutes before staff chatter in the log channel is auto-deleted.",
        example="5"),
}


# Sensitive config — infrastructure ids, credentials, security, sources. Only the
# owner may view or change these; non-owner admins get the operational sections.
OWNER_ONLY_SECTIONS = frozenset({
    "security", "sources", "access", "shortlink",
    "storage_channel", "log_channel", "main_channel", "index_channel",
    "bot",
})


def doc_for(section: str, field_name: str) -> FieldDoc | None:
    return FIELD_DOCS.get(f"{section}.{field_name}")


def is_owner_only(section: str) -> bool:
    return section in OWNER_ONLY_SECTIONS
