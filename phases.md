# NekoFetch — Implementation Phases

> This document reflects the **current codebase state**, not a roadmap. Each phase describes what's actually implemented.

---

## Phase 1: User Request — AniList-First Discovery

**Source files:** `requests.py`, `screens.py`, `anilist.py` (`sources/telegram/`), `tmdb.py` (`providers/metadata/`), `series.py` (`providers/metadata/`), `artwork.py` (`ui/`)

### Search Flow
1. User taps "Request Anime" → FSM state set to `req:await_name`.
2. User types an anime name → `_search_anilist()` fires.
3. **AniList GraphQL query** fetches the best match — full metadata, synopsis, genres, score, studio, cover/banner artwork, and complete relation graph (sequels, prequels, side stories, spin-offs, alternatives).
4. If AniList returns nothing → **TMDB fallback** (`/search/tv` → `/search/movie`, TV preferred). Builds a minimal franchise entry from TMDB data.
5. If both fail → "not found" message, user retries.

### Adaptation Detection
- `SeriesResolver.resolve()` compares the base entry's title tokens against each relation's title tokens.
- **Sequel/prequel with season-marker titles** (e.g. "Attack on Titan Season 2", "Demon Slayer: Mugen Train Arc") → collapsed into the same series.
- **Distinctly named TV continuations** (e.g. "Naruto Shippuuden", "Fullmetal Alchemist: Brotherhood") → split into separate versions. Only TV/TV_SHORT continuations qualify — one-off ONA/short prequels (One Piece "MONSTERS") stay as extras.
- **ALTERNATIVE** relations → a separate version when substantial: any TV/TV_SHORT adaptation (Fullmetal Alchemist 2003), or an OVA/ONA with ≥2 episodes (Hellsing Ultimate). Single-episode pilots/recaps/PVs (One Piece "Romance Dawn") are excluded.
- Title resolution is **English-first** so versions display their proper names ("Hellsing Ultimate", not romaji "HELLSING OVA").
- Candidate selection (`_best_id`) prefers an **exact primary-title match** over raw popularity, so "Hellsing" resolves to the TV series even though the OVA is more popular.
- If multiple versions detected → `choose_version()` screen shows selectable options.
- If single version → skip picker, show confirmation card directly.

### Confirmation Card (Photo + Caption)
Rendered via `confirm_franchise()` → returns a `Screen` with image + caption + inline keyboard.

**Image priority:** TMDB backdrop URL → AniList banner URL → AniList cover URL → local `pick_artwork()` (random 16:9 art from `images/`).

**Sent as a photo message:** `_send_screen()` helper in `requests.py` deletes the old text progress message and sends `client.send_photo()` with the screen's image (URL or local Path).

**Caption content:**
- Title + year
- Format (TV/TV_SHORT/MOVIE/OVA/ONA/SPECIAL), status (FINISHED/RELEASING), score (/10), studio, genres (top 5)
- **Synopsis** — TMDB synopsis preferred (better franchise-level overview), falling back to AniList description. Truncated at 300 chars with "… `<a href='https://anilist.co/anime/{id}'>Read More</a>`"
- **Franchise breakdown:** total episodes (main + continuation seasons), seasons count, movies, OVAs, ONAs, specials — counted from *content* relations only (source manga, character shorts and OTHER noise excluded)
- **Related entries** in `<blockquote expandable>` — curated franchise content only (sequels, prequels, side stories, alternatives, spin-offs, parent, summaries), English titles + format + episode counts, capped at 15
- Buttons: "✅ Yes, that's it" / "❌ Not this"

### Franchise-Level Model
- Confirmed request is registered with `DownloadScope.ENTIRE_SERIES` and `franchise_data` JSONB blob containing:
  - `anilist_id`, `source`, `query`, `title`, `year`, `format`
  - `franchise_episodes`, `franchise_seasons`, `franchise_movies`, `franchise_ovas`, `franchise_onas`, `franchise_specials`
  - Full `relations` array (relation type, format, episodes, titles, anilist_id)
  - `genres`
- Request status → **PENDING** (awaits staff review).
- Log channel event: `request.submitted` with code, anime, user, scope, franchise_seasons, relations count.

### User Rejection
- "Not this" → FSM reset to `req:await_name`, user can retry with a different query.

---

## Phase 2: Staff Review & Source Assignment

**Source files:** `review.py`, `request_service.py`, `queue_service.py`, `en.json` (localization)

### Review List
- Staff opens "Review Requests" → paginated list (8 per page) of PENDING requests.
- Each entry: `#REQ-10XX · Anime Title`.
- Tap to see detail panel.

### Source Selection
Detail panel shows: anime title, status, scope, current source, requester user ID.

**Button layout (two rows):**
1. **📨 Telegram** · **🌐 Website** · **🧲 Torrent**
2. **❌ Reject**

**Telegram sub-flow:**
- **🤖 Automatic** → updates source to `"telegram"`, calls `QueueService.enqueue()`.
- **✋ Manual** → FSM state `staff:await_manual`, prompts admin to send episode pack files. Any text message triggers `_manual_input()` → updates source to `"telegram_manual"`, enqueues.

**Website sub-flow:**
- Admin picks provider priority: **AniKoto (primary) → KickAssAnime** or **KickAssAnime (primary) → AniKoto**.
- Source stored as `"anikoto>kickassanime"` (or vice versa). Enqueued.

**Torrent:** Updates source to `"torrent"`, enqueues directly.

**Reject:** `RequestService.reject()` → status REJECTED. Log channel: `request.rejected`.

All actions logged to log channel.

---

## Phase 3: Download & Processing

**Source files:** `download_service.py`, `queue_service.py`, `pipeline.py`, `stages.py`, `notification_service.py`, `log_channel_service.py`

### Queue
- `QueueService.enqueue()` creates `DownloadJob` row, status QUEUED, request status → QUEUED.
- Log channel: `queue.enqueued`.
- Dashboard (`QueueService.dashboard()`) reads Redis progress snapshots for live data.

### Download Worker
- `DownloadWorker.run_forever()` — background loop, polls Postgres for next QUEUED job every 2s.
- Semaphore limits concurrent downloads (`concurrent_downloads` config).
- Claims job → status RUNNING → resolves source plugin → gets episodes → fans out across (resolution × audio) combinations.
- **Per-variant download:** Retry with backoff (`retry_attempts` × `retry_backoff_seconds`). Resume support via `resume_state`.
- **Live progress** pushed to Redis `ProgressSnapshot` every 0.5s: job_id, status, progress%, speed, downloaded/total bytes, current episode, ETA.
- Each downloaded file → `MediaFile` row recorded.
- On complete → status COMPLETED, request → PROCESSING.
- On failure → status FAILED, error stored. User notified via `NotificationService.download_failed()`.
- Log channel: `download.complete` or `error.download_failed`.

### Processing Pipeline
- `ProcessingPipeline.run_for_job()` runs configured stages in order:
  1. **Verify** — checks file integrity.
  2. **Rename** — standardizes filenames.
  3. **Metadata** — enriches with provider metadata.
  4. **Branding** — applies bot branding.
  5. **Thumbnail** — generates thumbnail.
  6. **Store** — writes to storage.
- Each stage logged to log channel: `processing.{stage_name}`, `processing.{stage_name}_done`, or `error.{stage_name}_failed`.
- If `require_approval_before_publish` → request status → **READY**.
- If auto-publish → request → **PUBLISHED**, all files marked published.
- User notified: `NotificationService.processing_complete()` with approval-gate info.

---

## Phase 4: Publish & Deliver

**Source files:** `publishing_service.py`, `approvals.py`, `main_channel_service.py`, `index_channel_service.py`, `storage_channel_service.py`, `distribution_service.py`, `notification_service.py`

### Approval Gate
- Staff opens "Approvals" → `PublishingService.list_ready()` returns READY requests with summary: title, file count, resolution, audio, thumbnail status.
- Actions: **Publish** / **Reprocess** / **Cancel**.

### Publishing (`PublishingService.publish()`)
1. Marks all `MediaFile` rows as `published = True`.
2. Request status → PUBLISHED.
3. Records analytics event (`publish`).
4. **Storage pack upload** — groups files by (season, resolution, audio) → `StorageChannelService.upload_pack()` posts header + files in order + end sticker to storage channel, records `StoragePack` row.
5. **Main channel post** — `MainChannelService.publish()` posts content card with captions + inline buttons to distribution channel.
6. **Index refresh** — `IndexChannelService.refresh_letter()` updates the alphabetical index.
7. Log channel: `publish.approved` with code, anime, file count, audio, resolution.
8. **User notification** — `NotificationService.request_published()` DMs the user.

### Delivery
- Distribution bot (`distribution/app.py`) handles user access:
  - **Pack delivery** — `StorageChannelService.deliver()` copies storage pack messages (header + files + end sticker) to the user.
  - **Access link** — `DistributionService.create_access_link()` generates a temporary token → sends to user.
- Auto-delete after `auto_delete_after_minutes` (scheduler).

---

## Infrastructure

### Database
- **PostgreSQL** (relational backbone): `User`, `Request` (with `franchise_data` JSONB), `DownloadJob`, `MediaFile`, `DistributionBot`, `AccessLink`, `StoragePack`, `ChannelPost`, `AccessToken`, `AnalyticsEvent`, `AuditLog`.
- **MongoDB** (flexible content): `anime`, `artwork`, `settings`, `message_templates`, `processing_profiles`, `source_cache`.
- **Redis**: Live progress snapshots (`ProgressSnapshot`), log channel pin tracking, FSM state storage, rate limiting.

### Bot Architecture
- **Admin bot** (`bots/admin/`): User-facing request flow, staff review/source assignment, approval panel, settings, storage admin, bot management, broadcast, help/commands.
- **Distribution bot** (`bots/distribution/`): User-facing access to published content, pack delivery, access links.
- **Bot manager** (`bots/manager.py`): Loads all bots, handles retry resolution for channels, startup alerts to owner.
- Forced subscription middleware (`bots/force_sub.py`).

### Log Channel (Operational Control Center)
`LogChannelService` — every event logged with category glyphs:
- `request.*` — submitted, source_assigned, rejected
- `queue.*` — enqueued
- `download.*` — complete
- `processing.*` — stage progress, done/failed
- `publish.*` — approved
- `delivery.*` — (for future use)
- `admin.*`, `bot.*` — administrative/bot events
- `error.*` — download_failed, processing_failed
- `system.*` — general

Pinned dashboard (live analytics: users, downloads, queue, failed, published, most requested) and pinned catalog (published titles with seasons).

### UI Layer
- `screens.py` — Pure builder functions returning `Screen` (caption + image + keyboard). No Telegram I/O.
- `typography.py` — `bq()` (blockquote), `bqx()` (expandable blockquote), `heading()`.
- `progress.py` — `bar()` (progress bar), `loading_animation()`, `staged_loading()`.
- `artwork.py` — Random 16:9 art picker, no back-to-back repeats.
- `components.py` — `cb()` (callback data builder), `keyboard()`, `paginate()`.
- All strings centralized in `localization/messages.py` + `resources/language/en.json` (150+ keys). HTML parse mode throughout.
