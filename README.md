# NekoFetch

**Premium content distribution platform for Telegram.**

NekoFetch is a configuration-driven, multi-tenant Telegram bot ecosystem for distributing
video content **you own or are licensed to distribute**. It consists of a private admin/management
bot and any number of automatically-managed, public-facing distribution bots (one per title,
optimized for Telegram discovery).

> ### Scope & legitimacy
> NekoFetch is built **only** for authorized distribution. The content-acquisition layer is a
> pluggable interface (`nekofetch.sources`) with reference implementations for **authorized sources
> only** — local ingestion of files you own, and HTTP/official APIs you control or are licensed to use.
> It deliberately ships **no** plugin that scrapes pirate streaming sites, and the platform does not
> re-attribute or strip the rightful metadata of third-party copyrighted works. Operators are
> responsible for ensuring they hold distribution rights to any content they ingest.

---

## Architecture at a glance

- **Admin bot** — private management surface (staff/admin), download queue, processing pipeline,
  approval/publishing, analytics, full in-Telegram settings.
- **Distribution bots** — generated per title from a BotFather token; searchable content libraries
  with season-centric delivery.
- **Sources** — pluggable, authorized-only acquisition layer.
- **Processing pipeline** — verify → rename → metadata → branding → thumbnail → store → publish.
- **Storage** — PostgreSQL (structured), MongoDB (flexible content/metadata/templates), Redis (cache/queues), local media store.

## Tech stack

| Concern              | Choice                                            |
|----------------------|---------------------------------------------------|
| Language             | Python 3.12+, async-first                         |
| Telegram             | Pyrogram (MTProto — large media + many bots)      |
| Relational DB        | PostgreSQL via SQLAlchemy 2.0 async + asyncpg     |
| Migrations           | Alembic                                           |
| Document DB          | MongoDB via Motor                                 |
| Cache / queues       | Redis (`redis.asyncio`)                           |
| Scheduling           | APScheduler (auto-delete, link expiry, jobs)      |
| Config               | Pydantic v2 settings (`.env`) + `config.yaml`     |
| Logging              | structlog                                         |
| Media                | ffmpeg / mkvtoolnix (metadata, thumbnails)        |
| Deployment           | Docker + Docker Compose                           |

## Quick start

```bash
cp .env.example .env          # fill in bot tokens, DB creds, admin IDs
# review config.yaml for feature toggles, branding, distribution rules
docker compose up -d          # postgres, mongo, redis, nekofetch
```

For local development without Docker, see `docs/ARCHITECTURE.md`.

## Documentation

- `docs/DEPLOYMENT.md` — first-run + channel setup (start here to run it).
- `docs/ARCHITECTURE.md` — design decisions, DB structure, service responsibilities, pipeline.
- `docs/SCRAPER_GUIDE.md` — implement the metadata scraper in one file.
- `docs/PROJECT_JOURNAL.md` — chronological development log (recovery backbone).
- `docs/TASKS.md` — live task tracker.
- `CHANGELOG.md` — formal version history.

## License

See `LICENSE`. You are responsible for the licensing of any content you distribute through NekoFetch.
