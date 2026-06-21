# NekoFetch — Task Tracker

> Continuously updated. Mirrors the session task list.

## In Progress

- **Admin bot** — welcome/auth/role/menus done; request flow, settings panel, queue/admin
  handlers still to wire.

## Pending

- Service layer — request, queue, download worker (live progress), processing pipeline
  (verify→rename→metadata→branding→thumbnail→store→publish), distribution, branding, analytics.
- Distribution bots — generation flow, anime-bot interface, season-package delivery.
- Temporary access links + auto-delete (APScheduler jobs).
- Content publishing/approval workflow.
- Analytics dashboard.
- GitHub integration + automatic conventional-commit workflow (pending operator confirmation).
- Alembic migration setup (dev uses `create_all`).

## Completed

- Project scope, authorized-only policy, tech stack.
- Reference repositories analyzed.
- Documentation backbone.
- Foundation: package layout, config files, Docker, `.gitignore`, `pyproject.toml`.
- Core: config (3-layer), logging, constants, exceptions, security (token cipher), DI container.
- Domain enums + permission model.
- Database: Postgres ORM schema, Mongo collections, Redis progress store, repositories.
- Authorized-source interface + `LocalFileSource`.
- Premium UX kit: progress bars, templates, i18n, components/pagination.
- Auth service + bot auth/rate-limit middleware.
- Multi-bot manager + admin bot welcome screen (staged animation) + distribution-bot skeleton.
- Verified clean compile of the whole `src` tree.
