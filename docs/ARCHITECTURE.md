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

## 6. Processing pipeline

`Search → Download → Verify → Rename → Metadata → Branding → Thumbnail → Store → Publish`

Each stage is a discrete, independently-toggleable step (`services/processing/`). A `ProcessingJob`
moves through stages; failures are recorded and retryable. Publishing requires admin approval.

## 7. Distribution model

Season-centric delivery. A user selects a season → resolution → language; the bot serves a
**package** (batch of indexed files) rather than individual episodes by default. Delivery options:
indexed file delivery, protected content, and **temporary/expiring access links** with optional
**auto-delete** — all configurable. Expiry and deletion are driven by APScheduler jobs.

## 8. Access control

Roles: `user`, `staff`, `admin` (extensible). Permissions are role-derived and checked in a
Pyrogram middleware before any handler runs. Admin whitelist seeded from `.env`. All privileged
actions write to `audit_logs`. Rate limiting and anti-spam enforced via Redis counters.

## 9. Multi-bot runtime

`bots/manager.py` runs the admin bot plus N distribution bots (one Pyrogram client each) in a
single process/event loop. Bots are registered by token (encrypted at rest), and content is
deployed to them automatically once published.

## 10. Open decisions

- [ ] Final batch-delivery mechanism (indexed channel vs. stored-message forwarding).
- [ ] Worker process model: in-process task loop vs. separate worker container (start in-process).
- [ ] Token encryption: Fernet via `SECRET_KEY` (current plan).
