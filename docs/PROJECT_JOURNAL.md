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
