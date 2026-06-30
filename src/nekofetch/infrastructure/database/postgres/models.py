"""PostgreSQL ORM models — structured, transactional data.

Flexible content (anime metadata, artwork, templates, runtime settings) lives in
MongoDB; this schema holds the relational backbone. Anime are referenced here by
their MongoDB id (``anime_doc_id``) so the two stores stay loosely coupled.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nekofetch.domain.enums import (
    AudioType,
    BotKind,
    JobStatus,
    RequestStatus,
    Role,
)
from nekofetch.infrastructure.database.postgres.base import (
    Base,
    EnumStr,
    PKMixin,
    TimestampMixin,
)


class User(Base, PKMixin, TimestampMixin):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(EnumStr(Role), default=Role.USER, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Time-based access (trial / token renewals). None = never granted yet.
    access_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requests: Mapped[list["Request"]] = relationship(back_populates="user")


class Request(Base, PKMixin, TimestampMixin):
    __tablename__ = "requests"

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)  # REQ-1048
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    anime_doc_id: Mapped[str | None] = mapped_column(String(48), index=True)
    anime_title: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # which source plugin
    source_ref: Mapped[str | None] = mapped_column(String(256))      # source-native id

    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    episodes: Mapped[list | None] = mapped_column(JSONB)             # selected episode numbers
    resolution: Mapped[str | None] = mapped_column(String(16))
    audio: Mapped[AudioType | None] = mapped_column(EnumStr(AudioType))

    status: Mapped[RequestStatus] = mapped_column(
        EnumStr(RequestStatus), default=RequestStatus.PENDING, index=True, nullable=False
    )
    position: Mapped[int | None] = mapped_column(Integer)

    # Phase 1 franchise data — JSON blob with the full AniList relation graph
    # so downstream sourcing knows the complete connected universe.
    franchise_data: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped["User"] = relationship(back_populates="requests")
    jobs: Mapped[list["DownloadJob"]] = relationship(back_populates="request")


class DownloadJob(Base, PKMixin, TimestampMixin):
    __tablename__ = "download_queue"

    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        EnumStr(JobStatus), default=JobStatus.QUEUED, index=True, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # Live progress (also mirrored to Redis for fast UI reads)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)   # 0..100
    speed_bps: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    downloaded_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    current_episode: Mapped[int | None] = mapped_column(Integer)
    eta_seconds: Mapped[int | None] = mapped_column(Integer)

    # Resume support
    resume_state: Mapped[dict | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    request: Mapped["Request"] = relationship(back_populates="jobs")
    files: Mapped[list["MediaFile"]] = relationship(back_populates="job")


class MediaFile(Base, PKMixin, TimestampMixin):
    __tablename__ = "files"

    job_id: Mapped[int | None] = mapped_column(ForeignKey("download_queue.id"), index=True)
    anime_doc_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)

    season: Mapped[int | None] = mapped_column(Integer)
    episode: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(16))
    audio: Mapped[AudioType | None] = mapped_column(EnumStr(AudioType))

    original_name: Mapped[str | None] = mapped_column(String(512))
    final_name: Mapped[str | None] = mapped_column(String(512))
    local_path: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128))
    container: Mapped[str | None] = mapped_column(String(8))

    # Telegram delivery references (populated once uploaded to a storage chat)
    tg_file_id: Mapped[str | None] = mapped_column(String(256))
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    tg_chat_id: Mapped[int | None] = mapped_column(BigInteger)

    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped["DownloadJob | None"] = relationship(back_populates="files")

    __table_args__ = (
        Index("ix_files_locator", "anime_doc_id", "season", "episode", "resolution", "audio"),
    )


class DistributionBot(Base, PKMixin, TimestampMixin):
    __tablename__ = "bots"

    kind: Mapped[BotKind] = mapped_column(EnumStr(BotKind), default=BotKind.DISTRIBUTION, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    bot_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)

    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted
    anime_doc_id: Mapped[str | None] = mapped_column(String(48), index=True)  # bound title, if any
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSONB)  # per-bot overrides


class AccessLink(Base, PKMixin, TimestampMixin):
    """Temporary / protected access tokens for season packages."""

    __tablename__ = "access_links"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)  # what it grants
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class StoragePack(Base, PKMixin, TimestampMixin):
    """A season pack stored as a message range in the database channel.

    Layout in the channel (the file-sharing-bot pattern):

        header text  ->  file 1, 2, 3 ... N (in order)  ->  end sticker

    Delivery copies the recorded range to the user. A pack is unique per
    (anime, season, resolution, language).
    """

    __tablename__ = "storage_packs"

    anime_doc_id: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    anime_title: Mapped[str] = mapped_column(String(256), nullable=False)
    season: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str] = mapped_column(String(16), nullable=False)
    audio: Mapped[AudioType] = mapped_column(EnumStr(AudioType), nullable=False)

    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    header_message_id: Mapped[int | None] = mapped_column(BigInteger)
    start_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)   # first file
    end_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)     # end sticker / last
    file_message_ids: Mapped[list | None] = mapped_column(JSONB)                # ordered, explicit
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    episode_from: Mapped[int | None] = mapped_column(Integer)
    episode_to: Mapped[int | None] = mapped_column(Integer)

    ingest_method: Mapped[str | None] = mapped_column(String(16))  # indexed | uploaded
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "anime_doc_id", "season", "resolution", "audio", name="uq_storage_pack"
        ),
        Index("ix_storage_pack_lookup", "anime_doc_id", "season", "resolution", "audio"),
    )


class ChannelPost(Base, PKMixin, TimestampMixin):
    """Tracks where an anime has been posted (main channel post + index entry).

    Lets the bot edit/update those posts in place instead of reposting.
    """

    __tablename__ = "channel_posts"

    anime_doc_id: Mapped[str] = mapped_column(String(48), unique=True, index=True, nullable=False)
    main_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    main_message_id: Mapped[int | None] = mapped_column(BigInteger)
    index_letter: Mapped[str | None] = mapped_column(String(2))
    index_message_id: Mapped[int | None] = mapped_column(BigInteger)


class AccessToken(Base, PKMixin, TimestampMixin):
    """A renewal token a user redeems (after completing a shortlink) for more access time."""

    __tablename__ = "access_tokens"

    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(Base, PKMixin):
    __tablename__ = "analytics_events"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    event: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    anime_doc_id: Mapped[str | None] = mapped_column(String(48), index=True)
    data: Mapped[dict | None] = mapped_column(JSONB)


class BotContentPost(Base, PKMixin, TimestampMixin):
    """Pre-generated content posts for a distribution bot.

    When a bot is created for an anime, we generate a set of posts (watch guide,
    season cards, info/overview, footer) that are stored here and delivered in
    order when a user starts the bot. The admin can edit these via settings.
    """

    __tablename__ = "bot_content_posts"

    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "watch_guide" | "season_card" | "movie_card" | "info_card" | "footer"
    season: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(16))
    audio: Mapped[str | None] = mapped_column(String(16))  # subbed/dubbed/dual_audio
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    image_local_path: Mapped[str | None] = mapped_column(Text)
    button_data: Mapped[dict | None] = mapped_column(JSONB)  # structured button layout
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)  # set after first send


class AuditLog(Base, PKMixin):
    __tablename__ = "audit_logs"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(256))
    detail: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("ts", "actor_id", "action", "target", name="uq_audit_dedupe"),
    )
