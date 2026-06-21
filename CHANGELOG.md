# Changelog

All notable changes to NekoFetch are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); the project uses
[Conventional Commits](https://www.conventionalcommits.org/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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

### Notes
- Content acquisition remains authorized-only via the `sources` plugin interface
  (`LocalFileSource` reference). No pirate-site scraper is included.
- The metadata enrichment seam ships unimplemented (`implemented = False`); implement the
  four fetchers in `scraper.py` against an authorized source to enable it.
