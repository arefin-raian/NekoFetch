# NekoFetch — Task Tracker

> Continuously updated. Mirrors the session task list.

## In Progress

- (none) — v0.1 milestone complete.

## Pending (operator actions — need real credentials/infra)

- **Implement `scraper.py`** — operator fills the four `fetch_*` methods against an
  authorized source and sets `implemented = True` (see `docs/SCRAPER_GUIDE.md`).
- **Configure channels** — set `storage_channel`/`log_channel` ids, make the admin bot an
  admin of both, set the end-sticker file_id; then enable.
- **Run a live smoke test** — real Telegram API creds + Postgres/Mongo/Redis up
  (`docker compose up`), then exercise the request→download→publish→deliver loop.

## Nice-to-have (future)

- Richer analytics windows (active-user time windows), staff-management UI, more languages.

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
- GitHub: public repo created and `main` pushed to https://github.com/arefin-raian/NekoFetch.
- Metadata enrichment seam: isolated `providers/metadata/` (models, provider interface,
  single editable `scraper.py` placeholder, transformer, renderer), `EnrichmentService`
  (Mongo-cached), distribution-bot consumption with fallback, and `docs/SCRAPER_GUIDE.md`.
- Database (storage) channel: `StoragePack` model + `StorageChannelService` (assisted
  indexing + automated upload + range delivery), admin storage panel/indexing flow,
  distribution delivery via packs with fallback.
- Log channel: `LogChannelService` (all-event sink + two auto-updated pinned messages),
  scheduler refresh, instrumentation across services.
- Alembic migrations (async env + baseline) + `AUTO_CREATE_SCHEMA` toggle.
- Test suite (pytest) + GitHub Actions CI (ruff + compile + pytest).
- Force-subscribe gate, admin broadcast tool, per-bot title binding.
- Opt-in ffmpeg watermark processing stage.
- Staff & user management UI (promote/demote, ban/unban, approve) with audit logging.
- `docs/DEPLOYMENT.md` first-run + channel setup guide.
