# NekoFetch — Task Tracker

> Continuously updated. Mirrors the session task list.

## In Progress

- **GitHub integration** — local git initialized with conventional commits; awaiting
  operator GitHub token/username/repo to create the remote and push.

## Pending

- Alembic migrations (dev currently uses `create_all`).
- Optional polish: video watermarking transcode, force-subscribe gate, broadcast tool,
  per-bot binding of a single title in the generation flow, richer analytics windows.
- Test suite (pytest) and CI.

## Completed

- Project scope, authorized-only policy, tech stack; reference repos analyzed.
- Documentation backbone.
- Foundation: package layout, config files, Docker, `.gitignore`, `.gitattributes`, `pyproject.toml`.
- Core: 3-layer config, logging, constants, exceptions, security (token cipher), DI container.
- Domain enums + permission model.
- Database: Postgres ORM schema, Mongo collections, Redis progress store, repositories.
- Authorized-source interface + `LocalFileSource`.
- Premium UX kit: progress bars, templates, i18n, components/pagination.
- Auth service + bot auth/rate-limit middleware.
- Multi-bot manager + admin bot welcome (staged animation).
- Service layer: request, queue, download worker (live progress + resume), processing
  pipeline (verify→rename→metadata→branding→thumbnail→store), branding engine,
  distribution (season packages, temp/protected links), analytics, settings, publishing.
- Admin bot: request flow, settings panel (live toggles), queue/analytics views, approval panel.
- Distribution bots: generation flow, live multi-bot add, anime-bot interface, season-package
  delivery with protected content + temporary links + auto-delete.
- Local git with logical conventional commits; clean compile of the whole `src` tree.
