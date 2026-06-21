# NekoFetch — Deployment & First-Run Guide

End-to-end setup, from zero to a running admin bot serving content. Two paths: **Docker
Compose** (recommended) and **local/manual**.

> **Authorized use:** NekoFetch distributes content you own or are licensed to distribute.
> The metadata scraper and any content source must point at sources you're authorized to use.

---

## 1. Prerequisites

- A server or machine with Docker + Docker Compose (or Python 3.12+ for manual setup).
- `ffmpeg` and `mkvtoolnix` (bundled in the Docker image; install locally otherwise).
- Telegram **API credentials**: create an app at https://my.telegram.org → note `api_id` + `api_hash`.
- An **admin bot** token from https://t.me/BotFather.
- Your own Telegram **user id** (message https://t.me/userinfobot).

---

## 2. Configure `.env`

```bash
cp .env.example .env
```

Fill in (minimum to boot):

| Variable | Value |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | from my.telegram.org |
| `ADMIN_BOT_TOKEN` | BotFather token for the management bot |
| `ADMIN_IDS` | your Telegram user id (comma-separated for several) |
| `SECRET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `POSTGRES_*`, `MONGO_*`, `REDIS_URL` | defaults work as-is under Docker Compose |
| `AUTO_CREATE_SCHEMA` | `true` for first run; set `false` once you adopt Alembic (step 5) |

`config.yaml` holds behaviour (feature toggles, branding, distribution rules); review it but
the defaults are sensible. Most of it is also editable live from the in-bot settings panel.

---

## 3. Start the stack (Docker)

```bash
docker compose up -d        # postgres, mongo, redis, nekofetch
docker compose logs -f nekofetch
```

You should see `container.startup` then `bots.admin.started`. Open your admin bot in
Telegram and send `/start` — you'll get the premium welcome with the staged loading
animation. Because your id is in `ADMIN_IDS`, you'll see the **Admin Panel** button.

### Manual (no Docker)

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
# ensure Postgres, MongoDB, Redis are running and reachable per your .env
python -m nekofetch
```

---

## 4. First-run checklist (in the admin bot)

1. `/start` → **Admin Panel**.
2. **Settings** → toggle features on/off (applies live, persists to MongoDB).
3. **Staff** → **Add Staff** to promote helpers by user id; ban/unban users here too.
4. Submit a test **Request Anime** as a user to confirm the request → queue flow.

---

## 5. Database migrations (production)

For the first run, `AUTO_CREATE_SCHEMA=true` creates the tables automatically. For
production, manage the schema with Alembic instead:

```bash
# set AUTO_CREATE_SCHEMA=false in .env, then:
alembic upgrade head                       # apply the baseline + any later revisions
# when you change models later:
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

(Inside Docker: `docker compose exec nekofetch alembic upgrade head`.)

---

## 6. Log channel setup

1. Create a Telegram **channel** for logs.
2. Add your **admin bot** as an **administrator** (needs post + edit + pin rights).
3. Get the channel id (e.g. forward a channel message to https://t.me/userinfobot, or use
   the `-100…` id).
4. In `config.yaml`:
   ```yaml
   log_channel:
     enabled: true
     channel_id: -100XXXXXXXXXX
     pinned_dashboard: true
     pinned_catalog: true
     refresh_seconds: 60
   ```
5. Restart. On startup NekoFetch posts + pins a **live stats dashboard** and a **catalog
   index**, both auto-updated, and every event streams into the channel.

---

## 7. Database (storage) channel setup

This is where content lives as ordered packs (`header → files → end sticker`).

1. Create a Telegram **channel** for storage and add the **admin bot** as an administrator.
2. (Optional) Pick an **end-of-pack sticker** and get its `file_id` — send the sticker to a
   bot like @idstickerbot, or log it once via the bot.
3. In `config.yaml`:
   ```yaml
   storage_channel:
     enabled: true
     channel_id: -100YYYYYYYYYY
     header_template: "{title} — Season {season} [{resolution}] [{language}]"
     end_sticker_id: "CAACAg...."       # optional but recommended
     copy_mode: copy
   ```
4. **Ingest content** two ways:
   - **Automated** — when you **Publish** an approved request, NekoFetch uploads its files in
     order (header → files → end sticker) and records the pack.
   - **Assisted** — post content to the channel yourself, then **Admin Panel → Storage →
     Index Pack** and send:
     ```
     anime_ref | season | resolution | language | start_id | end_id
     # e.g.  naruto-shippuden | 1 | 1080p | dual | 1201 | 1705
     ```
     (language = sub / dub / dual; ids are the channel message range.)

Delivery copies a pack's messages to the user, honoring `distribution.protect_content`,
temporary links, and auto-delete.

---

## 8. Distribution bots

1. Create a public bot with @BotFather (e.g. *Naruto Shippuden 1080p*).
2. **Admin Panel → Bots → Add Bot**, paste the token. It's encrypted at rest and goes live
   immediately.
3. (Optional) **Bind title** so the bot opens directly on one anime.
4. (Optional) Enable **force-subscribe** in `config.yaml` (`security.force_subscribe` +
   `force_subscribe_channels`) to require users join your channels first.

---

## 9. Metadata enrichment (optional)

To show rich anime info cards (synopsis, genres, stats, characters, artwork), implement the
four `fetch_*` methods in `src/nekofetch/providers/metadata/scraper.py` against an authorized
source and set `implemented = True`. Until then, bots show basic metadata. See
`docs/SCRAPER_GUIDE.md`.

---

## 10. Operations

- **Logs:** `docker compose logs -f nekofetch` (and your Telegram log channel).
- **Backups:** persist the `pgdata`, `mongodata`, and `storage` volumes.
- **Sessions:** Pyrogram session files live in the `sessions` volume — keep them to avoid
  re-login.
- **Updating:** `git pull` → `docker compose build` → `alembic upgrade head` → `docker
  compose up -d`.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Bot doesn't respond to `/start` | wrong `ADMIN_BOT_TOKEN`, or DBs not reachable (check logs) |
| No Admin Panel button | your id isn't in `ADMIN_IDS` |
| Log channel silent / no pins | bot isn't a channel admin, or wrong `channel_id` |
| Indexing/delivery fails | admin bot isn't an admin of the storage channel, or bad message range |
| Metadata cards not showing | scraper `implemented` is still `False` (expected until you implement it) |
