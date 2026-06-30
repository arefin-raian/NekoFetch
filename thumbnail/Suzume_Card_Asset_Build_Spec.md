# Suzume Hero Card — Build Spec (asset-based)

**Canvas: 1440×810 (16:9)**

## ⚠️ Image assets — use these files as-is

**Do not regenerate, redraw, repaint, or AI-generate any artwork.** Every visual element below is a file that already exists. Just place it.

| File | Role | Placement |
|---|---|---|
| `background.webp` | Full-bleed background art | Fills the entire 1440×810 canvas, behind everything (z-index 0) |
| `poster.jpg` | Small poster thumbnail | Inside the rounded card at **x:104, y:447, 190×290px** |
| `logo.png` | "Suzume" title wordmark | Top-left hero logo at **x:105, y:362**, rendered ≈313×54px |

Everything else (badge, Japanese title, metadata, synopsis, genre pills, ratings, like/save, director credit) is **live text/CSS**, not images.

---

## Global
- Font for all live text: a clean geometric/humanist sans — Poppins, Inter, or Plus Jakarta Sans.
- Text shadow on white text over the art: `text-shadow: 0 3px 14px rgba(0,0,0,0.55)`

## 1. Background — `background.webp`
- Fill the full canvas: `object-fit: cover` (or `background-size: cover; background-position: center;`)
- z-index 0, behind every other element
- If the file doesn't already have a darkening gradient baked in and text contrast looks weak, layer this on top: `linear-gradient(to top, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0) 55%)`

## 2. Badge ("🇯🇵 AniMovie Weebs")
- Flag chip: 48×33px, ~3px corner radius, at (121, 325). Emoji or simple icon — no asset file needed.
- "AniMovie Weebs": white, bold, ~20–22px, ~10px gap right of the flag.

## 3. Hero Logo — `logo.png`
- `<img src="logo.png">`, anchored top-left at **x:105, y:362**
- Target rendered footprint ≈ **313×54px** — resize via CSS to fit that, preserving the file's own aspect ratio (don't assume those are the file's native pixel dimensions)
- No font/color/letter-spacing styling needed — it's a flattened image, not live text

## 4. Poster Card — `poster.jpg`
- Container: x:104, y:447, **190×290px**, `border-radius: 16px`, `overflow: hidden`
- `box-shadow: 0 18px 36px rgba(0,0,0,0.45)`
- `<img src="poster.jpg">` fills it, `object-fit: cover`
- The "Suzume" wordmark at the bottom of the poster is already part of poster.jpg — nothing to add on top.

## 5. Japanese Title Block
- "すずめの戸締まり": x:337, y:451 → ~24–26px bold white
- "(Suzume no Tojimari)": x:334, y:485 → ~22–24px bold white
- ~14px gap between the two lines

## 6. Metadata Row
`2022 | G | 2h 1m | Language: Japanese & English`
- x:336, y:518 → ~16–18px regular, ~70–80% white opacity
- Pipe separators with extra side padding (not tight-kerned)

## 7. Synopsis
- Column max-width ~536px, starts x:333, y:566
- ~16–17px regular, ~85% white, line-height ~1.3–1.4 (wraps to 4 lines naturally)

## 8. Genre Pills
Row at y:696, height 44px. True stadium shape — `border-radius: 9999px` (= height/2, ≈22px). Border ~1.5–2px white @ ~50–55% opacity. Fill `rgba(0,0,0,0.40–0.45)`. Text white bold ~16–18px. ~14px gaps between pills.

| Pill | x-range | width |
|---|---|---|
| Adventure | 336→482 | 146px |
| Fantasy | 496→628 | 132px |
| Mystery | 642→778 | 136px |
| Supernatural | 792→950 | 158px |

## 9. Rating Cluster (centered sub-column, ~x=1325)
- "7.6": x:1272, y:124 → ~40–42px bold
- "IMDB": centered below → ~14–16px bold caps
- Ring: x:1263, y:203, **~130–136px diameter**, stroke ~16–18px, `stroke-linecap: round`, white arc clockwise from 12 o'clock to 82%, dim ~35–40%-white track for the remaining 18% (sits top-left of the circle)
- "82%": centered inside ring → ~36–40px bold
- "Anilist Rating": centered below ring → ~16–18px medium/bold

## 10. Action Row
- Heart icon (outline, ~24×20px) at x:1125, y:629, then "Like" ~16–17px, ~10px gap
- Bookmark icon (outline, ~24×20px) at x:1208, then "Save to watch later" ~16–17px, ~10px gap
- Inline SVG or icon-font glyphs — no asset files needed for these

## 11. Director Credit (right-aligned, right edge ≈x:1397)
- "Director:": x:1262→1397, y:693 → ~26–28px bold
- "Makoto Shinkai": x:1233→1397, y:722 → ~24–26px regular/medium
- ~4–6px gap between the two lines

---

### Confidence note
`logo.png`/`poster.jpg` placement, the flag chip, and the director-block right-alignment were verified two ways (visual + pixel scan) — solid to build from. The four genre-pill widths are the least certain numbers here (their dark fill sits over genuinely dark parts of the original art) — fine to build from, just not pixel-gospel.
