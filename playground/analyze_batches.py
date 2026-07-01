"""Analyze all 49 batch dump files to understand pack structure."""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Fix Windows Unicode output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DUMP_DIR = Path("index_data/dumps")
OUT_DIR = Path("playground/_analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Load all messages ──────────────────────────────────────────────
all_msgs: list[dict] = []
batch_counts: dict[str, int] = {}

for i in range(1, 50):
    fname = f"batch_{i:03d}.json"
    fpath = DUMP_DIR / fname
    if not fpath.exists():
        print(f"⚠ Missing: {fname}")
        continue
    data = json.loads(fpath.read_text(encoding="utf-8"))
    batch_counts[fname] = len(data)
    all_msgs.extend(data)

# Sort by ID descending (channel order)
all_msgs.sort(key=lambda m: m["id"], reverse=True)
print(f"Total messages: {len(all_msgs)} across {len(batch_counts)} batches")

# ── Type breakdown ──────────────────────────────────────────────────
type_counts = Counter(m["type"] for m in all_msgs)
print(f"\nType counts: {dict(type_counts)}")

# Count documents by mime_type
mime_counts = Counter(m.get("mime_type", "?") for m in all_msgs if m["type"] == "document")
print(f"MIME types: {dict(mime_counts.most_common(10))}")

# Check media groups
media_group_msgs = [m for m in all_msgs if "media_group_id" in m]
print(f"\nMessages with media_group_id: {len(media_group_msgs)}")
media_groups = defaultdict(list)
for m in media_group_msgs:
    media_groups[m["media_group_id"]].append(m)
print(f"Unique media groups: {len(media_groups)}")

# ── Sticker analysis ────────────────────────────────────────────────
stickers = [m for m in all_msgs if m["type"] == "sticker"]
sticker_emojis = Counter(
    m.get("sticker", {}).get("emoji", "?") for m in stickers
)
print(f"\nStickers: {len(stickers)}")
print(f"Sticker emojis: {dict(sticker_emojis)}")
print(f"Unique sticker file_ids: {len(set(m['sticker']['file_id'] for m in stickers))}")

# ── Text message analysis ──────────────────────────────────────────
texts = [m for m in all_msgs if m["type"] == "text"]
print(f"\nText messages: {len(texts)}")

# Parse captions
caption_pattern = re.compile(r"➠\s*(.+?)\s*:\s*(.+?)\n➠\s*(.+)")
parsed_captions = []
for t in texts:
    m = caption_pattern.match(t["text"])
    if m:
        parsed_captions.append({
            "id": t["id"],
            "series": m.group(1).strip(),
            "season_info": m.group(2).strip(),
            "quality_audio": m.group(3).strip(),
        })

print(f"Parseable captions: {len(parsed_captions)}")

# Extract unique series names from captions
series_from_captions = set(c["series"] for c in parsed_captions)
print(f"\nUnique series in captions: {len(series_from_captions)}")
for s in sorted(series_from_captions):
    print(f"  {s}")

# Extract season info patterns
season_infos = Counter(c["season_info"] for c in parsed_captions)
print(f"\nSeason info patterns: {dict(season_infos)}")

# ── File naming pattern analysis ────────────────────────────────────
docs = [m for m in all_msgs if m["type"] == "document"]
file_pattern = re.compile(
    r"^(.+?)\s*\[(.+?)\]\s*(\d+p|Multi\s+Quality)\s*\[(.+?)\]\s*@Ani[_ ]?[Ww]eebs"
)
parsed_files = []
unparseable_files = []
for d in docs:
    fn = d.get("file_name", "")
    m = file_pattern.match(fn)
    if m:
        parsed_files.append({
            "id": d["id"],
            "title": m.group(1).strip(),
            "season_tag": m.group(2).strip(),
            "quality": m.group(3).strip(),
            "audio": m.group(4).strip(),
            "filename": fn,
        })
    else:
        unparseable_files.append(fn)

print(f"\nParseable filenames: {len(parsed_files)}")
print(f"Unparseable filenames: {len(unparseable_files)}")

# Show some unparseable filenames
if unparseable_files:
    print("\nSample unparseable filenames:")
    for fn in unparseable_files[:20]:
        print(f"  {fn}")

# ── Pack reconstruction ─────────────────────────────────────────────
# A "pack" = messages between two stickers (or start/end)
packs: list[list[dict]] = []
current_pack: list[dict] = []
first = True

for msg in all_msgs:
    if msg["type"] == "sticker":
        if current_pack or not first:
            packs.append(current_pack)
            current_pack = []
    else:
        current_pack.append(msg)
    first = False

if current_pack:
    packs.append(current_pack)

print(f"\nTotal packs (sticker-delimited groups): {len(packs)}")

# Analyze pack structure
pack_types = Counter()
empty_packs = 0
no_caption_packs = 0
no_files_packs = 0
for pack in packs:
    has_caption = any(m["type"] == "text" for m in pack)
    has_files = any(m["type"] == "document" for m in pack)
    if not has_caption and not has_files:
        empty_packs += 1
        continue
    if not has_caption:
        no_caption_packs += 1
    if not has_files:
        no_files_packs += 1
    pack_types[f"caption={has_caption}, files={has_files}"] += 1

print(f"Empty packs: {empty_packs}")
print(f"Packs without caption: {no_caption_packs}")
print(f"Packs without files: {no_files_packs}")
print(f"Pack types: {dict(pack_types)}")

# ── Series grouping from filenames ───────────────────────────────────
series_files = defaultdict(list)
for pf in parsed_files:
    # Normalize title
    title = pf["title"].strip()
    series_files[title].append(pf)

print(f"\nUnique series from filenames: {len(series_files)}")
for s in sorted(series_files.keys()):
    count = len(series_files[s])
    print(f"  {s}: {count} files")

# ── Identify season tags ────────────────────────────────────────────
season_tags = Counter(pf["season_tag"] for pf in parsed_files)
print(f"\nSeason tag patterns: {dict(season_tags.most_common(30))}")

# ── Identify movie entries ──────────────────────────────────────────
movies_from_files = [pf for pf in parsed_files if "Movie" in pf["season_tag"] or "movie" in pf["season_tag"].lower()]
print(f"\nMovie entries from filenames: {len(movies_from_files)}")
movie_groups = defaultdict(list)
for mf in movies_from_files:
    key = f"{mf['title']} [{mf['season_tag']}]"
    movie_groups[key].append(mf)
for key, items in sorted(movie_groups.items()):
    print(f"  {key}: {len(items)} files, qualities: {[i['quality'] for i in items]}")

# ── Identify specials/OVAs/ONAs ─────────────────────────────────────
specials = [pf for pf in parsed_files if re.search(r"\[(Special|OVA|ONA)\]", pf["season_tag"], re.IGNORECASE)]
print(f"\nSpecial/OVA/ONA entries: {len(specials)}")
for sp in specials:
    print(f"  {sp['title']} [{sp['season_tag']}] {sp['quality']}")

# ── Audio types ─────────────────────────────────────────────────────
audio_types = Counter(pf["audio"] for pf in parsed_files)
print(f"\nAudio types: {dict(audio_types)}")

# ── Quality distribution ────────────────────────────────────────────
qualities = Counter(pf["quality"] for pf in parsed_files)
print(f"\nQuality distribution: {dict(qualities)}")

# ── Check for duplicate file entries ─────────────────────────────────
file_ids = [m["id"] for m in all_msgs if m["type"] == "document"]
unique_ids = set(file_ids)
if len(file_ids) != len(unique_ids):
    dupes = [fid for fid, cnt in Counter(file_ids).items() if cnt > 1]
    print(f"\n⚠ DUPLICATE file IDs: {len(dupes)} duplicates found!")
    for d in dupes[:10]:
        print(f"  ID {d} appears {Counter(file_ids)[d]} times")
else:
    print(f"\n✅ No duplicate file IDs — all {len(file_ids)} unique")

# ── Check file naming inconsistencies ───────────────────────────────
# Case variations
title_variants = defaultdict(set)
for pf in parsed_files:
    title_variants[pf["title"].lower()].add(pf["title"])

inconsistencies = {k: v for k, v in title_variants.items() if len(v) > 1}
if inconsistencies:
    print(f"\n⚠ Title case inconsistencies: {len(inconsistencies)}")
    for k, v in list(inconsistencies.items())[:10]:
        print(f"  {k}: {v}")

# ── Detect corrupted/suspicious entries ──────────────────────────────
suspicious = []
for d in docs:
    if d.get("file_size", 0) < 10000:  # Suspiciously small
        suspicious.append(("Small file", d))
    if d.get("file_size", 0) > 3_000_000_000:  # > 3GB
        suspicious.append(("Very large file", d))
    if ".mp4" in d.get("file_name", "") and d.get("mime_type", "") == "video/x-matroska":
        suspicious.append(("Mime mismatch (.mp4 but video/x-matroska)", d))
    if ".Mkv" in d.get("file_name", ""):
        suspicious.append(("UpperCase extension", d))

if suspicious:
    print(f"\n⚠ Suspicious entries: {len(suspicious)}")
    for reason, item in suspicious[:20]:
        print(f"  [{reason}] ID {item['id']}: {item.get('file_name','')} ({item.get('file_size',0)} bytes)")

# ── Save parsed data for tree building ──────────────────────────────
output = {
    "total_messages": len(all_msgs),
    "total_documents": type_counts.get("document", 0),
    "total_text": type_counts.get("text", 0),
    "total_stickers": type_counts.get("sticker", 0),
    "total_packs": len(packs),
    "series_from_captions": sorted(series_from_captions),
    "series_from_filenames": {k: len(v) for k, v in sorted(series_files.items())},
    "audio_types": dict(audio_types),
    "qualities": dict(qualities),
    "season_tags": dict(season_tags.most_common()),
    "movies": {k: [{"quality": i["quality"], "filename": i["filename"]} for i in v]
               for k, v in sorted(movie_groups.items())},
    "specials": [{"title": sp["title"], "tag": sp["season_tag"], "quality": sp["quality"]}
                 for sp in specials],
    "media_groups": {k: [{"id": m["id"], "filename": m.get("file_name")} for m in v]
                     for k, v in media_groups.items()},
}

with open(OUT_DIR / "batch_analysis.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

# ── Save pack boundaries for tree building ──────────────────────────
pack_summary = []
for i, pack in enumerate(packs):
    if not pack:
        continue
    captions = [m for m in pack if m["type"] == "text"]
    docs_in_pack = [m for m in pack if m["type"] == "document"]
    pack_summary.append({
        "pack_index": i,
        "first_id": pack[0]["id"],
        "last_id": pack[-1]["id"],
        "message_count": len(pack),
        "captions": [t["text"] for t in captions],
        "file_count": len(docs_in_pack),
        "filenames": [d.get("file_name", "")[:80] for d in docs_in_pack[:5]],
        "has_media_group": any("media_group_id" in d for d in docs_in_pack),
    })

with open(OUT_DIR / "pack_summary.json", "w", encoding="utf-8") as f:
    json.dump(pack_summary, f, indent=2, ensure_ascii=False)

print(f"\n✅ Analysis saved to {OUT_DIR}")
print(f"   - batch_analysis.json")
print(f"   - pack_summary.json")
print("\nReady for tree building!")
