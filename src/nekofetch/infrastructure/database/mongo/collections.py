"""MongoDB collection accessors and index setup.

Flexible content & configuration:

- ``anime``               full anime metadata (titles, synopsis, genres, studio, seasons)
- ``artwork``             poster / banner / cover / thumbnail references
- ``settings``            runtime feature toggles & branding overrides (admin panel)
- ``message_templates``   editable per-message templates
- ``processing_profiles`` named pipeline configurations
- ``source_cache``        cached source lookups (TTL)
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

ANIME = "anime"
ARTWORK = "artwork"
SETTINGS = "settings"
TEMPLATES = "message_templates"
PROFILES = "processing_profiles"
SOURCE_CACHE = "source_cache"


class Collections:
    """Typed accessors over the Mongo database handle."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self.db = db

    @property
    def anime(self) -> AsyncIOMotorCollection:
        return self.db[ANIME]

    @property
    def artwork(self) -> AsyncIOMotorCollection:
        return self.db[ARTWORK]

    @property
    def settings(self) -> AsyncIOMotorCollection:
        return self.db[SETTINGS]

    @property
    def templates(self) -> AsyncIOMotorCollection:
        return self.db[TEMPLATES]

    @property
    def profiles(self) -> AsyncIOMotorCollection:
        return self.db[PROFILES]

    @property
    def source_cache(self) -> AsyncIOMotorCollection:
        return self.db[SOURCE_CACHE]

    async def ensure_indexes(self) -> None:
        await self.anime.create_index("title")
        await self.anime.create_index("alt_titles")
        await self.anime.create_index([("title", "text"), ("synopsis", "text")])
        await self.artwork.create_index("anime_doc_id")
        await self.settings.create_index("key", unique=True)
        await self.templates.create_index("key", unique=True)
        await self.source_cache.create_index("expires_at", expireAfterSeconds=0)
