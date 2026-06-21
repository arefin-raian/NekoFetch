# Changelog

All notable changes to NekoFetch are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); the project uses
[Conventional Commits](https://www.conventionalcommits.org/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `LICENSE` (MIT + Acceptable Use Notice) and Mermaid architecture/data-flow diagrams in the README.
- Documentation backbone: `README.md`, `docs/ARCHITECTURE.md`, `docs/PROJECT_JOURNAL.md`,
  `docs/TASKS.md`, this changelog.
- Project scope and authorized-only content-acquisition policy.
- Tech-stack decisions (see `README.md`).
- Project scaffold: package layout, `.env.example`, `config.yaml`, `resources/language/en.json`,
  `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `.gitignore`.
- Core layer: 3-layer configuration system, structlog logging, Fernet token cipher,
  DI container, constants, exception hierarchy.
- Domain model: roles, permissions, request/job/processing enums.
- Database layer: PostgreSQL ORM schema (users, requests, queue, files, bots, access links,
  analytics, audit logs), MongoDB collections + indexes, Redis progress store, repositories.
- Authorized-only content-source interface (`AnimeSource`) with registry and a
  `LocalFileSource` reference implementation (resumable, metadata-detecting).
- Premium UX kit: glyph progress bars, template engine, i18n loader, inline components + pagination.
- Auth service and bot middleware (user resolution, rate limiting, anti-spam).
- Multi-bot manager, admin bot with staged-animation welcome screen, distribution-bot skeleton.
- Full service layer: resumable download worker with live progress, processing pipeline
  (verify→rename→metadata→branding→thumbnail→store), branding engine, season-package
  distribution with temporary/protected links, analytics, runtime settings, publishing.
- APScheduler jobs: access-link expiry sweep and per-message auto-delete.
- Interactive admin bot: request flow, live feature-toggle settings panel, queue and
  analytics views, and the publish-approval workflow.
- Distribution bots: token-paste generation (encrypted, live without restart), live
  multi-bot management, and the anime-bot interface with season-package delivery.

- Metadata enrichment seam (`providers/metadata/`): stable data contracts, `MetadataProvider`
  interface with a provided `build_template_data` orchestrator, a single editable
  `scraper.py` placeholder (`fetch_profile_data`/`fetch_character_data`/`fetch_statistics`/
  `fetch_assets`), transformer, renderer, and `EnrichmentService` (Mongo-cached). Consumed by
  the distribution bot's title page with graceful fallback. See `docs/SCRAPER_GUIDE.md`.

- Database (storage) channel: `StoragePack` model + `StorageChannelService` storing content
  as ordered packs (header → files → end sticker) per anime/season/resolution/language.
  Assisted indexing (admin range input) and automated upload on publish; range delivery
  with protect/auto-delete. Admin storage panel + indexing flow. Resolves the batch-delivery
  open decision.
- Log channel: `LogChannelService` posting all lifecycle/admin/delivery events to one
  configurable channel, plus two auto-updated pinned messages (live stats dashboard +
  catalog index) refreshed on a scheduler. Key services instrumented to emit events.
- Config: `storage_channel.*` and `log_channel.*` sections.

- Alembic migrations: async `migrations/env.py` targeting `Base.metadata`, baseline initial
  revision, and an `AUTO_CREATE_SCHEMA` env toggle (dev auto-create vs. prod migrations).
- Test suite (pytest) covering parsing, progress, templates, permissions, token cipher,
  metadata transform/render, and config; GitHub Actions CI (ruff + compile + pytest).
- Force-subscribe gate on distribution bots (config-driven, with join buttons + recheck).
- Admin broadcast tool (copies a message to all non-banned users, reports delivered/failed).
- Per-bot title binding (a distribution bot can open directly on one bound title).
- Opt-in video watermark processing stage (ffmpeg text/image overlay; corner/opacity/scale).
- Staff & user management: `StaffService` (promote/demote, ban/unban, approve) with audit
  logging + log-channel events, and an admin staff panel wired to the Staff button.
- `docs/DEPLOYMENT.md` — end-to-end first-run and channel setup guide.
- **Main channel publishing**: on publish, post each anime to a public main channel
  (poster + `⌬ EPISODES/QUALITY/LANGUAGE/GENRE` caption + overview) with **[Index][Download]**
  buttons; Download deep-links to the bound bot (`/start anime_<id>`). `ChannelPost` model,
  `main_channel.*` config.
- **Index channel**: bot maintains stylized per-letter index posts (`IndexChannelService`),
  edited in place; the main-channel Index button links to the relevant letter post.
- **Multi-quality × language acquisition**: a request with no pinned quality/language fans
  out into the configured matrix (resolutions × english/japanese = dub/sub), English subs
  enforced; files tagged per combo so packs build per quality/language. `acquisition.*` config.
- **Bot auto-branding**: binding a bot to a title auto-sets its name/about/description from
  the title's facts (best-effort, version-tolerant). **Pending-bot queue**: admin sees titles
  that have content but no bot yet; content work never blocks on tokens.
- **Access/token system**: per-user free trial then renewal via a shortlink token, gating
  delivery (`AccessService`, `access.*`). Pluggable shortlink seam (`providers/shortlink/`)
  with a **Linkvertise** adapter. Deep-link token redemption (`/start token_<t>`). Plus a
  "forward to Saved Messages" hint and the auto-delete window note on delivery.

### Notes
- Content acquisition remains authorized-only via the `sources` plugin interface
  (`LocalFileSource` reference). No pirate-site scraper is included.
- The metadata enrichment seam ships unimplemented (`implemented = False`); implement the
  four fetchers in `scraper.py` against an authorized source to enable it.
