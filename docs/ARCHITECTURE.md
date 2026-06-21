# NekoFetch — Architecture

> Living document. Update whenever a design decision is made or changed.

## 1. Guiding principles

1. **Configuration-first.** Behaviour is driven by `.env` + `config.yaml` + in-Telegram settings
   stored in MongoDB. Hardcoded values are avoided; almost every feature is toggleable at runtime.
2. **Authorized-only acquisition.** Content enters the system through the `sources` plugin interface.
   Only sources the operator is authorized to use are implemented. No pirate-site scrapers.
3. **Clean architecture.** Dependencies point inward: `bots`/`ui` → `services` → `repositories` →
   `infrastructure`. The domain layer has no framework imports.
4. **Async-first.** All I/O is async. Long-running work (downloads, processing) runs on a worker
   loop with progress published to Redis and rendered via Telegram message edits.
5. **Recoverable.** Docs + `.recovery-state.json` are updated as work proceeds; the repo is always
   buildable and deployable.

## 2. Layered structure

```
src/nekofetch/
├── core/            # config, logging, DI container, constants, exceptions  (no business logic)
├── domain/          # entities, enums, value objects                        (pure, no I/O)
├── infrastructure/  # postgres / mongo / redis clients, scheduler, repositories
├── sources/         # pluggable AUTHORIZED content-acquisition interface + impls
├── providers/       # pluggable metadata enrichment seam (scraper placeholder + transform/render)
├── services/        # business logic: auth, requests, queue, download, processing, distribution
├── ui/              # premium Telegram UX kit: progress bars, templates, components, pagination
├── localization/    # i18n loader over resources/language/*.json
└── bots/            # admin bot, distribution bots, multi-bot manager
```

Dependency rule: an inner layer never imports an outer layer. `services` depend on repository
*interfaces*; concrete repositories live in `infrastructure` and are wired by the DI container.

## 3. Data stores & responsibilities

### PostgreSQL (structured, transactional)
`users`, `roles`, `permissions`, `requests`, `download_queue`, `files`, `bots`,
`analytics_events`, `audit_logs`, `access_links`. SQLAlchemy 2.0 async ORM, Alembic migrations.

### MongoDB (flexible, content & config)
`anime` (metadata, alt titles, genres, studio), `artwork` (poster/banner/cover refs),
`settings` (runtime feature toggles & branding), `message_templates`, `processing_profiles`,
`source_cache`. Motor async driver.

### Redis
Live download/processing progress, rate-limit counters, anti-spam, FSM state cache, job locks.

### Local media store
`storage/` (configurable) holds downloaded/ingested media, generated thumbnails, and artwork,
keyed by anime + episode + resolution + language.

## 4. Configuration layers (precedence: in-Telegram > config.yaml > .env defaults)

- `.env` — secrets & connection strings (tokens, DB creds, paths). Loaded by pydantic-settings.
- `config.yaml` — feature toggles, downloads, processing, distribution, branding, queue defaults.
- MongoDB `settings` — runtime overrides editable from the admin settings panel without restart.

`core.config.Settings` merges these into a single typed object; runtime overrides are layered on
read via `ConfigService` so changes apply dynamically.

## 5. Content-acquisition (sources) interface

`sources/base.py` defines `AnimeSource` (ABC). Methods mirror the clean Aniyomi-style shape but are
provider-agnostic and authorized-only:

```
search(query)            -> list[AnimeStub]
get_details(anime_id)    -> AnimeDetails           # synopsis, genres, studio, seasons
get_episodes(anime_id)   -> list[Episode]          # season/episode detection
get_videos(episode_id)   -> list[VideoVariant]     # resolution / language / subtitle detection
download(variant, dest, on_progress)               # resumable, progress callbacks
```

`registry.py` discovers registered sources. `local.py` is the reference implementation: it ingests
a structured local directory of content the operator owns. Future authorized providers (licensed
HTTP APIs, official catalogs) plug in by implementing `AnimeSource`.

## 5b. Metadata enrichment (pluggable scraping seam)

Acquisition of *display metadata* (profile, characters, statistics, artwork) is isolated in
`providers/metadata/` so it can be implemented later by editing **one file**. Layers:

```
scraper.py     fetch_profile_data / fetch_character_data / fetch_statistics / fetch_assets
               -> Raw* models                                   [the only file to edit]
transformer.py Raw* -> AnimeTemplateData (canonical view model) [stable]
renderer.py    AnimeTemplateData -> RenderedAnimeInfo (caption+image) [stable]
EnrichmentService (services/) -> cache to Mongo `anime`, serve to bots
```

The `MetadataProvider.implemented` flag gates the seam: while `False`, `EnrichmentService`
returns `None` and consumers fall back to basic source metadata; flipping it `True` (after
implementing the fetchers) upgrades every consumer automatically with no other changes.
Required field: `RawProfile.title`. See `docs/SCRAPER_GUIDE.md`.

## 6. Processing pipeline

`Search → Download → Verify → Rename → Metadata → Branding → Thumbnail → Store → Publish`

Each stage is a discrete, independently-toggleable step (`services/processing/`). A `ProcessingJob`
moves through stages; failures are recorded and retryable. Publishing requires admin approval.

## 7. Distribution model

Season-centric delivery. A user selects a season → resolution → language; the bot serves a
**package** (batch of indexed files) rather than individual episodes by default. Delivery options:
indexed file delivery, protected content, and **temporary/expiring access links** with optional
**auto-delete** — all configurable. Expiry and deletion are driven by APScheduler jobs.

## 7b. Database (storage) channel — resolves the §10 batch-delivery decision

Content is stored in a single Telegram **database channel** as ordered packs, mirroring the
file-sharing-bot range pattern:

```
header text  ->  file 1, 2, 3 ... N  ->  end sticker     (per anime/season/resolution/language)
```

Each pack is recorded as a `StoragePack` (Postgres): `channel_id`, `header_message_id`,
`start_message_id`, `end_message_id`, the ordered `file_message_ids`, and `file_count`.
A pack is unique per `(anime_doc_id, season, resolution, audio)`.

`StorageChannelService` provides three operations (all via the admin client, which must
administer the channel):

- **index_pack** — *assisted ingestion*: record a range you posted manually (admin gives
  `start_id..end_id`; the service enumerates the range and keeps the media as the file list).
- **upload_pack** — *automated ingestion*: on publish, post the header, upload files in
  order, post the end sticker, and record the range.
- **deliver** — copy a pack's messages to a user (honors `protect_content`; header/sticker
  inclusion configurable). The caller schedules auto-delete of the copied messages.

Distribution delivery prefers a stored pack (direct copy) and falls back to a temporary
access token when no pack exists. Header text and the end sticker are configurable
(`storage_channel.*`), with template variables `{title}{season}{resolution}{language}
{episode_from}{episode_to}{group}`.

## 8. Access control

Roles: `user`, `staff`, `admin` (extensible). Permissions are role-derived and checked in a
Pyrogram middleware before any handler runs. Admin whitelist seeded from `.env`. All privileged
actions write to `audit_logs`. Rate limiting and anti-spam enforced via Redis counters.

## 9. Multi-bot runtime

`bots/manager.py` runs the admin bot plus N distribution bots (one Pyrogram client each) in a
single process/event loop. Bots are registered by token (encrypted at rest), and content is
deployed to them automatically once published.

## 9b. Observability — log channel

A single configurable **log channel** receives every notable event via
`LogChannelService.event(category, action, **fields)` — requests, queue, downloads,
processing, publishing, deliveries, bot registration, admin/setting changes, errors.
`event()` is fire-and-forget and never raises into its caller (logging must not break the
operation it records). Categories: `request, queue, download, processing, publish,
delivery, admin, bot, error, system`; `events: [all]` forwards everything.

Two **pinned messages** are maintained in place (edited, not reposted) on a scheduler
(`refresh_seconds`): a **live stats dashboard** (users, downloads, queue, failures,
published) and a **catalog index** (published anime → seasons). Their message ids are
cached in Redis so they survive restarts.

This complements the durable `audit_logs` / `analytics_events` Postgres tables — the
channel is the human-facing live feed; the tables are the queryable record.

## 10. Open decisions

- [x] Batch-delivery mechanism — **resolved**: single database channel with message-range
  packs (§7b), assisted + automated ingestion.
- [ ] Worker process model: in-process task loop vs. separate worker container (start in-process).
- [ ] Token encryption: Fernet via `SECRET_KEY` (current plan).
