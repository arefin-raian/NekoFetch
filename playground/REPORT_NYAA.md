# NekoFetch — Nyaa.si Source Report

**Date:** 2026-06-25
**Source:** `src/nekofetch/sources/nyaa.py` (+ `_torrent.py`, `_torrentdl.py`, `_transcode.py`)
**Tooling:** bundled `aria2c` (torrents) + `ffmpeg`/`ffprobe` (transcode), in `tools/`

A torrent-based source. We scrape **nyaa.si RSS directly** (Anime category,
seeder-sorted) rather than depend on a third-party hosted API — the RSS exposes
seeders/size/infohash cleanly and never sleeps.

---

## 1. Pipeline

| Stage | How |
|---|---|
| **Search** | nyaa RSS `c=1_2` (Anime – English-translated), `s=seeders&o=desc` |
| **Audio detect** | fuzzy "Dual Audio" + language inference from title **and** description |
| **Ranking** | Dual/Multi first, then seeders desc, trusted-uploader tiebreak |
| **Episodes** | download the `.torrent`, decode bencode, order EP1..EPN from the release's stable naming pattern |
| **Download** | `aria2c` multi-connection BitTorrent + DHT + extra trackers, selective single-file (`--select-file`), original filename preserved |
| **Transcode** | ffmpeg → 720p + 480p, recompress oversized 1080p (duration-aware), keeping all audio + subs |

---

## 2. Validation results (6 titles, 1998 → 2025)

| Title | Top release | Dual | Seeders | Episodes parsed | Kinds detected | Ordering |
|---|---|---|---|---|---|---|
| Attack on Titan | [Anime Time] Complete Collection | ✅ | 773 | 131 | 101 ep / 4 movie / 8 special / 18 extra | ✅ monotonic |
| Frieren | [Judas] S2 batch | ✅ | 443 | 10 | 10 ep (S02E01–10) | ✅ |
| Bocchi the Rock | [Judas] Season 1 BD | ❌ (subbed) | 162 | 12 | 12 ep | ✅ |
| A Silent Voice | [Judas] Koe no Katachi BD | ✅ | 182 | 1 | 1 **movie** | ✅ |
| Cowboy Bebop | [YakuboEncodes] 01~26 + Movie | ✅ | 260 | 27 | 26 ep + 1 movie | ✅ |
| Spy x Family | [Trix] S03 batch | ✅ | 228 | 13 | 13 ep (S03) | ✅ |

**Search accuracy:** every query returned the expected series as the top result.
**Seeder prioritization:** the highest-seeder dual-audio release leads in all cases.
**Episode ordering:** stable per-release pattern detection works across SubsPlease
(`- 01`), Judas (`S02E01`), and batch collections; **seasons, movies, specials,
OVAs, and extras are classified and ordered** (AOT's 131-file collection split
cleanly into 101 episodes + 4 movies + 8 specials + 18 extras).

### Dual-audio detection (fuzzy) — unit-verified

`Dual Audio`, `Dual-Audio`, `Dual_Audio`, `[DualAudio]`, `DUAL.AUDIO` → **True**;
`Multi Audio` / `dual subtitle` → **False** (not dual-audio). `[Multi-Audio]` and
`[JPN+ENG+HIN]` → **Multi**.

### Fallback hierarchy (subbed when no dual exists)

1. Title advertises **Dual/Multi Audio** → use it (highest seeders).
2. No title-dual → **inspect each top candidate's view-page description** for
   language indicators (English/ENG/Japanese/JPN/Hindi/…). `ja + en` present ⇒
   treated as dual; `ja+en+hi` ⇒ multi.
3. Still none → **gracefully fall back to the highest-seeder subbed release**
   (never fails the task).

Verified: a SubsPlease-style title `[SubsPlease] Show - 01` with description
"English subbed" classifies as **single/subbed**; releases tagged `[Dual-Audio]`
or `[JPN+ENG]` classify as dual without relying on one field.

---

## 3. Download (fastest method)

**aria2c** — the fastest practical torrent client without compiling libtorrent:
parallel piece fetching across many peers, DHT, plus extra public trackers for
fast peer discovery. `--select-file` downloads only the wanted episode from a
batch; `--seed-time=0` stops seeding immediately.

- **Bocchi EP1**: 197 MB in **195 s** (~1 MB/s, peer-limited), original filename
  `[Judas] Bocchi the Rock! - 01.mkv` preserved.
- **Attack on Titan EP1**: 545 MB, download confirmed starting (1%+) after the
  MAX_PATH fix below.

---

## 4. Transcoding

From the (usually 1080p) source, generate **720p + 480p**, and **recompress 1080p
only when oversized**. "Oversized" is **duration-aware** — a per-minute budget
(~16 MB/min for 1080p, i.e. the ≈23 min / 370 MB example) so movies and long
episodes get proportionally larger limits. CRF-based (quality-preserving), and
**every transcode keeps all audio tracks (dual audio survives) + all subtitles**.

Oversize heuristic — unit-verified:

| Input | Decision |
|---|---|
| 23 min / 370 MB | recompress ✅ |
| 23 min / 300 MB | keep ❌ |
| 120 min / 1.2 GB | keep ❌ (large budget) |
| 120 min / 3 GB | recompress ✅ |

Bocchi EP1 (1080p HEVC, 7.6 MB/min → not oversized): produced **720p (152 MB) +
480p (91 MB)**, each retaining audio + all 9 subtitle tracks; no 1080p recompress
(correct).

---

## 5. Issues found & resolved

1. **Windows MAX_PATH on batch releases (aria2 exit 16).** AOT's "Complete
   Collection" release folder + filename exceeded 260 chars. **Fixed** with
   `--index-out=<idx>=<name>`, flattening the selected file to `<dir>/<name>` —
   preserves the original filename while dropping the long folder. Verified.
2. **`episode` number missing from episode metadata.** Ordering was correct
   (natural-sort fallback) but the numeric field wasn't propagated. **Fixed** —
   `episode` is now stored in the episode ref.
3. **Single-file movies not flagged.** A lone video with no episode number (e.g.
   *A Silent Voice*) was labelled `episode`. **Fixed** — single-file releases with
   no episode index are classified as **movie**.
4. **Dual-only matching too strict.** Added the description/metadata language
   inference + subbed fallback (§2) so series without a "Dual Audio" title string
   still resolve correctly.

---

## 6. Edge cases & notes

- **HEVC/x265 sources transcode slowly** (10-bit decode + 8-bit x264 encode):
  Bocchi's full episode took ~17 min at `veryfast`. Production should use a fixed
  fast preset or hardware encoding; the preset is a parameter.
- **x264 output vs x265 source size**: downscaled x264 isn't dramatically smaller
  than an efficient x265 1080p source (x264 < x265 efficiency). Expected; switch
  the encoder to x265 if smaller derived files matter.
- **Title encoding**: some group names contain symbols (e.g. Spy×Family's "×")
  that arrive as a replacement char — cosmetic only, doesn't affect matching.
- **Peer-bound speed**: torrent throughput depends on swarm health; well-seeded
  dual-audio releases (our priority) download fastest, by design.
- **Selective download**: tests grab only EP1; full-series downloads simply omit
  `--select-file`.

---

## 6b. Multi-source fallback (general downloader rule)

`orchestrator.download_with_fallback(sources, query, dest)` makes reliability a
whole-downloader property, not per-source:

1. Try the **preferred source** first.
2. Within it, try the **top N candidate releases** (Nyaa) / search results, and
   for each episode try **every variant/server** before giving up.
3. On no-result, **timeout** (per-source budget), or download failure, move to
   the **next source** entirely.
4. Fail only when **every** source is exhausted — returning the full `attempts`
   trail for diagnostics.

This means a title like *Attack on Titan* that stalls or has a bad top release on
one source automatically continues through other releases and then other sources
(KickAssAnime, AniKoto, Nyaa) until a valid release downloads. Verified with mock
sources: search-failure fallthrough, all-candidates-fail → next source, and
full-exhaustion error all behave correctly.

---

## 7. Bottom line

A complete torrent-based source: nyaa RSS search with **Dual Audio priority +
graceful subbed fallback** (title *and* description inference), **seeder-first
ranking**, robust **episode ordering** across seasons/movies/specials/OVAs with
preserved filenames, **fast aria2c selective downloads**, and **duration-aware
ffmpeg transcoding** to 720p/480p (+ oversized-1080p recompress) that keeps dual
audio and subtitles. All four issues found during validation were fixed and
re-verified.
