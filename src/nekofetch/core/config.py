"""Configuration system.

Three layers, in increasing precedence:

1. ``.env`` / environment  -> secrets & connection strings  (``EnvSettings``)
2. ``config.yaml``         -> feature toggles & behaviour    (``AppConfig``)
3. MongoDB ``settings``    -> runtime overrides from the admin panel
                              (applied by ``ConfigService``, see services layer)

``EnvSettings`` and ``AppConfig`` are immutable, typed snapshots loaded at startup.
Runtime overrides are layered on read so the admin can change behaviour without a
restart — see ``nekofetch.services.config_service.ConfigService``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — secrets & connection strings (.env)
# ─────────────────────────────────────────────────────────────────────────────
class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    telegram_api_id: int = Field(..., alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(..., alias="TELEGRAM_API_HASH")
    admin_bot_token: str = Field(..., alias="ADMIN_BOT_TOKEN")
    admin_ids: list[int] = Field(default_factory=list, alias="ADMIN_IDS")

    # Security
    secret_key: str = Field(..., alias="SECRET_KEY")

    # PostgreSQL
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_user: str = Field("nekofetch", alias="POSTGRES_USER")
    postgres_password: str = Field("change-me", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("nekofetch", alias="POSTGRES_DB")

    # MongoDB
    mongo_uri: str = Field("mongodb://mongo:27017", alias="MONGO_URI")
    mongo_db: str = Field("nekofetch", alias="MONGO_DB")

    # Redis
    redis_url: str = Field("redis://redis:6379/0", alias="REDIS_URL")

    # Storage
    storage_path: Path = Field(Path("/data/storage"), alias="STORAGE_PATH")
    session_path: Path = Field(Path("/data/sessions"), alias="SESSION_PATH")

    # TMDB
    tmdb_read_access_token: str = Field("", alias="TMDB_API_READ_ACCESS_TOKEN")
    tmdb_api_key: str = Field("", alias="TMDB_API_KEY")

    # Logging
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    log_json: bool = Field(False, alias="LOG_JSON")

    # Schema management: True auto-creates tables on startup (dev convenience).
    # Set False in production and manage the schema with Alembic migrations.
    auto_create_schema: bool = Field(True, alias="AUTO_CREATE_SCHEMA")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, v: Any) -> Any:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(x) for x in v.replace(" ", "").split(",") if x]
        return v

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            f"?ssl=require"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — feature toggles & behaviour (config.yaml)
# Each section mirrors a block in config.yaml. Defaults make the file optional.
# ─────────────────────────────────────────────────────────────────────────────
class Features(BaseModel):
    request_system: bool = True
    download_queue: bool = True
    distribution_bots: bool = True
    watermarking: bool = False
    metadata_editing: bool = True
    thumbnail_generation: bool = True
    auto_delete: bool = False
    temporary_links: bool = True
    analytics: bool = True
    audit_logs: bool = True


class DownloadsConfig(BaseModel):
    concurrent_downloads: int = 5
    retry_attempts: int = 3
    retry_backoff_seconds: int = 10
    resume_interrupted: bool = True
    chunk_size_kb: int = 1024
    progress_update_interval_seconds: int = 3


class ProcessingConfig(BaseModel):
    verify_files: bool = True
    rename: bool = True
    metadata: bool = True
    branding: bool = True
    thumbnail: bool = True
    require_approval_before_publish: bool = True


class RenameConfig(BaseModel):
    enabled: bool = True
    template: str = "{title} S{season}E{episode} [{resolution}] [{audio}] - {group}"


class MetadataConfig(BaseModel):
    enabled: bool = True
    update_title: bool = True
    update_author: bool = True
    update_comment: bool = True
    update_tags: bool = True
    update_description: bool = True
    supported_containers: list[str] = Field(default_factory=lambda: ["mkv", "mp4", "avi", "mov"])


class ThumbnailConfig(BaseModel):
    enabled: bool = True
    attach_to_video: bool = True
    attach_to_document: bool = True
    generate_previews: bool = True


class WatermarkConfig(BaseModel):
    enabled: bool = False
    type: str = "text"
    text: str = "Anime Weebs"
    image_path: str = ""
    corner: str = "bottom_right"
    opacity: float = 0.6
    scale: float = 0.12


class BrandingConfig(BaseModel):
    enabled: bool = True
    channel_name: str = "Anime Weebs"
    footer_text: str = "Anime Weebs"
    website: str = ""
    telegram_channel: str = ""
    community_link: str = ""
    watermark_text: str = "Anime Weebs"
    metadata_author: str = "Anime Weebs"
    metadata_comment: str = "Provided by Anime Weebs"


class DistributionConfig(BaseModel):
    mode: str = "season_package"
    protect_content: bool = True
    temporary_links: bool = True
    link_expiry_minutes: int = 60
    auto_delete: bool = False
    auto_delete_after_minutes: int = 60


class QueueConfig(BaseModel):
    max_visible: int = 10
    position_recalc_seconds: int = 5


class SecurityConfig(BaseModel):
    rate_limit_per_minute: int = 20
    anti_spam_cooldown_seconds: int = 2
    force_subscribe: bool = False
    force_subscribe_channels: list[int] = Field(default_factory=list)
    owner_id: int = 0


class StorageChannelConfig(BaseModel):
    """The database channel where content packs live (header -> files -> end sticker)."""

    enabled: bool = False
    channel_id: int = 0                       # -100... id of the database channel
    # Header text posted before each pack. Variables: {title} {season} {resolution}
    # {language} {episode_from} {episode_to} {group}
    header_template: str = "{title} — Season {season} [{resolution}] [{language}]"
    end_sticker_id: str = ""                  # file_id of the end-of-pack sticker
    copy_mode: str = "copy"                   # copy | forward
    include_header_in_delivery: bool = True
    include_sticker_in_delivery: bool = False


class LogChannelConfig(BaseModel):
    """The operational control center: one channel of persistent, edited-in-place
    section messages (dashboard, pending, active, completed, notices, catalog)
    plus a pool of preallocated reserved messages used when a section message can
    no longer be edited (Telegram's ~48h edit window)."""

    enabled: bool = False
    channel_id: int = 0
    pinned_dashboard: bool = True             # live stats summary (edited in place)
    pinned_catalog: bool = True               # published catalog index (edited in place)
    sections: bool = True                     # full sectioned control center
    reserved_slots: int = 2                   # reserved msgs per growth-prone section
    notices_lines: int = 12                   # rolling event-stream length
    # Sticker posted between sections as a permanent visual divider.
    divider_sticker_id: str = (
        "CAACAgUAAxkBAAI0vGpAOaZ7gJ6Yk9MtJ63jm0sYmDysAAIYAANDc8kSzixbXL29lfc8BA"
    )
    # Cover image at the very top of the channel (URL or file_id). Empty = skip.
    cover_image: str = ""
    # Minutes of inactivity before a human discussion thread is auto-deleted.
    discussion_ttl_minutes: int = 5
    refresh_seconds: int = 60                 # full rebuild of all sections
    # The active-tasks panel gets a fast lane: live downloads/processing update on
    # this short interval so the progress bar feels responsive, while the heavier
    # dashboard/catalog/completed panels stay on the slower full refresh above.
    active_refresh_seconds: int = 5
    # 'all' = everything; otherwise a subset of categories to forward.
    events: list[str] = Field(default_factory=lambda: ["all"])


class AccessConfig(BaseModel):
    """Time-based access: a free trial, then renew via a shortlink token."""

    enabled: bool = False
    free_trial: bool = True
    trial_days: int = 3
    token_days: int = 3
    token_link_ttl_hours: int = 24       # how long a generated token link stays valid
    forward_to_saved_hint: bool = True   # nudge users to forward files to Saved Messages


class ShortlinkConfig(BaseModel):
    """URL shortener used to gate token generation (e.g. Linkvertise)."""

    enabled: bool = False
    provider: str = "linkvertise"
    linkvertise_user_id: str = ""        # your Linkvertise publisher id
    api_token: str = ""                  # generic api token for other providers
    base_url: str = ""                   # generic provider base url


class AcquisitionConfig(BaseModel):
    """What to fetch when a request doesn't pin a specific quality/language.

    A request with no resolution/audio fans out into the full matrix below. ``languages``
    map to audio tracks: english = Dub, japanese = Sub (always with English subtitles).
    """

    resolutions: list[str] = Field(default_factory=lambda: ["360p", "540p", "720p", "1080p"])
    languages: list[str] = Field(default_factory=lambda: ["english", "japanese"])
    require_english_subs: bool = True
    # Mandatory qualities to grab for every request (best-first). Each is fetched
    # when the source offers it; 480p is special-cased with a fallback ladder
    # below so we never ship nothing at the SD tier.
    target_resolutions: list[str] = Field(
        default_factory=lambda: ["1080p", "720p", "480p"]
    )
    # When a target resolution is missing, try these alternates in order. Only the
    # first available alternate is taken, so we don't double up the same tier.
    resolution_fallbacks: dict[str, list[str]] = Field(
        default_factory=lambda: {"480p": ["540p", "360p"]}
    )


class MainChannelConfig(BaseModel):
    """The public 'main' channel where each published anime is posted."""

    enabled: bool = False
    channel_id: int = 0
    # Variables: {title} {tag} {episodes} {qualities} {languages} {genres} {overview}
    caption_template: str = (
        "<blockquote><b>{title}『 #{tag} 』</b></blockquote>\n\n"
        "<b>⌬ EPISODES :</b> {episodes}\n"
        "<b>⌬ QUALITY :</b> {qualities}\n"
        "<b>⌬ LANGUAGE :</b> {languages}\n"
        "<b>⌬ GENRE :</b> {genres}\n\n"
        "<blockquote><b>‣ OverView :</b> {overview}</blockquote>"
    )
    index_button_text: str = "ɪɴᴅᴇx"
    download_button_text: str = "ᴅᴏᴡɴʟᴏᴀᴅ"


class IndexChannelConfig(BaseModel):
    """A channel holding stylized, per-letter index posts the bot maintains."""

    enabled: bool = False
    channel_id: int = 0
    # Rendered per first-letter. Variables: {letter} {entries}
    letter_header_template: str = "•──────────•°• {letter} •°•──────────•"
    entry_template: str = "⦿ {title}"


class SourcesConfig(BaseModel):
    enabled: list[str] = Field(
        default_factory=lambda: ["local", "telegram", "anikoto", "kickassanime", "nyaa"]
    )
    default: str = "telegram"


class UIConfig(BaseModel):
    start_sticker_id: str = "CAACAgUAAyEFAASAgUwqAAJh_mckw2STkeY1WMOHJGY4Hs9_1-2fAAIPFAACYLShVon-N6AFLnIiHgQ"
    start_image_url: str = "https://envs.sh/odE.png"
    start_image_has_spoiler: bool = True
    sticker_delete_delay: float = 1.5
    loading_dot_delay: float = 0.32
    loading_steps: int = 3


class LocalizationConfig(BaseModel):
    default_language: str = "en"
    directory: str = "resources/language"


class BotConfig(BaseModel):
    """Distribution-bot creation and content configuration."""

    auto_create_on_publish: bool = True
    health_check_interval_minutes: int = 60
    delivery_retention_days: int = 7
    avatar_source: str = "tmdb"  # "tmdb" | "anilist"


class AppConfig(BaseModel):
    """Typed view of config.yaml. Every section is optional with sane defaults."""

    features: Features = Field(default_factory=Features)
    downloads: DownloadsConfig = Field(default_factory=DownloadsConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    rename: RenameConfig = Field(default_factory=RenameConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    thumbnail: ThumbnailConfig = Field(default_factory=ThumbnailConfig)
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig)
    branding: BrandingConfig = Field(default_factory=BrandingConfig)
    distribution: DistributionConfig = Field(default_factory=DistributionConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    storage_channel: StorageChannelConfig = Field(default_factory=StorageChannelConfig)
    log_channel: LogChannelConfig = Field(default_factory=LogChannelConfig)
    main_channel: MainChannelConfig = Field(default_factory=MainChannelConfig)
    index_channel: IndexChannelConfig = Field(default_factory=IndexChannelConfig)
    acquisition: AcquisitionConfig = Field(default_factory=AcquisitionConfig)
    access: AccessConfig = Field(default_factory=AccessConfig)
    shortlink: ShortlinkConfig = Field(default_factory=ShortlinkConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    localization: LocalizationConfig = Field(default_factory=LocalizationConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    bot: BotConfig = Field(default_factory=BotConfig)

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "AppConfig":
        p = Path(path)
        if not p.exists():
            return cls()
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)


@lru_cache(maxsize=1)
def get_env() -> EnvSettings:
    """Cached environment settings (loaded once per process)."""
    return EnvSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    """Cached static config.yaml snapshot. Runtime overrides are applied by ConfigService."""
    return AppConfig.load()
