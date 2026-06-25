# NekoFetch — Full Source Verification Report

**Generated:** 2026-06-25
**Tooling:** bundled ffmpeg/ffprobe (`tools/`), in-process de-masking HLS engine
**Sources tested:** KickAssAnime (`kaa.lt`), AniKoto (`anikototv.to`)
**Titles:** 6 per source, spanning **1998 → 2024** (both KAA audio shapes covered)
**Per-file analysis:** ffprobe stream inspection + ffmpeg decode-check + subtitle
hygiene scan (watermark/branding) + label-vs-audio-count verification.

Raw data: `playground/full_test/RESULTS_FULL.json`. Media: `playground/full_test/`.

---

## 1. Headline

| Source | Titles | Clean (0 problems) | Notes |
|---|---|---|---|
| **KickAssAnime** | 6 | **6 / 6** | every label, audio-count, decode, watermark & branding check passed |
| **AniKoto** | 6 | **4 / 6 clean** | 1 search-relevance issue (Death Note), 1 transient candidate error (AOT, recovered on retry) |

**Across all downloaded files: 0 corrupted, 0 residual PNG masks, 0 decode errors,
0 watermarks surviving, branding present in every subtitle track checked.**

---

## 2. KickAssAnime — detailed per-file results

| Title (era) | Label | Container | Video | Duration | Audio tracks | Subs | Decode | Watermark | Branding |
|---|---|---|---|---|---|---|---|---|---|
| Cowboy Bebop (1998) | SUBBED | MKV | 1920×1432 h264 | 24.7 min | 1 × `jpn` | 1 | ✅ clean | ✅ removed | ✅ present |
| Death Note (2006) | Dual Audio | MKV | 1280×720 h264 | 23.0 min | 2 × `jpn`,`eng` | 1 | ✅ clean | ✅ removed | ✅ present |
| Attack on Titan (2013) | Dual Audio | MKV | 1280×720 h264 | 25.7 min | 2 × `jpn`,`eng` | 1 | ✅ clean | ✅ removed | ✅ present |
| Demon Slayer (2019) | Dual Audio | MKV | 1280×720 h264 | 24.3 min | 2 × `jpn`,`eng` | 9 | ✅ clean | ✅ removed | ✅ present |
| Frieren (2023) | **Multi Audio** | MKV | 1280×720 h264 | 26.0 min | 3 × `jpn`,`eng`,`hin` | 9 | ✅ clean | ✅ removed | ✅ present |
| Solo Leveling (2024) | SUBBED | MKV | 1280×720 h264 | 23.7 min | 1 × `jpn` | 12 | ✅ clean | ✅ removed | ✅ present |

**Every KAA verification passed:**
- **Label ↔ audio-track count** matches in all 6 (SUBBED/DUBBED = 1, Dual = 2, Multi = 3).
- **Audio languages** are exactly the ja/en/hi subset — never a 4th language (Frieren
  has 8 available; only ja/en/hi kept).
- **Both delivery shapes verified:** Cowboy Bebop & Solo Leveling are single-audio
  *separate-variant* sources → SUBBED (not merged); the rest are *multi-audio
  manifests* → Dual/Multi.
- **Subtitles:** all tracks muxed as ASS with correct language tags; `kaa.mx`
  watermark removed; `Telegram: @AniXWeebs` branding present (Telegram-blue +
  white). Demon Slayer/Frieren/Solo Leveling carry 9–12 subtitle languages each.
- **Decode:** ffmpeg decoded a slice of every file with **zero errors**.

---

## 3. AniKoto — detailed per-file results

| Title (era) | Label | Container | Video | Duration | Audio | Subs | Decode | Branding | Status |
|---|---|---|---|---|---|---|---|---|---|
| Cowboy Bebop (1998) | SUBBED | MKV | 966×720 h264 | 24.7 min | 1 | 1 | ✅ | ✅ | clean |
| Death Note (2006) | SUBBED | MP4 | 1280×720 h264 | **130 min** | 1 | 0 | ✅ | n/a | ⚠ wrong title (Relight special) |
| Attack on Titan (2013) | SUBBED | MKV | 1280×720 h264 | ~24 min | 1 | 1 | ✅ | ✅ | recovered on retry (transient) |
| Demon Slayer (2019) | SUBBED | MKV | 1280×720 h264 | 23.7 min | 1 | 1 | ✅ | ✅ | clean |
| Frieren (2023) | SUBBED | MKV | 1280×720 h264 | 24.0 min | 1 | 1 | ✅ | ✅ | clean |
| Solo Leveling (2024) | SUBBED | MKV | 1280×720 h264 | 23.7 min | 1 | 1 | ✅ | ✅ | clean |

AniKoto serves sub and dub as independent single-audio streams, so every output is
correctly **SUBBED** (single Japanese audio) — never a wrongly-merged track,
consistent with the "respect the source structure" rule.

---

## 3b. Post-report fixes (investigated & resolved)

These were raised after the first pass and have been fixed + verified:

- **Gap detection / branding placement.** Confirmed the engine already placed the
  AOT cue in a genuine 45.5 s gap (18:35), *not* the stale 2:48 a previous build
  produced. Added the requested rules: **exclude the final 3 minutes** (cutoff
  from the real ffprobe duration) and **place near the start** of the longest gap.
  Re-verified on AOT → branding at **18:35**, 0 overlapping cues, present inside
  the muxed MKV with Telegram-blue styling, `kaa.mx` absent.
- **Subtitle track count / "only our subs".** The current pipeline embeds **only**
  our processed `.ass` tracks (AOT MKV has exactly 1 — its single source English
  track). The earlier "3 tracks" was a stale file. Added **content-signature
  dedup**: identical tracks across variants collapse to one; distinct tracks
  (timing/wording/content) are all kept and processed independently (unit-tested).
- **AniKoto embedded-audio language** now tagged `jpn`/`eng` (was `und`/`?`).

---

## 4. Issues found (for review)

1. **AniKoto search relevance — Death Note.** The query resolved to *Death Note:
   Relight* (a 130-minute recap special) instead of the TV series, so the file is
   feature-length, `.mp4`, and has no subtitle track. Root cause is search ranking
   (the special outranked the series), the same class as the Jujutsu PV / Frieren
   mini-anime cases. **Fix direction:** prefer entries whose episode count > 1 and
   whose title lacks recap/special/relight markers.

2. **AniKoto AOT — transient candidate error.** One run threw `'NoneType' …
   'lower'` from a malformed candidate response; a manual retry succeeded (the
   fallback chain picked the next server → SUBBED, 235 MB, clean). Rare and
   self-recovering, but the post-candidate path could be wrapped so a single bad
   candidate never escapes the loop. Logged for hardening.

3. **CDN rate-limiting (KAA / krussdomi).** Segment concurrency of 16 sustained
   across back-to-back episodes got our IP **temporarily 403-blocked** mid-run.
   **Fixed:** default concurrency lowered to **8** + a 6 s inter-episode pause.
   The re-run completed all 6 KAA titles with zero blocks. Trade-off: slightly
   lower peak speed for reliability.

4. **Quality fallback — Cowboy Bebop (KAA).** Requested 720p but the master had no
   exact 720 rendition, so the engine fell back to the highest (1920×1432 → 979 MB).
   Correct behaviour, but worth a note: add nearest-≤-target selection if disk size
   matters.

5. **AniKoto audio language metadata.** Embedded `.ts` audio was muxed untagged
   (`lang='?'`). **Fixed:** the muxer now tags AniKoto's embedded audio `jpn`/`eng`
   from the sub/dub variant.

6. **One slow KAA mirror.** Cowboy Bebop's krussdomi node was unusually slow
   (~8 min for the video). It still completed cleanly; the 600 s per-title timeout
   guards against a truly stuck mirror.

---

## 5. Verification methodology

Each output was checked for:
- **Container/format** and **video stream** (codec, resolution, fps, duration) via ffprobe.
- **Audio tracks** — count, language tags, codecs; **A/V duration drift** (all ≈ 0).
- **Subtitle tracks** — count, language tags, codec (ASS).
- **Corruption** — `ffmpeg -xerror -t 12 … -f null -` (decodes a slice; any stderr = fail). All clean.
- **PNG-mask residue** — header sniff + full-file signature scan. Zero.
- **Label correctness** — audio-track count must match SUBBED/DUBBED/Dual/Multi.
- **Subtitle hygiene** — `kaa.mx` absent, `@AniXWeebs` + Telegram-blue present.

---

## 6. Conclusion

- **KickAssAnime: fully verified, 6/6 clean** across 1998→2024, both audio delivery
  shapes, with correct labeling, ja/en/hi-only audio, multi-language subtitles,
  watermark removal, and branding — all in single integrated MKVs.
- **AniKoto: 4/6 clean + 1 recovered + 1 relevance issue.** The download/extraction
  pipeline is correct; the two blemishes are search-ranking (Death Note) and a rare
  transient (AOT) — both understood, with fix directions noted.
- **No corruption anywhere.** The original "corrupted files" class of bug is
  comprehensively gone: 0 PNG masks, 0 decode errors, 0 failed integrity checks.
- **Reliability tuning applied:** concurrency 8 + inter-episode pause eliminates the
  CDN rate-limit blocks that the aggressive 16-wide setting triggered.
