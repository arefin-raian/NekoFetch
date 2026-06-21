# NekoFetch — Project Journal

Chronological development log. Newest entries at the top. This file (with `TASKS.md`,
`CHANGELOG.md`, and `.recovery-state.json`) is the recovery backbone — inspect it before resuming.

---

## 2026-06-21

### Session 1 — Project bootstrap

**Completed**

- Established project scope and the **authorized-only** content policy (no pirate-site scraping;
  pluggable source interface with local/licensed reference implementations).
- Locked the tech stack: Python 3.12+, Pyrogram, PostgreSQL (SQLAlchemy 2.0 async + Alembic),
  MongoDB (Motor), Redis, APScheduler, Pydantic v2 settings, structlog, Docker Compose.
- Analyzed the two reference repositories:
  - `arefin-raian/nonayarbusiness` — Pyrogram file-sharing bot (MongoDB). Adapting *concepts*:
    link generation, force-subscribe, protected content, auto-delete timers, broadcast, in-bot config.
  - `yuzono/anime-extensions/.../kickassanime` — Aniyomi (Kotlin) pirate-source extension. Using
    only the clean `search → details → episodes → videos` interface shape; **not** porting scraping.
- Created documentation backbone: `README.md`, `docs/ARCHITECTURE.md`, this journal, `TASKS.md`,
  `CHANGELOG.md`.

**Files modified**

- `README.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_JOURNAL.md`, `docs/TASKS.md`, `CHANGELOG.md`

**Current state**

- Documentation backbone in place. Building project skeleton, config system, and Docker support next.

### Session 1 (cont.) — Foundation through bootable skeleton

**Completed**

- Scaffolded the full package layout, `.env.example`, `config.yaml`,
  `resources/language/en.json`, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.gitignore`.
- Core layer: `config.py` (3-layer config: env → yaml → runtime), `logging.py` (structlog),
  `constants.py`, `exceptions.py`, `security.py` (Fernet token cipher), `container.py` (DI root).
- Domain: `enums.py` (Role/Permission/RequestStatus/JobStatus/ProcessingStage/...).
- Database: SQLAlchemy 2.0 async ORM (users, requests, download_queue, files, bots,
  access_links, analytics_events, audit_logs); Mongo `Collections` + indexes; Redis
  `ProgressStore`; repository pattern (base, user, request, queue).
- Sources: authorized-only `AnimeSource` interface + `SourceRegistry` + `LocalFileSource`
  reference implementation (season/episode/resolution/audio detection, resumable copy).
- UX kit: progress bars (▰▱), template engine, i18n loader, inline components + pagination.
- Auth service (role resolution via env whitelist, permission checks).
- Bots: multi-bot `BotManager`, admin-bot client factory, auth/rate-limit middleware,
  premium `/start` welcome with staged loading animation; distribution-bot skeleton.
- Verified: `python -m compileall src` passes (clean syntax across all modules).

**Files modified**

- Entire `src/nekofetch/**` tree, root config & Docker files, all `docs/`.

**Current state**

- Project boots end-to-end at skeleton level (admin bot `/start` → welcome screen).
- Tasks 1–5 complete; task 6 (admin bot) partially complete: welcome/auth/role/menus done;
  request flow, settings panel, and queue/admin handlers still to wire.

**Known issues / open questions**

- GitHub credentials not yet provided. Note: creating a repo + pushing publishes code
  externally — will confirm with the operator before doing it.
- Menu buttons (req/queue/settings/admin) are defined but their handlers are not yet built.
- Final batch-delivery mechanism for distribution bots not yet decided (see ARCHITECTURE §10).

**Next planned tasks**

- Service layer: request, queue, download worker (live progress), processing pipeline
  (verify→rename→metadata→branding→thumbnail→store→publish), distribution, branding, analytics.
- Admin bot: request flow handlers, in-Telegram settings panel, queue/analytics views.
- Distribution: bot generation flow + anime-bot interface + season-package delivery
  (protected/temporary links + auto-delete via APScheduler).

### Session 1 (cont.) — Database channel + log channel

**Completed**

- **Database (storage) channel.** New `StoragePack` ORM model (channel message range per
  anime/season/resolution/language). `StorageChannelService` with: assisted indexing
  (admin supplies `start_id..end_id`; enumerates the range, keeps media as ordered files),
  automated upload on publish (header → files → end sticker → record range), and range
  delivery (copy to user, protect/auto-delete aware). Distribution delivery now prefers a
  stored pack and falls back to a temporary token. Admin storage panel + indexing flow.
- **Log channel.** `LogChannelService.event()` posts all lifecycle/admin/delivery events to
  one configurable channel (fire-and-forget, never raises). Two pinned messages
  (live stats dashboard + catalog index) created on startup and refreshed on a scheduler;
  message ids cached in Redis. Instrumented request submit, queue, download complete/fail,
  processing, publish, bot registration, setting changes, delivery.
- Config sections `storage_channel.*` and `log_channel.*` (in `config.py` + `config.yaml`).
- Decisions: single channel with delimited packs; both ingestion paths; two pinned messages;
  one log channel for everything. Resolves ARCHITECTURE §10 batch-delivery.
- Verified clean compile.

**Current state**

- Both channel subsystems are implemented and wired but ship **disabled** (`enabled: false`,
  `channel_id: 0`). To enable: set the channel ids, make the admin bot an administrator of
  both channels, and (for storage) set the end sticker file_id.

**Known issues / open questions**

- Assisted indexing relies on the bot reading the channel range by message id (admin bot
  must be a channel admin). Verified by compile only; needs a live channel to exercise.

### Session 1 (cont.) — Metadata enrichment seam (single-file scraper)

**Completed**

- Added an isolated metadata/enrichment provider layer so scraping can be added later by
  editing one file. Layers: `providers/metadata/models.py` (stable Raw* + AnimeTemplateData
  + RenderedAnimeInfo contracts), `base.py` (`MetadataProvider` ABC with provided
  `build_template_data` orchestrator), `scraper.py` (the single editable placeholder —
  `fetch_profile_data`/`fetch_character_data`/`fetch_statistics`/`fetch_assets`,
  `implemented` flag), `transformer.py`, `renderer.py`, `registry.py`.
- `EnrichmentService` (Mongo-cached) is the app's entry point; returns None while the
  scraper is unimplemented so consumers fall back.
- Wired consumption into the distribution bot title page (rich card when available, basic
  details otherwise) and into the container (provider lifecycle).
- Documented end-to-end in `docs/SCRAPER_GUIDE.md` (functions, inputs, outputs, required
  fields, scraper→transformer→template→output flow) and ARCHITECTURE §5b.
- Verified clean compile.

**Current state**

- The scraping seam is in place and consumed but intentionally unimplemented. Operator
  implements `scraper.py` against an authorized source and flips `implemented = True`.

### Session 1 (cont.) — Feature-complete (tasks 1–8), local git

**Completed**

- Full service layer: request, queue, resumable download worker (live progress → Redis),
  processing pipeline (verify→rename→metadata→branding→thumbnail→store), branding engine,
  distribution (season packages + temporary/protected links), analytics, settings, publishing.
- Scheduler wired in (link-expiry sweep + per-message auto-delete).
- Admin bot fully interactive: Redis FSM, request flow (search→results→content→season→scope→
  submit), live feature-toggle settings panel (persisted to Mongo), queue + analytics views,
  publish-approval workflow.
- Distribution bots: token-paste generation (validated, encrypted, live without restart),
  live multi-bot manager add, anime-bot interface (catalog/title→season→resolution→language→
  episodes→season package) with protected content, temporary links, and auto-delete.
- Local git initialized; 9 clean conventional commits; whole `src` tree compiles.

**Current state**

- Tasks 1–8 complete. Project boots and is feature-complete for the authorized-distribution
  scope. Only the GitHub remote push (task 9) remains, which needs operator credentials.

**Known issues / open questions**

- `gh` CLI not installed → will push via GitHub API + token-authenticated HTTPS remote.
- Runtime testing requires real Telegram/API credentials and running Postgres/Mongo/Redis;
  verification so far is byte-compile (deps not installed in this environment).

**Next planned tasks**

- Create GitHub repo + push (awaiting token/username/repo).
- Alembic migrations; pytest suite + CI; optional polish (watermark transcode, force-sub,
  broadcast, per-bot title binding).
