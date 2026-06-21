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

### Notes
- Content acquisition remains authorized-only via the `sources` plugin interface
  (`LocalFileSource` reference). No pirate-site scraper is included.
