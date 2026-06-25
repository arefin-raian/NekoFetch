# NekoFetch — Telegram Userbot Source Report

**Date:** 2026-06-25
**Modules:** `src/nekofetch/sources/telegram/` — `userbot.py`, `anilist.py`,
`matching.py`, `animefair.py`, `packs.py`, `source.py`
**Runtime:** pyrofork (pyrogram 2.3.69), user session (not a bot account)

A Telegram-channel source, preferred over streaming/torrent sources when the
requested anime exists in the AnimeFair index.

> **LIVE-VALIDATED (session provisioned).** A user session was provisioned and
> the **entire pipeline was run end to end against the real bot/channels**:
> login → fetch index (146 anime) → Anilist match → join channel → discover packs
> → download a file → normalize. Findings from that live run are folded in below.

### Live run — what the real data revealed

- **The index bot is menu-driven, not search.** Free-text queries return
  "Unknown Command". `/start` returns a sticker + **multi-part text messages**
  ("Index of Anime Fair (1)/(2)/(3)") where each anime name is a **TEXT_LINK
  entity** → `t.me/<channel>` (public username *or* `t.me/+invite` for private).
  Fix applied: parser now reads **entities**, and `lookup` pulls the **whole
  index once** and matches locally (146 anime parsed live).
- **Acronym matching bug found & fixed.** "Attack on Titan" wrongly matched
  "Ao Ashi" because the Anilist synonym **"AoT"** camel-split to `{ao}` and
  collided. Added `meaningful_variants()` to drop acronym/too-short variants.
  Post-fix: AoT/JJK/Demon Slayer/Death Note/One Piece all resolve correctly;
  un-indexed titles (Bocchi) return nothing → clean fallback.
- **Real channel layout** (live): files are **documents** named
  `Ao Ashi - S1 E01 [Dual] 1080p @Anime_Fair.mkv`, posted per resolution
  (1080p, then 720p, then 480p), with a header text and promo photo/"how to
  watch" video as noise. Discovery handled it: **24 episodes × {1080p,720p,480p}
  dual-audio**, noise → `unresolved`.
- **Download + normalize, live**: Ao Ashi S1E01 480p (45 MB) downloaded via the
  user session and normalized → container `Anime Weebs #1 - @AniXWeebs`, audio
  `English - @AniXWeebs` / `Japanese - @AniXWeebs`, subs `English - @AniXWeebs`
  (identical tracks deduped).

---

## 1. Userbot infrastructure (`userbot.py`)

A **pool of user accounts** with automatic selection + graceful fallback:

- `UserbotPool(api_id, api_hash, accounts)` / `from_env(...)` — one account today
  (`TELEGRAM_USERBOT_SESSION`), arbitrarily many via `TELEGRAM_USERBOT_ACCOUNTS`
  (JSON list of `{name, session_string}`).
- `acquire()` starts the first account that logs in successfully; failures
  (auth/flood/ban) roll to the next.
- `execute(fn, retries=…)` runs an operation on a working client and **falls back
  to another account** if it dies mid-operation (flood-wait, session death).
- Same pool is the **control layer for future automation** (creating/renaming
  bots, setting commands) — actions a bot account can't perform.

Verified: pyrofork `Client` supports `session_string`, `join_chat`,
`get_chat_history`, `download_media`; the pool imports and constructs lazily
(no connection until first use).

---

## 2. Anilist metadata + flexible matching (`anilist.py`, `matching.py`) — LIVE TESTED

**Matching is never exact-string.** A title reduces to its set of meaningful word
tokens (camelCase split, every separator normalized, quality/format noise &
stopwords dropped). All separator variants match:

`Attack on Titan` ≡ `Attack-on-Titan` ≡ `AttackOnTitan` ≡ `Attack_On_Titan` ≡
`Attack on Titan S01 1080p Dual Audio` → **match**; `Demon Slayer` → **no match**.

**Anilist** expands one query into every title we might see on Telegram. Live
results:

| Query | Titles | Synonyms | Relations | Variants |
|---|---|---|---|---|
| Attack on Titan | Shingeki no Kyojin / Attack on Titan / 進撃の巨人 | SnK, AoT, … | 11 (2 sequels/prequels, 3 movies) | **47** |
| Frieren | Sousou no Frieren / Beyond Journey's End / 葬送の… | Frieren at the Funeral, … | 6 | 32 |
| Kaguya-sama | …wa Kokurasetai / Love is War / かぐや様… | … | 2 | 19 |

Payoff: a channel that names the show **"Shingeki no Kyojin S2"** still matches a
**"Attack on Titan"** query via the variant set — verified.

---

## 3. AnimeFair index + channel entry (`animefair.py`)

- **`lookup(title)`** — messages @AnimeFair_Index_Bot with the Anilist-expanded
  names, reads the reply, and extracts `(anime → channel)` entries from **both
  inline-keyboard buttons and message text**. Verified on synthetic replies of
  both shapes.
- **Channel-link normalization** (verified): `@user`, `t.me/user`,
  `t.me/+hash`, `t.me/joinchat/hash` → canonical ref + an `is_invite` flag.
- **`find_channel(title)`** — picks the entry whose name best matches the query
  variants (separator-proof, ≥0.6/0.8 thresholds).
- **`enter_channel(entry)`** — `join_chat`; on a private channel it catches
  `InviteRequestSent` and reports **`pending`** ("retry after approval"); already
  a member → `joined`; public resolvable → `public`. `is_member()` re-checks
  after approval. (pyrogram error classes confirmed present.)

---

## 4. Pack-structure discovery (`packs.py`) — UNIT TESTED

Builds a generalized catalog from a channel's media messages (filename **and**
caption), reusing the release-name heuristics. Verified on a mixed synthetic
channel:

```
seasons: { 1: {episodes:2, resolutions:[480p,720p,1080p], range:[1,2]},
           2: {episodes:2, resolutions:[1080p],          range:[1,2]} }
movies: 1   specials: 2   packs: 1   unresolved: 1
```

- **Resolution variants** grouped per episode (S1 EP1 → 480p/720p/1080p).
- **Multi-season** split (`S02E01` ≠ season 1).
- **Season packs** (`[Batch]`, `.zip`, `01-25`) detected as `pack`.
- **Movies / specials / OVAs** classified and set aside.
- **Ambiguous** items (e.g. a stray thumbnail) go to `unresolved` for
  **escalation to channel maintainers** rather than being mis-filed.

---

## 5. TelegramSource + priority (`source.py`)

Implements the `AnimeSource` interface, registered in the source registry:

- `search(query)` → returns a stub **only if the index has the anime**; otherwise
  empty, so the orchestrator falls back to Nyaa / KickAssAnime / AniKoto.
- `get_episodes` → enters the channel, scans up to `history_limit` media messages,
  runs discovery, and exposes seasons → EP1..EPN + movies/specials.
- `get_variants` → one variant per resolution (highest first).
- `download` → fetches the chosen message's media via the user session.

**Priority:** placing `telegram` first in the orchestrator's source list makes it
preferred whenever a release exists there; its empty `search` result on a miss is
the graceful hand-off to the other sources (the §`download_with_fallback`
mechanism).

---

## 5b. Release normalization (`_normalize.py`) — TESTED

Every downloaded file is normalized so all user-facing metadata is our branding,
language info preserved where reliable. Verified on a real 9-subtitle / 2-audio MKV:

- **Captions/title replaced** → container title `Anime Weebs #1 - @AniXWeebs`,
  source metadata stripped (`-map_metadata -1`).
- **All embedded text subtitles extracted** (ASS/SRT/VTT/mov_text → VTT), image
  subs (PGS/VOBSUB) skipped and reported.
- **Each subtitle processed** with the shared pipeline (watermark strip + our
  styling + branding in the longest gap, last-3-min excluded) → only **our**
  `.ass` tracks are re-muxed; originals dropped.
- **Language detection** (tag first, else content analysis by script + function
  words): verified en/ja/hi/es. 
- **Naming policy** applied to subtitle **and** audio track titles + metadata:
  | Case | Title |
  |---|---|
  | known sub/audio language | `English - @AniXWeebs`, `Japanese - @AniXWeebs`, `Hindi - @AniXWeebs` |
  | subtitle language unknown | `@AniXWeebs` |
  | audio language unknown | `Anime Weebs #1 - @AniXWeebs` |

Real output (Demon Slayer test): audio `Japanese - @AniXWeebs` / `English -
@AniXWeebs`; 9 subs relabeled `French / Arabic / English / Spanish / … -
@AniXWeebs` with correct ISO language codes. `normalize_release()` is
source-agnostic — wired into TelegramSource and available to apply to any
source's output for fleet-wide consistency.

---

## 6. Edge cases, limitations & next steps

- **Live session required** for the Telegram-dependent paths (login, index query,
  channel join, media download). Create a `session_string` once interactively,
  set `TELEGRAM_USERBOT_SESSION`, then those paths run unmodified.
- **Private channels with approval** surface as `pending`; a scheduler should
  re-check `is_member()` and resume once approved.
- **Unknown index reply format**: parsing covers buttons + text/links; if a future
  format differs, `lookup` degrades to "no entries" (safe fallback) and should be
  extended after observing a real reply.
- **Pack archives (.zip season packs)**: detected and catalogued, but extracting
  individual episodes from an archive is a follow-up (download + unpack).
- **Escalation hook**: `Catalog.unresolved` is the designated place to ask channel
  admins/maintainers for clarification on un-parseable items.
- The discovery heuristics are **general/pattern-based**; broadening them is best
  done by observing many real channels with a live session.

---

## 7. Bottom line

Userbot pool (multi-account, fallback) + Anilist-enriched separator-proof matching
+ AnimeFair index parsing + automatic channel entry (with private-channel request
handling) + generalized pack discovery (seasons/resolutions/movies/specials,
multi-season) + a registered `TelegramSource` preferred over other sources. The
metadata, matching, parsing, and discovery layers are tested now; the
session-bound Telegram I/O is coded to the verified pyrofork API and ready to run
once a user session is provisioned.
