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
