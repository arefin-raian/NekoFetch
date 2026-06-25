# NekoFetch — UI / Flow Redesign v2 (DESIGN ONLY — not for production)

> **Status: PROPOSAL FOR REVIEW.** Nothing here is wired into the bots. Single
> source of truth for the message standard and every layout. Build only after sign-off.

**Revised per feedback. Decisions in force:**
- Parse mode = **HTML**. **No code/quote styling for ordinary text** — important
  text is **bold**, supporting text *italic*, long details in
  `<blockquote expandable>`. `<code>`/`<pre>` only for real IDs/logs.
- **Every major window/section carries its own artwork**, all at a fixed **16:9**
  aspect ratio so the layout never jumps when a message is edited.
- **Anything that takes time shows a live animation** (edit-cycle), same spirit
  as the connecting animation.
- **No heavy borders / boxes.** Separate fields with **colons, spacing, and light
  symbols** — clean, not boxy.
- Matching targets **complete series** (seasons collapsed), with **distinct
  versions** shown as separate options (logic in §6, grounded in real AniList data).
- Search confirmation uses a **TMDB 16:9 backdrop + TMDB info + Yes/No**, not a list.
- **Preserved exactly:** startup cat sticker, connecting animation, animated
  `Connecting!!!!!!` text.
- Exists-message and ready-message wording = **placeholders** for now.

---

## 1. Formatting standard

Switch every bot to `parse_mode=HTML`. Emphasis comes from weight/hierarchy/
spacing, not monospace.

### Telegram-supported HTML tags (the whole set we use)
| Tag | Use for |
|---|---|
| `<b>`/`<strong>` | primary emphasis — names, labels, the important word |
| `<i>`/`<em>` | secondary notes, alt titles, hints, transient status |
| `<u>`/`<ins>` | rare, single-word emphasis |
| `<s>`/`<del>` | a superseded value |
| `<tg-spoiler>` / `<span class="tg-spoiler">` | spoilers (optional) |
| `<a href="…">` | links / deep-links |
| `<a href="tg://user?id=…">` | mention a user/admin |
| `<blockquote>` | one short callout, used sparingly |
| `<blockquote expandable>` | long details collapsed by default |
| `<code>` | **only** IDs / hashes / filenames |
| `<pre><code class="language-…">` | **only** real logs / JSON |
| `<tg-emoji emoji-id="…">⭐</tg-emoji>` | optional custom-emoji layer (Premium, later) |

Unsupported (never use): `<br>`, `<hr>`, headings, `<ul>`, `<table>`, CSS. Breaks
are real `\n`. Photo messages: text lives in the **caption** (≤1024 chars) — keep
layouts within that.

---

## 2. Visual system

### 2.1 Imagery
- Every major surface (welcome, my-requests, search-confirm, request-received,
  ready, each admin step) has a **dedicated 16:9 image**.
- Fixed aspect ratio across all of them → editing a message (swap photo+caption
  via `editMessageMedia`) never shifts the layout.
- Search/confirm backdrop comes from **TMDB** (English promotional backdrop),
  cropped to 16:9 if needed.

### 2.2 Loading animations (everywhere time passes)
Edit the message text/caption on a short cycle to signal life. Patterns:
- **Spinner:** cycle a frame char — `⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏`.
- **Dots:** `Searching.` → `Searching..` → `Searching...` → repeat.
- **Pulse word:** the connecting-style animated keyword.
Applied to: DB lookups, search, fetching TMDB, and each pipeline step.

### 2.3 Separators (clean, no boxes)
- Field rows: `<b>Label</b> : value` (colon-aligned).
- Light divider line: `─────` or `· · · · ·` (plain text), used at most once per card.
- Lifecycle/status uses light glyphs `●` (done) · `◌` (pending) · `➤` (current),
  laid out as a clean vertical list — never inside an ASCII box.

### 2.4 Emoji legend (standard set)
🐾 brand · 🔎 search · 📥 request/queued · ⏳ pending · ⚙️ processing · 🎬 video ·
💬 subtitles · 🏷️ metadata · 🖋️ watermark · ⬆️ uploading · ✅ done · ⚠️ attention ·
❌ failed.

---

## 3. User flow

### 3.1 Startup — PRESERVED
Cat sticker → connecting animation → animated `Connecting!!!!!!`. Unchanged. First
text surface after connect = the welcome (3.2).

### 3.2 Welcome  *(image: brand artwork)*
Personalized, explains what the bot is, two user buttons.

Caption (rendered):
```
🐾  Hi Raiyan — welcome to NekoFetch.

I fetch anime for you. Ask for any title and I'll source it,
clean it up, brand it, and deliver it — subs, dual audio,
the works.

Already in our library? You get it instantly.
Not yet? I'll go get it.

What would you like to do?
```
Caption (HTML):
```html
🐾  <b>Hi Raiyan — welcome to NekoFetch.</b>

I fetch anime for you. Ask for any title and I'll source it, clean
it up, brand it, and deliver it — <b>subs, dual audio, the works</b>.

<i>Already in our library?</i> You get it instantly.
<i>Not yet?</i> I'll go get it.

What would you like to do?
```
Buttons (regular users):
```
[ 🔎 Request Anime ]   [ 📥 My Requests ]
```

### 3.3 My Requests  *(image: "my requests" artwork — same message, edited)*
Tapping **My Requests** edits the welcome into this (photo + caption swap).

Caption (rendered):
```
📥  Raiyan — your requests

Attack on Titan        :  ✅ Ready
Frieren                :  ⚙️ Processing · subtitles
Jujutsu Kaisen         :  ⏳ Queued · #3
Bleach                 :  ⚠️ Needs info (admin asked)

4 total  ·  1 ready  ·  2 in progress  ·  1 waiting on you

[ 🔎 Request Anime ]   [ ⬅ Back ]
```
- Colon-separated rows, status with one emoji. No boxes.
- If a request needs the user (e.g. confirm a title), it’s called out.

### 3.4 Request input
After **Request Anime**, prompt (image: search artwork):
```
🔎  Which anime?

Send me a name — English, Japanese, or a short form.
Examples : Attack on Titan · Shingeki no Kyojin · AoT
```

### 3.5 Searching — animated
On submit, the same message animates (edit-cycle) while we resolve:
```
🔎  Looking up Attack on Titan ⠹      (frame cycles)
```
then transitions to the confirm card (3.6) or the versions list (3.7).

### 3.6 Single series → confirm  *(image: TMDB 16:9 backdrop)*
The default path. We fetch the TMDB backdrop + info and ask one question.

Caption (rendered):
```
🎬  Attack on Titan   (2013)

Type     :  TV Series
Seasons  :  4  ·  Episodes : 89
Genres   :  Action · Drama · Fantasy
Rating   :  9.0

[TMDB synopsis — 1–2 clean lines.]

Is this the one?
[ ✅ Yes, that's it ]   [ ❌ Not this ]
```
- Seasons are **collapsed into the one series** — we do not list them.
- **Not this** → 3.8.

### 3.7 Distinct versions → choose  *(image: brand artwork)*
Only when the title genuinely has separate versions (e.g. Hellsing vs Hellsing
Ultimate, Fullmetal Alchemist vs Brotherhood, Naruto vs Naruto Shippuden — see §6).
Presented directly, no single-confirm:
```
🔎  “Hellsing” comes in two versions. Which one?

Hellsing            :  TV · 2001 · 13 eps
Hellsing Ultimate   :  OVA · 2006 · 10 eps

[ Hellsing ]   [ Hellsing Ultimate ]
[ ❌ Neither ]
```
- Each version is its own DB entry (own aliases, own lifecycle).

### 3.8 Not this / no match → ask again
```
🔎  My bad — let's try again.

Give me the title a bit more precisely (add the year or the
Japanese name if you can).
```

### 3.9 Request received (queued)  *(image: queued artwork)*
Clean style — colons, spacing, symbols; **no box**.
```
📥  Got it, Raiyan.

Anime    :  Attack on Titan
Status   :  ⏳ Queued for sourcing
Queue    :  #3

I'll fetch → process → brand → publish it, and ping you here
the moment it's ready.
```

### 3.10 Ready & 3.11 Exists — PLACEHOLDERS
Wording/buttons deferred (delivery layer TBD). Ready = a notification with an
Open/Browse action; Exists = instant access into the delivery bot.

---

## 4. Matching & aliases (data/logic)

On **new entry creation**, store + index: admin-confirmed primary title, AniList
romaji/english/native, synonyms, alternative/regional names. Any future request
matching **any** alias resolves to the same entry. Matching is separator/format-
agnostic (existing flexible matcher).

---

## 5. Log channel — one live card per request (redesigned)

A single message per request, **edited in place** as it advances. Clean rows,
colons, light status glyphs — no boxes.

### 5.1 In-progress  *(image: optional small state art, fixed 16:9)*
```
🐾  Attack on Titan

Request   :  #1042
By        :  @user
Source    :  🧲 Torrent
Now       :  ⚙️ Extracting subtitles  ·  ep 3 / 25

●  Requested
●  Source assigned
●  Downloaded
➤  Extracting subtitles
◌  Watermark
◌  Uploading
◌  Published
```
- Current step = `➤`, done = `●`, pending = `◌`.

### 5.2 Completed — no "Status" field (it's obviously done)
Show what actually matters instead:
```
✅  Attack on Titan

Seasons   :  1–4
Qualities :  480p · 720p · 1080p
Episodes  :  89  ·  Dual Audio
Source    :  🧲 Torrent
Took      :  14m 22s
```

### 5.3 Blocked / failed — show the blocking point
```
⚠️  Attack on Titan

Stuck at  :  Extracting subtitles
Reason    :  No text subtitle tracks in 3 files
Source    :  🧲 Torrent

Details (tap to expand)        ← <blockquote expandable>
[ 🔁 Retry ]  [ 🔀 Reassign source ]  [ ✖ Dismiss ]
```

---

## 6. Series vs. distinct versions — the auto-distinction logic

Grounded in live AniList relation data:

| Case | AniList signal | Decision |
|---|---|---|
| AoT "Season 2/3/Final Season" | **SEQUEL**, title = base + *season marker* | **collapse** into one series |
| Naruto → "Naruto: Shippuuden" | **SEQUEL**, title = base + *named subtitle* | **separate** entries |
| Hellsing → Hellsing Ultimate | **ALTERNATIVE** | **separate** (show both) |
| FMA → Brotherhood | **ALTERNATIVE** | **separate** (show both) |
| OVAs / specials / spin-offs | SIDE_STORY / SPIN_OFF / SUMMARY | treated as extras, not user-facing "versions" |

**Proposed rule:**
1. Pull the searched title's AniList relations.
2. **ALTERNATIVE** (TV/OVA) → distinct version → list both (3.7).
3. **SEQUEL/PREQUEL** (TV): strip the base title from the relation's title.
   - remainder matches a *season marker* (`Season N`, `N(st|nd|rd|th) Season`,
     `Part N`, `Cour N`, `Final Season`, a bare number) → **same series, collapse**.
   - remainder is a *named* continuation (e.g. "Shippuuden", "Brotherhood") →
     **separate entry** → list both.
4. Otherwise → single series → confirm flow (3.6).

> **Open:** this rule is derived from 4 real cases and must be validated against a
> wider set; the admin can always override a collapse/split. Edge cases (split
> cours that share a title, reboots) need confirming — flagged in §9.

---

## 7. Admin side

### 7.1 New request notification  *(image: admin artwork)*
```
📥  New request

Anime     :  Attack on Titan
Aliases   :  Shingeki no Kyojin · AoT · 進撃の巨人
Requester :  @user
AniList   :  TV · 2013 · 89 eps · seasons collapsed

Assign a source:
[ 📨 Telegram ]  [ 🌐 Website ]  [ 🧲 Torrent ]
[ ❌ Reject ]
```
- Row 1 : Telegram · Website · Torrent. Row 2 : Reject. (No "check channels".)

### 7.2 Telegram selected → Automatic or Manual
```
📨  Telegram source

[ 🤖 Automatic ]   [ ✋ Manual ]
```
- **Automatic** → existing AnimeFair automation flow.
- **Manual** → prompt for the files/info we need (ordered pack per quality), with
  the order-validation result surfaced; ambiguous patterns ask for confirmation.

### 7.3 Website / Torrent
- **Website** → existing worker flow; admin confirms source/quality.
- **Torrent** → final fallback; filename-pattern analysis + order validation run;
  low-confidence ordering escalates to a confirm (5.3 style).

### 7.4 Admin actions
Attach to the same live log card (Retry / Reassign / Pause) — no separate noisy
stream.

---

## 8. Publishing

DB hierarchy is correct: Season → 480p → Episode Pack → Sticker → 720p → … → 1080p
→ …, repeated per season. **The published message format/wording is NOT finalized**
— to be defined later.

---

## 9. Dependencies & open questions

**Dependencies**
- **TMDB API key** for backdrops + info (English backdrop, 16:9 crop). Needed
  before the search-confirm card can be built.
- A set of **section artworks** (welcome, my-requests, search, queued, admin),
  all 16:9.

**Open questions**
1. Series-distinction rule (§6) — validate against more titles; confirm handling
   of split cours that share a title, and reboots/remakes.
2. Custom emoji — when a Premium sender + pack exist, which moments use them?
3. My-Requests / version lists — pagination cap before we page?
4. Log-card edit cadence — throttle per-episode ticks to dodge edit-rate limits?
5. Publishing target — one channel per anime, or one channel with per-anime topics?
6. Section stickers — reuse the cat sticker as the terminator, or a distinct one?
7. Image hosting — store artworks as file_ids (upload once) vs re-upload per send?

---

## 10. Build gate
On approval: (1) HTML render helpers + tokens/emoji + image/animation utilities →
(2) log live-card engine → (3) user messages (welcome, my-requests, search-confirm,
versions, queued) → (4) admin messages (request, source select, Telegram auto/manual,
actions) → (5) publishing. Each step ships behind review against this file.
