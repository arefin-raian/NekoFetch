<div align="center">

# 🐾 NekoFetch

### A premium, fully-automated anime sourcing, processing & distribution platform for Telegram

*Search → confirm → source → download (every quality, dual-audio) → verify → brand → publish → deliver — orchestrated from a self-healing control-center channel, with exhaustive diagnostics and zero silent failures.*

`Python 3.12+` · `Pyrogram (pyrofork)` · `PostgreSQL` · `MongoDB` · `Redis` · `async everywhere`

</div>

---

## Table of contents

- [What is NekoFetch?](#what-is-nekofetch)
- [Why it exists](#why-it-exists)
- [Feature catalogue](#feature-catalogue)
- [The big picture — architecture](#the-big-picture--architecture)
- [The request lifecycle, end to end](#the-request-lifecycle-end-to-end)
- [Sourcing & extraction engine](#sourcing--extraction-engine)
- [Reliability: how a download *refuses* to fail silently](#reliability-how-a-download-refuses-to-fail-silently)
- [Quality & audio policy](#quality--audio-policy)
- [The download engine](#the-download-engine)
- [The processing pipeline](#the-processing-pipeline)
- [Channels: storage, main, index & the control center](#channels-storage-main-index--the-control-center)
- [Distribution bots](#distribution-bots)
- [The log-channel control center](#the-log-channel-control-center)
- [Localization](#localization)
- [Configuration reference](#configuration-reference)
- [Installation & setup](#installation--setup)
- [Running NekoFetch](#running-nekofetch)
- [Admin commands](#admin-commands)
- [Operations & diagnostics](#operations--diagnostics)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Tech stack](#tech-stack)
- [Troubleshooting](#troubleshooting)
- [Glossary](#glossary)

---

## What is NekoFetch?

NekoFetch is an end-to-end pipeline that turns *"I want this anime"* into *"it's published and downloadable"* — entirely through Telegram, entirely automatically, and entirely **authorized-only**.

A user asks for a title in a bot chat. NekoFetch identifies it against **AniList** (with **TMDB** for artwork), confirms the exact franchise, and posts a **request card** to a staff control-center channel. A staff member assigns a source. NekoFetch then:

1. **extracts** playable streams from the chosen provider (AniKoto / KickAssAnime / torrents / a Telegram userbot index),
2. **downloads** every required quality (480p / 720p / 1080p, with fallbacks) in both **sub and dub**, de-masking obfuscated HLS segments byte-for-byte,
3. **verifies** the files aren't corrupt, **renames**, **tags metadata**, optionally **watermarks**, and attaches an **official TMDB poster thumbnail**,
4. **uploads** the finished packs to a private storage (database) channel,
5. **publishes** to the public main channel + an A–Z index channel, and **notifies** the requester,
6. **auto-creates a distribution bot** for each published title with a full catalog of pre-generated content (watch guide, info card, season cards, footer).

The whole operation is observable and controllable from a **single, self-healing control-center channel**: live progress bars, request cards with inline buttons, per-episode **Stop**, whole-series **Cancel**, and a stuck-episode **recovery flow** (Retry / Switch source / Provide file).

> **Authorized use only.** NekoFetch is a private automation tool intended for content the operator is authorized to distribute. Treat it accordingly.

---

## Why it exists

Manually sourcing anime is tedious and fragile: streaming sites obfuscate their HLS segments, rotate CDN hosts, expire tokens, and sit behind Cloudflare. Doing it by hand means babysitting downloads, re-trying dead servers, juggling sub/dub and qualities, and re-encoding. NekoFetch automates **all** of it and — critically — does so **observably**:

- It never says a bare *"download failed."* Every failure is **classified** (dead host vs WAF block vs expired token vs rate-limit vs genuinely-missing) with a concrete reason.
- It **exhausts every server** before giving up, then offers **human recovery** rather than silently dropping an episode.
- A single broken episode **never blocks the rest of the series**.
- Work **survives restarts** — interrupted jobs resume from where they left off.

---

## Feature catalogue

### Discovery & confirmation
- **AniList-first search** with English + Romaji verification (so "Naruto" never resolves to a recap short).
- **Franchise aggregation** — walks the AniList relation graph to total seasons / movies / OVAs / ONAs / specials across the *whole* franchise.
- **Manga & unreleased filtering** — source manga/novels and not-yet-released entries are excluded from the tree and the counts (we're not a manga distributor, and we don't list vapor).
- **Accurate episode counts**, even for currently-airing shows (falls back to the aired-episode count via `nextAiringEpisode` instead of showing `?`).
- **Version picker** for titles with multiple distinct adaptations (e.g. *Hellsing* vs *Hellsing Ultimate*), with **Both** (one combined franchise request) and **Neither** options.
- **TMDB enrichment** — English/US-region backdrops & posters for the confirmation card and document thumbnails.

### Metadata & info cards
- **@acutebot integration** — primary metadata source for distribution bot info cards. Sends `/anime <title>` to @acutebot, parses the structured response (title, romaji, genres, rating, status, aired dates, runtime, episode count, synopsis), and **downloads the card photo** to a persistent directory for use as the info-card image.
- **Graceful fallback chain**: @acutebot → AniList → TMDB. If any source is unavailable, the next is tried automatically.
- **Strict title matching** — verified via exact English/Romaji matching before being passed to downstream sources.

### Sourcing & extraction
- **Multiple providers**: AniKoto, KickAssAnime, Nyaa (torrents), and a Telegram userbot index.
- **ffmpeg-free HLS engine** that locates and strips the fake-image masks streaming sites prepend to each `.ts` segment, byte-for-byte, producing a clean transport stream.
- **All servers tried** — every mirror/embed/CDN host is enumerated and attempted before an episode is declared unrecoverable.
- **Shared failure classification** across all providers — one diagnosis module, not per-provider band-aids.
- **Fast circuit-breaker** — a dead/flaky CDN (e.g. Cloudflare `521`) aborts in **under a second** and falls back to the next server instead of grinding for minutes.
- **Multi-quality** — discovers the real resolutions a stream offers (1080p/720p/480p…) and emits a variant per quality.
- **Dual-audio** — sub + dub, merged or cross-sourced (sub from one provider, dub from another) when needed.

### The download engine
- **Per-episode isolation** — one failed episode is recorded and retried later; it never aborts the job.
- **Retry with fresh metadata** — re-extracts new tokens / rotated hosts before giving up (recovers expired-token & dead-host failures automatically).
- **Resume after crash** — downloaded eps 1–9, crashed on 10 → restart resumes straight at 10.
- **Startup recovery** — orphaned `RUNNING` jobs from a killed process are reconciled so the active list reflects reality.
- **Stop** a single episode (skip it now, retry at the end) and **Cancel** the whole series (terminate + clean up) from the control center.
- **Rolling-window speed** — accurate MB/s & ETA, reported in real bytes (not segment counts).
- **Telemetry-safe** — a Redis/DB hiccup during progress reporting can never fail a download that's actually succeeding.

### Processing & delivery
- **Verify** (ffprobe corruption check), **rename** (template-driven), **metadata** tagging, **branding/watermark** (opt-in), **TMDB poster thumbnails**, and **store**.
- **Auto-upload** verified packs to a private storage channel, grouped by (season, resolution, audio), with the poster attached as the Telegram document thumbnail.
- **Publish** to a public main channel + maintain an **A–Z index channel**.
- **Distribution bots** with auto-generated content, temporary access links, and auto-deletion.

### Distribution bots
- **Auto-creation on publish** — when content is published, a dedicated Telegram bot is created (via BotFather) for the title, complete with a profile photo, description, and bound commands.
- **Auto-generated content** — each bot delivers a curated set of posts in order:
  1. **Watch guide** (pinned) — overview of seasons and available qualities
  2. **Info card** — full metadata from @acutebot (title, genres, rating, synopsis) with the AcuteBot photo as the card image
  3. **Season cards** — one per season, with quality buttons and language info
  4. **Footer** — branding/cross-promotion
- **Per-user delivery with auto-delete** — messages are delivered on-demand and automatically cleaned up after a configurable retention period. Grace extension: if the user interacts within the retention window, cleanup is pushed back.
- **Health checks** — the bot manager periodically checks all distribution bots. If a bot is banned or unreachable, it's **automatically recreated** from scratch (new BotFather flow, new avatar, re-generated content).
- **Admin controls** — manual recreate via the admin dashboard for instant recovery.

### Recovery & control (the stuck-episode flow)
When episodes can't be downloaded after retries, NekoFetch posts an **attention card** naming exactly which version failed (e.g. *Ep 2 · SUB / Ep 5 · DUB*) with:
- **🔁 Retry** — re-queue just those episodes.
- **🔀 Switch source** — checks the alternate provider's coverage and **explicitly** states whether it has the needed audio ("⚠️ KickAssAnime has no dub for this title") before switching.
- **📥 Provide file** — an admin sends the missing file via Telegram; it's ingested, published, and the upload copy is deleted.

### Observability
- A **self-healing control-center channel**: pinned dashboard, pending/active/completed/catalog sections, a rolling activity stream, and request cards — all edited in place.
- **Live progress** with quality + audio badges (`📺 S01E006 · 1080p · DUAL`), updated every few seconds.
- **Prominent failure cards** and a precise, classified reason for every failure.
- **Build-stamp at startup** so you can confirm a restart actually loaded new code.
- **Local time** — all displayed timestamps are in the configured display timezone (defaults to **Asia/Dhaka**, UTC+6).

### Main channel
- **TMDB English backdrop** as the primary post photo (16:9) — falls back to poster art if unavailable.
- **Franchise-wide synopsis** from TMDB (covers the entire franchise, not just a single season).
- **HTML-formatted captions** with `<blockquote>`, `<b>` tags matching the reference channel format.
- **Small-caps Unicode buttons** (`ɪɴᴅᴇx` / `ᴅᴏᴡɴʟᴏᴀᴅ`) — Index links to the A–Z index channel, Download deep-links to the title's distribution bot.
- Configurable via settings panel (caption template, button text, channel ID).

---

## The big picture — architecture

NekoFetch is a layered, async monolith running on a single event loop:

```
                         ┌─────────────────────────────────────────────┐
   Telegram users  ◄────►│  BOTS  (pyrogram clients)                    │
   Staff/owner     ◄────►│  • admin bot  • distribution bots            │
                         │  handlers → callback routing → FSM           │
                         └───────────────────┬─────────────────────────┘
                                             │ calls
                         ┌───────────────────▼─────────────────────────┐
                         │  SERVICES  (business logic)                  │
                         │  request · queue · download · publishing ·   │
                         │  storage/main/index channels · log-channel · │
                         │  analytics · access · distribution · auth …  │
                         └───────┬───────────────────────┬─────────────┘
                                 │                        │
              ┌──────────────────▼──────┐   ┌─────────────▼────────────┐
              │ SOURCES (extraction)    │   │ PROCESSING (pipeline)    │
              │ anikoto · kickassanime ·│   │ verify→rename→metadata→  │
              │ nyaa · telegram · _hls ·│   │ branding→watermark→thumb→│
              │ _diagnostics · _mux …   │   │ store                    │
              └─────────────────────────┘   └──────────────────────────┘
                                 │
              ┌──────────────────▼──────────────────────────────────────┐
              │ INFRASTRUCTURE                                           │
              │ PostgreSQL (jobs/requests/files)  ·  MongoDB (analytics/ │
              │ overrides/distribution)  ·  Redis (live progress, flags, │
              │ control-center layout, FSM)                              │
              └─────────────────────────────────────────────────────────┘
```

**Layer rules**: handlers call services; services orchestrate sources/processing/infrastructure; sources and processing are pure extraction/transformation; the **container** (`core/container.py`) is the dependency-injection root that owns every connection and client.

### Data stores, and what lives where
| Store | Holds |
|-------|-------|
| **PostgreSQL** | `users`, `requests`, `download_queue` (jobs), `files` (MediaFile), storage packs, distribution bots, bot content posts, channel posts — the durable record. |
| **MongoDB** | analytics events, runtime config overrides, distribution/access state. |
| **Redis** | live progress snapshots, control-center layout ids, Stop/Cancel/skip flags, stuck-episode state, FSM, discussion threads, per-user activity tracking. *(Ephemeral & self-healing.)* |

---

## The request lifecycle, end to end

```
 user: "Takopi's Original Sin"
   │
   ▼
 [1] AniList search ──► verify (EN+Romaji) ──► franchise graph (drop manga/unreleased)
   │                                            episode counts (aired-aware)
   ▼
 [2] Confirmation card (TMDB backdrop)  ──►  user confirms  ──►  RequestService.submit()
   │
   ▼
 [3] Request card posted to control center  (divider │ card │ divider │ card …)
   │     staff taps a source: Telegram / Website / Torrent
   ▼
 [4] QueueService.enqueue()  ──►  DownloadJob (QUEUED)
   │
   ▼
 [5] DownloadWorker picks it up ──► RUNNING
   │     for each episode → for each target resolution → for each audio:
   │        • resume-skip if already downloaded
   │        • extract variants (all servers) ──► download (de-mask HLS) ──► record MediaFile
   │        • failures isolated → retry pass (fresh metadata) → stuck → attention card
   ▼
 [6] Processing pipeline: verify → rename → metadata → branding → watermark → thumbnail → store
   │
   ▼
 [7] Auto-upload packs to storage channel (poster thumbnail attached)
   │
   ▼
 [8] (approval gate) ──► publish to main channel (TMDB backdrop + franchise overview)
   │                       + A–Z index
   │                       + auto-create distribution bot with content
   ▼
 [9] Distribution bot delivers: Watch guide → Info card (AcuteBot photo + metadata)
       → Season cards (quality buttons) → Footer (branding)
       → Auto-deleted after retention period (with grace extension)
```

---

## Sourcing & extraction engine

All web sources implement a common `AnimeSource` interface: `search → get_details → get_episodes → get_variants → download`.

### AniKoto (`sources/anikoto.py`)
- Resolves the watch page → episode list (the `/ajax/episode/list/{id}` endpoint, which **requires** an `x-requested-with` XHR header + same-site referer).
- Enumerates **multiple streaming servers** per episode from two pipelines (the Kiwi/mapper API and the site server list), de-base64'ing embed codes and extracting `getSources` manifests.
- Emits one variant **per real resolution** the master playlist offers, for both sub and dub.
- **Header hygiene**: the XHR marker rides only on the JSON/AJAX endpoints — never on the CDN segment fetches, where it would trip Cloudflare's bot detection (a real `<video>` tag never sends it). Browser-like `Accept` headers are sent on segments.

### KickAssAnime (`sources/kickassanime.py`)
- AES-256-CBC decryption of server payloads; JSON-API-first with a page-scrape fallback.
- Enumerates and **keeps every server** as a download-time fallback (lazily resolved), so a dead primary CDN doesn't fail the episode.

### The HLS engine (`sources/_hls.py`)
The heart of extraction. Many origins disguise each HLS segment with a junk header (a tiny fake PNG/JPEG plus padding) so naive downloaders save garbage. NekoFetch:
- locates the genuine MPEG-TS payload **byte-for-byte** (the real stream begins on a 188-byte packet boundary) and strips the mask — **no ffmpeg required**;
- fetches segments with bounded concurrency over a keepalive pool (yt-dlp-style concurrent fragments, in-process);
- verifies the assembled stream passes an end-to-end TS sync check before accepting it;
- discovers the qualities a master playlist offers (`list_master_qualities`).

### Torrents (`sources/nyaa.py`, `_torrent*.py`)
- Seeders-ranked, dual-audio-first picker with an auto-pick option.

### Telegram userbot (`sources/telegram/`)
- An AnimeFair-style index matched against AniList, plus a **manual pack** path where an admin supplies files directly.

---

## Reliability: how a download *refuses* to fail silently

This is a core design principle. The same failure modes occur on every site, so the diagnosis lives in **one** shared module (`sources/_diagnostics.py`).

### Failure classification
Every non-OK response or transport error is classified into a `FailureKind` with a concrete, human reason:

| Kind | Trigger | Recovery hint |
|------|---------|---------------|
| `DEAD_HOST` | `521/522/523`, connection refused/timeout | retryable; fall back to next server |
| `BLOCKED` | `403` + Cloudflare `cf-mitigated` / WAF | needs refresh (headers/cookie/fingerprint) |
| `EXPIRED` | `401`, token-looking `403` | re-extract fresh metadata |
| `RATE_LIMITED` | `429` | back off & retry |
| `SERVER_ERROR` | `5xx` | transient; retry |
| `NOT_FOUND` | `404/410` | genuinely gone on this server |
| `EXTRACTION` | no servers / 0 episodes produced | upstream extraction problem |

A failure is logged like `dead_host: HTTP 521 on cdn.example [server=cloudflare cf-ray=… cf-mitigated=challenge] — CDN origin unreachable` — **never** a bare "download failed."

### The circuit breaker
A healthy stream returns `200` on the first try, so it never accumulates retryable failures. A dead/flaky origin trips a small budget within ~1 second, captures the **first failure's classified signature**, and aborts — which is what lets the source fall back to the next server fast instead of grinding through hundreds of dead segments.

### Server exhaustion
Both AniKoto and KickAssAnime enumerate **every** server and try each (with classified per-server logging — `anikoto.server.try 1/3 host=…` → `anikoto.server.failed … falling back to next server`) before an episode is declared unrecoverable.

### Then — and only then — human recovery
If every server is exhausted, the episode goes to the [stuck-episode attention card](#feature-catalogue) (Retry / Switch source / Provide file). The series is **not** blocked; everything that downloaded proceeds to publish.

---

## Quality & audio policy

- **Target resolutions** (default `1080p, 720p, 480p`) are each fetched when the source offers them.
- **480p fallback ladder**: if 480p is missing, it falls back to `540p`, then `360p` — so the SD tier is never simply skipped.
- **Audio**: configured `languages` map to audio tracks — `english → dub`, `japanese → sub` (always with English subtitles). A request can pin a specific resolution/audio, or fan out into the full matrix.
- **Dual-audio** is built natively when a single dual track exists, or assembled (merge / separate / cross-source) when not.

> Downloading all qualities × sub+dub means up to **6 files per episode** — that's the policy by design. Trim `acquisition.target_resolutions` / `acquisition.languages` to taste.

---

## The download engine

`services/download_service.py` — `DownloadWorker` runs as a background loop on the event loop.

- **`run_forever`** claims the next queued job, runs it under a concurrency semaphore, and (on startup) calls **`recover_on_startup`** to reconcile orphaned jobs.
- **Per-episode isolation** — each `(episode, resolution, audio)` unit runs independently; failures are recorded, not raised.
- **Stop watcher** — each unit downloads under a watcher that polls Redis flags; an admin **Stop** cancels the current episode (it's retried at the end), a **Cancel** tears the whole job down.
- **Retry pass** — re-extracts fresh variants for failed units.
- **Resume** — `_already_have()` skips units whose verified file already exists on disk.
- **Telemetry-safe** — progress writes and flag polls are wrapped so a Redis/Upstash timeout never fails a real download.

Job states: `QUEUED → RUNNING → COMPLETED` (or `FAILED` / `CANCELLED` / `PAUSED`). Live progress mirrors to Redis (fast UI reads) and Postgres.

---

## The processing pipeline

`services/processing/` — ordered, independently-toggleable stages operating on a shared `StageContext`:

| Stage | Does |
|-------|------|
| **Verify** | ffprobe decode-probe; corrupt files fail the job (never ship garbage). |
| **Rename** | Template-driven naming (`title`, `season`, `episode`, `resolution`, `audio`, `group`). |
| **Metadata** | Title/branding tags via `mkvpropedit` (MKV) where available. |
| **Branding** | Caption/metadata-level branding. |
| **Watermark** | Opt-in video overlay (text/image) via ffmpeg. |
| **Thumbnail** | Fetches the **official TMDB poster** (English/US), fit to Telegram's 320×320 limit; falls back to an ffmpeg frame-grab. |
| **Store** | Marks files processed. |

External tools (ffmpeg/ffprobe/mkvpropedit) are **optional** — a missing tool records a note and the pipeline continues.

---

## Channels: storage, main, index & the control center

- **Storage (database) channel** — verified packs are auto-uploaded here, grouped by `(season, resolution, audio)`, each document carrying the poster as its Telegram thumbnail. Upload concurrency is tuned (`max_concurrent_transmissions`) for speed.
- **Main channel** — the public, user-facing channel where published anime are posted with:
  - **TMDB English backdrop** (16:9) as the post photo
  - **Franchise-wide synopsis** from TMDB (covers the whole franchise, not just one season)
  - HTML-formatted captions with `<b>` and `<blockquote>` tags
  - **[Index]** / **[Download]** buttons in small-caps Unicode
- **Index channel** — an auto-maintained A–Z index of everything published.
- **Distribution bots** — dedicated Telegram bots per title with auto-generated content (watch guide, info card with AcuteBot photo, season cards, footer), temporary access links, and auto-deletion with grace extension.

---

## Distribution bots

### Auto-creation
When content is published and `features.distribution_bots` is enabled, NekoFetch automatically:
1. Generates a bot name and username from the anime title
2. Drives a BotFather conversation via the userbot to create the bot
3. Sets a profile photo (TMDB poster, alternated rank to avoid same-image collisions)
4. Sets the bot description and about text
5. Registers the bot token, brings it online, and binds it to the title

### Auto-generated content
Each distribution bot delivers a curated set of posts in order:
1. **Watch guide** (pinned) — season listing with episode counts per season and available qualities
2. **Info card** — full metadata from **@acutebot** (title, romaji, genres, format, rating, status, synopsis) with the **AcuteBot photo** as the card image. Falls back to AniList + TMDB if @acutebot is unavailable.
3. **Season cards** — one per season, with quality buttons and language info. Supports flat layout (dual-audio) and separate-audio sections (English/Japanese).
4. **Footer** — cross-promotion branding card

### Health checks & auto-recovery
The bot manager runs a periodic health check (`bot.health_check_interval_minutes`). If a bot is banned or unreachable:
- A new BotFather flow is triggered to recreate the bot
- A new avatar is fetched
- Content is regenerated and re-bound
- Logged and surfaced in the admin panel

### Per-user delivery & privacy
- Messages are delivered on-demand when a user starts the bot
- Auto-deleted after `bot.delivery_retention_days` (configurable)
- **Grace extension**: if the user interacts within the retention window, cleanup is pushed back
- Force-subscribe gate can require joining channels before content delivery

---

## The log-channel control center

The control center (`services/log_channel_service.py`) is a fixed, ordered layout of **persistent, edited-in-place** messages:

```
[cover/intro]
──── 📊 CONTROL CENTER        (pinned; live stats + most-requested)
──── 📥 PENDING REQUESTS       (awaiting a source)
──── ⚙️ ACTIVE TASKS           (live downloads/processing; Stop + Cancel buttons)
──── ✅ RECENTLY COMPLETED
──── 🛰️ ACTIVITY STREAM        (rolling, expandable event log)
──── 📚 CATALOG                (pinned; everything published)
[request cards appear below, each preceded by a divider sticker]
```

- **Self-healing**: on every startup it verifies each section still exists; if the channel was wiped or changed, it tears down and rebuilds the whole layout, re-pins, and sweeps Telegram's pin notices.
- **Request cards** with inline source-selection buttons; a divider precedes each card and is cleaned up when the card is consumed (kept on assignment as the section separator, removed on reject).
- **Active tasks** render rich rows — title · episode · quality/audio · stage · progress bar · **speed · size · ETA** — and carry **Stop** and **Cancel** buttons.
- **Failure & attention cards** are posted prominently (not buried in the activity stream).
- **Human conversation** — staff messages are reformatted into a tidy signed conversation thread and auto-swept after idle.
- Two refresh lanes: a **fast** active-tasks lane (every few seconds) keeps the progress bar responsive; a slower full refresh updates the heavier panels.

---

## Localization

**Every** user-facing string lives in `resources/language/<code>.json` and is reached through `localization/messages.py` via a message **key** — never a hardcoded string.

- Edit a word/emoji/HTML in `en.json` and it propagates everywhere.
- **Auto-reload**: the catalog watches file mtimes and reloads within a couple of seconds — no restart, no `/reload` needed (though `/reload` forces it instantly).
- **Safe formatting**: a template that references a placeholder the call site doesn't supply renders the literal `{placeholder}` instead of crashing — so editing copy can never take the bot down.

---

## Configuration reference

NekoFetch reads **environment variables** (secrets/connections) and a **YAML config** (behavior, validated by Pydantic).

### Environment variables (`.env`)
| Variable | Purpose |
|----------|---------|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | Telegram app credentials. |
| `ADMIN_BOT_TOKEN` | The admin/control bot token. |
| `ADMIN_IDS` | Comma-separated owner/admin Telegram ids. |
| `POSTGRES_HOST` / `PORT` / `USER` / `PASSWORD` / `DB` | PostgreSQL connection. |
| `MONGO_URI`, `MONGO_DB` | MongoDB connection. |
| `REDIS_URL` | Redis connection (local recommended for low-latency progress writes). |
| `STORAGE_PATH`, `SESSION_PATH` | Working/download dir and pyrogram session dir. |
| `TMDB_API_READ_ACCESS_TOKEN`, `TMDB_API_KEY` | TMDB (backdrops/posters). |
| `SECRET_KEY` | Signing/crypto secret. |
| `AUTO_CREATE_SCHEMA` | Create tables on startup (dev convenience). |
| `LOG_LEVEL`, `LOG_JSON` | Logging verbosity/format. |
| `NEKO_TZ` | Display timezone (default `Asia/Dhaka`). |

### Config sections (Pydantic models in `core/config.py`)
`features` · `downloads` · `processing` · `rename` · `metadata` · `thumbnail` · `watermark` · `branding` · `distribution` · `queue` · `security` · `storage_channel` · `log_channel` · `access` · `shortlink` · `acquisition` · `main_channel` · `index_channel` · `sources` · `ui` · `localization` · `bot`.

Key knobs:
- `acquisition.target_resolutions` / `resolution_fallbacks` / `languages`
- `downloads.concurrent_downloads` / `retry_attempts` / `resume_interrupted` / `progress_update_interval_seconds`
- `log_channel.refresh_seconds` / `active_refresh_seconds` / `divider_sticker_id`
- `main_channel.caption_template` / `index_button_text` / `download_button_text`
- `bot.auto_create_on_publish` / `health_check_interval_minutes` / `delivery_retention_days`

---

## Installation & setup

### Prerequisites
- **Python 3.12+**
- **PostgreSQL**, **MongoDB**, **Redis** reachable
- *(optional)* **ffmpeg / ffprobe / mkvpropedit** on `PATH` (or in a project-local `tools/`) for verify/watermark/thumbnail/remux
- Telegram **API id/hash** + a **bot token**, and **TMDB** API keys

### Install
```bash
git clone https://github.com/arefin-raian/NekoFetch.git
cd NekoFetch

python -m venv .venv
source .venv/Scripts/activate     # Windows Git Bash;  use .venv/bin/activate on Linux/macOS

pip install -e .                  # editable install (so source edits apply on restart)
pip install -e ".[speedups,dev]"  # optional: native crypto speedup + dev tools
```

### Configure
```bash
cp .env.example .env              # then fill in credentials/connections
# edit your YAML config for behavior (channels, acquisition, etc.)
```

### Initialize the database
Set `AUTO_CREATE_SCHEMA=true` for first run, or run Alembic migrations.

---

## Running NekoFetch

```bash
python -m nekofetch        # or: nekofetch   (console script)
```

At startup you'll see a **build stamp** — the running version + git commit + commit time:

```
  NekoFetch 0.1.0  ·  build 1b8619c 2026-06-29 12:27
```

> **Use that stamp to confirm a restart actually loaded new code.** If the commit shown isn't the one you expect, you're running stale code — kill every running process and clear `__pycache__/` if needed.

---

## Admin commands

Registered in the Telegram "/" menu (admin/owner only):

| Command | Action |
|---------|--------|
| `/start`, `/help` | Panel & help. |
| `/cancel` | Cancel the current interactive flow. |
| `/reload` | Re-read `en.json` from disk instantly (auto-reload also runs in the background). |
| `/cleardownloads` | **Owner** — cancel every active/queued/stuck/orphaned download and clear live progress. The cure for a "ghost" active task. |
| `/resetoverrides` | **Owner** — clear Mongo runtime config overrides so YAML config wins again. |

**Inline controls** (control-center buttons): assign source · reject · per-episode **Stop** · whole-series **Cancel** · stuck-episode **Retry / Switch source / Provide file** · bot **Recreate / Create**.

---

## Operations & diagnostics

Reusable scripts in `scripts/` (run from the repo root with the venv active):

| Script | Purpose |
|--------|---------|
| `python scripts/clear_downloads.py` | Immediately cancel all active/stuck download jobs + clear live progress (the ghost-killer, runnable before a restart). |
| `python scripts/clear_database.py [--yes]` | **Wipe all data except users** — truncates Postgres (keeps `users`), empties Mongo, deletes `nf:*` Redis keys. |
| `python scripts/diag_anikoto.py "<title>"` | Drive AniKoto's real extraction against the live site and probe a segment (old vs new headers) — proves where/why a fetch fails. |
| `python scripts/diag_kickass.py "<title>"` | Same, for KickAssAnime. |
| `node scripts/diag_browser.js [url]` | Capture the **real browser's** network requests (via Playwright) to compare against our extraction — invaluable when a site changes its API. |

Additional diagnostic scripts in `playground/`:

| Script | Purpose |
|--------|---------|
| `python playground/probe_acutebot.py <title>` | Test @acutebot metadata fetch + photo download end-to-end. |
| `python playground/probe_mainchannel.py <anime_doc_id>` | Test main channel publishing flow (facts, caption, buttons). |
| `python playground/probe_enrich.py` | Compare AniList vs TMDB enrichment (backdrop language tags, synopsis source). |
| `python playground/probe_card.py` | Preview franchise confirmation cards. |

These were the tools used to root-cause real production issues (a changed episode-list endpoint, a Cloudflare `521` host, a header that tripped a WAF) — keep them; they pay for themselves the next time a site shifts.

---

## Testing

```bash
pytest -q                 # full suite (115 tests)
pytest -q tests/test_download_isolation.py    # one module
ruff check .              # lint
mypy src                  # types
```

The suite covers franchise totals, parsing, dual-audio strategy, the control-center self-heal, download isolation (Stop/Cancel/normal), caption budgets, permissions/security, templates, progress, bot content generation, bot orchestration, distribution delivery, and more — all offline with fakes, so it runs anywhere.

---

## Project layout

```
NekoFetch/
├── src/nekofetch/
│   ├── __main__.py            # entry point (boots container + bot manager; build stamp)
│   ├── core/                  # container (DI), config, logging, constants, timefmt
│   ├── domain/                # enums (JobStatus, RequestStatus, AudioType, …)
│   ├── bots/
│   │   ├── admin/             # control bot: handlers (requests, review, commands, settings…)
│   │   ├── distribution/      # delivery bots (content posts, buttons, force-sub, access)
│   │   ├── manager.py         # starts clients + workers + scheduler + health checks
│   │   ├── fsm.py             # Redis-backed conversation state
│   │   ├── force_sub.py       # channel join gate
│   │   └── middleware.py      # auth middleware
│   ├── services/              # business logic (download, queue, publishing, channels, …)
│   │   ├── bot_content.py     # content generation (watch guide, info card, season cards)
│   │   ├── bot_factory.py     # BotFather-driven bot creation
│   │   ├── bot_management.py  # bot registration, encryption, bind/rebind
│   │   ├── bot_orchestrator.py# bot lifecycle coordination
│   │   ├── bot_naming.py      # name/username generation
│   │   ├── main_channel_service.py  # public channel publishing
│   │   ├── index_channel_service.py # A–Z index maintenance
│   │   └── processing/        # the stage pipeline (verify→…→store)
│   ├── sources/               # extraction: anikoto, kickassanime, nyaa, telegram,
│   │   │                       #   _hls (de-mask engine), _diagnostics (classification),
│   │   │                       #   _mux/_subs/_dualaudio/_transcode/_normalize
│   │   └── telegram/          # userbot index + manual pack + AniList client
│   ├── providers/             # metadata (acute_bot, tmdb, anilist), shortlink
│   ├── infrastructure/
│   │   ├── database/          # postgres (models/session), mongo, redis (progress store)
│   │   └── repositories/      # queue, request repositories
│   ├── localization/          # i18n loader (auto-reload, safe-format) + message keys
│   └── ui/                    # pure render builders (screens, components, log sections,
│                               #   progress bars, website report)
├── resources/language/        # en.json (and any other locales)
├── scripts/                   # ops & diagnostics (above)
├── playground/                # interactive probe scripts for testing
├── tests/                     # offline test suite (115 tests)
├── pyproject.toml
└── README.md                  # you are here
```

---

## Tech stack

| Concern | Choice |
|---------|--------|
| Telegram | **Pyrogram (pyrofork)**, optional TgCryptoX native speedup |
| Language | **Python 3.12+**, fully `async` |
| Relational DB | **PostgreSQL** via SQLAlchemy 2 (async) + Alembic |
| Document DB | **MongoDB** via Motor |
| Cache / live state | **Redis** |
| Scheduling | **APScheduler** |
| Config / validation | **Pydantic** v2 + pydantic-settings + YAML |
| HTTP | **httpx** (async, HTTP/2 capable) |
| Scraping | **BeautifulSoup4**, custom HLS engine, **yt-dlp** (where applicable) |
| Crypto | **cryptography** (AES for KickAssAnime payloads) |
| Logging | **structlog** |
| Media tools | **ffmpeg / ffprobe / mkvpropedit** (optional) |
| Diagnostics | **Playwright** (browser network capture) |
| Lint / types / tests | **ruff**, **mypy**, **pytest** (+ asyncio) |

---

## Troubleshooting

**"It's still running the old code after I edited/restarted."**
Check the **build stamp** printed at startup (`NekoFetch x.y.z · build <commit> <date>`). If it isn't the commit you expect: (1) make sure you actually killed the running process (a backgrounded/`service` process won't restart on its own); (2) confirm you're on an **editable install** (`pip install -e .`); (3) delete `__pycache__/` directories if you suspect stale bytecode. `en.json` text edits auto-reload without a restart.

**A "ghost" download shows as active but nothing is downloading.**
A job was left `RUNNING` by a killed process. Run `python scripts/clear_downloads.py` (or `/cleardownloads`), then restart — startup recovery keeps the active list honest from then on.

**Segments return `521`.**
That's a **dead CDN host** (Cloudflare can't reach origin), not your bug. The circuit-breaker now bails in ~1s and the source falls back to the next server. If *every* server is down for that title right now, you'll get a stuck-episode card — retry later or use Switch source / Provide file. (Use `scripts/diag_anikoto.py` to confirm against the live site.)

**Episodes marked "failed" that clearly downloaded.**
Almost always a **Redis/Upstash timeout** during progress writes. Telemetry is now wrapped so it can't fail a download — but a **local Redis** is strongly recommended over a remote one for low-latency progress.

**Times look wrong.**
Displayed times use `NEKO_TZ` (default `Asia/Dhaka`, UTC+6). Storage is always UTC. Set `NEKO_TZ` to your IANA zone to change the display.

---

## Glossary

- **Franchise** — the whole connected set of AniList entries for a title (seasons + movies + OVAs/ONAs/specials), with manga/unreleased excluded.
- **Variant** — a specific (resolution, audio, container) of an episode from a source.
- **Candidate / server** — one of several streaming mirrors a source exposes for an episode.
- **De-masking** — stripping the fake-image header obfuscating an HLS segment to recover the real transport stream.
- **Stuck episode** — one that couldn't be downloaded after retries across all servers; surfaced on an attention card for human recovery.
- **Control center** — the staff log channel where the whole operation is observed and driven.
- **Distribution bot** — a dedicated Telegram bot per anime title that delivers curated content (watch guide, info card, season cards).
- **AcuteBot provider** — primary metadata source that fetches anime info by interacting with @acutebot via the userbot pool.

---

<div align="center">

*Built for reliability: every server tried, every failure named, every restart survived.*

🐾

</div>
