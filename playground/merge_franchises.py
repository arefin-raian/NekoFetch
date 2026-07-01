"""Merge standalone movies/OVAs/specials into their parent franchise entries.

Reads the existing PACK_TREE.json, applies a comprehensive FRANCHISE_MAP to group
related content under canonical franchise names, then regenerates all output files.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OUT_DIR = Path("index_data")
CHANNEL = "Ani_Weebs_Index"
CHANNEL_URL = f"https://t.me/{CHANNEL}"

# ══════════════════════════════════════════════════════════════════════
# COMPREHENSIVE FRANCHISE MAPPING
# Maps any standalone entry title → canonical franchise name
# Case-insensitive matching via .lower()
# ══════════════════════════════════════════════════════════════════════
FRANCHISE_MAP: dict[str, str] = {
    # ── Neon Genesis Evangelion ──
    "1.0 you are (not) alone": "Neon Genesis Evangelion",
    "1.11 you are not alone": "Neon Genesis Evangelion",
    "2.0 you can (not) advance": "Neon Genesis Evangelion",
    "2.22 you can not advance": "Neon Genesis Evangelion",
    "3.0 you can (not) redo": "Neon Genesis Evangelion",
    "3.33 you can not redo": "Neon Genesis Evangelion",
    "3.0+1.0 thrice upon a time": "Neon Genesis Evangelion",
    "end of evangelion": "Neon Genesis Evangelion",

    # ── Naruto ──
    "naruto shippuden": "Naruto",
    "the last": "Naruto",
    "road to ninja": "Naruto",
    "the lost tower": "Naruto",
    "the will of fire": "Naruto",
    "blood prison": "Naruto",
    "ninja clash in land": "Naruto",
    "legend of the stone": "Naruto",
    "guardians of crescent": "Naruto",
    "bonds": "Naruto",

    # ── Bleach ──
    "bleach tybw": "Bleach",
    "fade to black": "Bleach",
    "memories of nobody": "Bleach",
    "the diamond dust rebellion": "Bleach",
    "hell verse": "Bleach",

    # ── My Hero Academia ──
    "two heroes": "My Hero Academia",
    "heroes rising": "My Hero Academia",
    "world heroes mission": "My Hero Academia",

    # ── That Time I Got Reincarnated as a Slime (Tensura) ──
    "reincarnated as a slime": "That Time I Got Reincarnated as a Slime",
    "scarlet bond": "That Time I Got Reincarnated as a Slime",
    "visions of coleus": "That Time I Got Reincarnated as a Slime",

    # ── Sword Art Online ──
    "ordinal scale": "Sword Art Online",
    "aria of the startless night": "Sword Art Online",
    "scherzo of deep night": "Sword Art Online",

    # ── Haikyu!! ──
    "the dumpster battle": "Haikyu!!",
    "dumpster battle": "Haikyu!!",
    "talent and sense": "Haikyu!!",
    "battle of concepts": "Haikyu!!",
    "the end & the beginning": "Haikyu!!",
    "the end and the beginning": "Haikyu!!",
    "the winner & the loser": "Haikyu!!",
    "the winner and the loser": "Haikyu!!",
    "haikyu!!": "Haikyu!!",

    # ── Rascal Does Not Dream of Bunny Girl Senpai ──
    "dream of a dreaming girl": "Rascal Does Not Dream of Bunny Girl Senpai",
    "dream of a sister": "Rascal Does Not Dream of Bunny Girl Senpai",
    "dream of a knapsack kid": "Rascal Does Not Dream of Bunny Girl Senpai",

    # ── Alya/Roshidere ──
    "alya sometimes hides": "Alya Sometimes Hides Her Feelings in Russian",
    "alya sometimes hides...": "Alya Sometimes Hides Her Feelings in Russian",

    # ── Overlord ──
    "the dark hero": "Overlord",
    "the undead king": "Overlord",
    "the sacred kingdom": "Overlord",

    # ── Psycho-Pass ──
    "initiation": "Psycho-Pass",
    "initiation -": "Psycho-Pass",
    "transgression": "Psycho-Pass",
    "transgression -": "Psycho-Pass",
    "glorification": "Psycho-Pass",
    "glorification -": "Psycho-Pass",

    # ── Fate ──
    "unlimited blade works": "Fate Series",
    "heaven's feel": "Fate Series",

    # ── Re:Zero ──
    "frozen bonds": "Re:Zero - Starting Life in Another World",
    "memory snow": "Re:Zero - Starting Life in Another World",
    "re zero - frozen bonds": "Re:Zero - Starting Life in Another World",
    "re zero - memory snow": "Re:Zero - Starting Life in Another World",

    # ── Beyond the Boundary ──
    "i'll be here future": "Beyond the Boundary",
    "i'll be here past": "Beyond the Boundary",

    # ── Steins;Gate ──
    "steins gate": "Steins;Gate",
    "steins;gate": "Steins;Gate",
    "load region of déjà vu": "Steins;Gate",

    # ── Haikyu!! (handle one-u vs two-u variants) ──
    "haikyuu!!": "Haikyu!!",

    # ── Jujutsu Kaisen ──
    "jujutsu kaisen 0": "Jujutsu Kaisen",

    # ── Bungo Stray Dogs ──
    "dead apple": "Bungo Stray Dogs",

    # ── No Game No Life ──
    "no game no life zero": "No Game No Life",

    # ── Kuroko's Basketball ──
    "the last game": "Kuroko's Basketball",
    "the last game -": "Kuroko's Basketball",
    "winter cup": "Kuroko's Basketball",
    "winter cup -": "Kuroko's Basketball",

    # ── KonoSuba ──
    "legend of crimson": "KonoSuba: God's Blessing on This Wonderful World!",

    # ── Blue Lock ──
    "episode nagi": "Blue Lock",

    # ── Blue Exorcist ──
    "blue exorcist: the movie": "Blue Exorcist",

    # ── Fruits Basket ──
    "fruits basket prelude": "Fruits Basket",

    # ── Solo Leveling ──
    "re-awakening": "Solo Leveling",
    "re-awakening {cam-rip}": "Solo Leveling",
    "re": "Solo Leveling",

    # ── Black Clover ──
    "wizard king's sword": "Black Clover",
    "wizard king's sword -": "Black Clover",

    # ── Demon Slayer ──
    "to the swordsmith village": "Demon Slayer: Kimetsu no Yaiba",
    "to the hashira training": "Demon Slayer: Kimetsu no Yaiba",

    # ── Berserk ──
    "golden age": "Berserk",
    "golden age - 01": "Berserk",
    "golden age - 02": "Berserk",
    "golden age - 03": "Berserk",

    # ── Code Geass ──
    "re;surrection": "Code Geass",
    "re;surrection -": "Code Geass",

    # ── Violet Evergarden ──
    "auto memory doll": "Violet Evergarden",
    "auto memory doll -": "Violet Evergarden",
    "violet evergarden -": "Violet Evergarden",

    # ── Fullmetal Alchemist: Brotherhood ──
    "sacred star of milos": "Fullmetal Alchemist: Brotherhood",

    # ── Case/naming duplicates ──
    "another": "Another",
    "erased": "Erased",
    "ninja batman": "Batman Ninja",
    "batman ninja": "Batman Ninja",
    "batman ninja -": "Batman Ninja",
    "shangri-la frontier": "Shangri-La Frontier",

    # ── Dr. Stone ──
    "dr. stone ryusui": "Dr. Stone",

    # ── Clannad ──
    "clannad movie": "Clannad",

    # ── Hellsing ──
    "hellsing ultimate": "Hellsing",

    # ── Angel Beats! ──
    "angel beats! ova": "Angel Beats!",

    # ── Nisekoi ──
    "nisekoi ova": "Nisekoi",

    # ── Baccano! ──
    "baccano! - special": "Baccano!",

    # ── Dorohedoro ──
    "dorohedoro - ova": "Dorohedoro",

    # ── Tomozaki ──
    "tomozaki ova": "Bottom-Tier Character Tomozaki",

    # ── Kabaneri ──
    "kababeri of the iron fortress": "Kabaneri of the Iron Fortress",

    # ── Additional aliases from data ──
    "kimi ni todoke": "Kimi ni Todoke",
    "id  invaded": "ID: Invaded",
    "i want to eat your pancreas": "I Want to Eat Your Pancreas",
    "apothecary diaries": "The Apothecary Diaries",
    "classroom of the elite": "Classroom of the Elite",
    "cyberpunk edgerunners": "Cyberpunk: Edgerunners",
    "darling in the franxx": "Darling in the Franxx",
    "dr. stone": "Dr. Stone",
    "eighty six- 86": "86: Eighty Six",
    "god of highschool": "The God of High School",
    "hell's paradise": "Hell's Paradise: Jigokuraku",
    "horimiya": "Horimiya",
    "kingdom of ruins": "Kingdom Of Ruins",
    "komi can't communicate": "Komi Can't Communicate",
    "mushoku tensei": "Mushoku Tensei: Jobless Reincarnation",
    "oshi no ko": "Oshi no Ko",
    "platinum end": "Platinum End",
    "promised neverland": "The Promised Neverland",
    "rent a girlfriend": "Rent-A-Girlfriend",
    "samurai champloo": "Samurai Champloo",
    "spy x family": "SPY X FAMILY",
    "tokyo revengers": "Tokyo Revengers",
    "tower of god": "Tower of God",
    "your lie in april": "Your Lie in April",
    "zom 100": "Zom 100: Bucket List of the Dead",

    # ── Overlord movies (filename-based titles) ──
    "overlord movie01": "Overlord",
    "overlord movie02": "Overlord",
    "overlord movie03": "Overlord",
    "overlord movie03 the sacred kingdom dual": "Overlord",
    "overlord movie03 the sacred kingdom": "Overlord",

    # ── Assassination Classroom movie ──
    "assassination classroom - the movie 1080p": "Assassination Classroom",

    # ── Clannad movie ──
    "clannad movie 1080p": "Clannad",

    # ── Fruits Basket Prelude ──
    "fruits basket prelude 1080p": "Fruits Basket",

    # ── SPY X FAMILY Code: White ──
    "spy x family- code white 1080p": "SPY X FAMILY",

    # ── Violet Evergarden variants ──
    "violet evergarden: the movie": "Violet Evergarden",

    # ── Black Clover movie ──
    "black clover movie": "Black Clover",

    # ── MHA movie variants ──
    "my hero academia: two heroes": "My Hero Academia",
    "my hero academia: heroes rising": "My Hero Academia",
    "my hero academia: world heroes mission": "My Hero Academia",

    # ── Sword Art Online Progressive ──
    "sword art online progressive": "Sword Art Online",

    # ── Case/format aliases — ensure ALL-CAPS variants map to canonical ──
    "black clover": "Black Clover",
    "bleach": "Bleach",
    "blue exorcist": "Blue Exorcist",
    "blue lock": "Blue Lock",
    "bungo stray dogs": "Bungo Stray Dogs",
    "dorohedoro": "Dorohedoro",
    "hellsing": "Hellsing",
    "jujutsu kaisen": "Jujutsu Kaisen",
    "kuroko's basketball": "Kuroko's Basketball",
    "my hero academia": "My Hero Academia",
    "naruto": "Naruto",
    "no game no life": "No Game No Life",
    "violet evergarden": "Violet Evergarden",

    # ── Fix capwords-damaged names from previous merge runs ──
    "jojo's bizarre adventure": "JoJo's Bizarre Adventure",

    # ── Miscellaneous corrections ──
    "demon slayer": "Demon Slayer: Kimetsu no Yaiba",
    "mha": "My Hero Academia",
    "jojo": "JoJo's Bizarre Adventure",
    "re zero": "Re:Zero - Starting Life in Another World",
    "re:zero": "Re:Zero - Starting Life in Another World",
}


def resolve_franchise(title: str) -> str:
    """Map a title to its canonical franchise name.

    Case-insensitive. First checks the explicit FRANCHISE_MAP, then returns
    the title as-is. ALL case-variant merging is handled separately by
    normalizing keys in the main loop."""
    key = title.lower().strip()
    for candidate in (key, key.rstrip("….- ").strip()):
        if candidate in FRANCHISE_MAP:
            return FRANCHISE_MAP[candidate]
    return title


def merge_entries(target: dict, source: dict) -> None:
    """Merge source entry into target. Source's movies/ovas/specials are appended.
    Source's seasons are merged by key. Caps are combined and deduplicated."""
    # Merge seasons
    for skey, sdata in source.get("seasons", {}).items():
        if skey in target.setdefault("seasons", {}):
            t = target["seasons"][skey]
            t["file_count"] += sdata["file_count"]
            t["start_id"] = min(t["start_id"], sdata["start_id"])
            t["end_id"] = max(t["end_id"], sdata["end_id"])
            t.setdefault("caps", []).extend(sdata.get("caps", []))
            for q, rdata in sdata.get("resolutions", {}).items():
                if q in t.setdefault("resolutions", {}):
                    tre = t["resolutions"][q]
                    tre["file_count"] += rdata["file_count"]
                    tre["start_id"] = min(tre["start_id"], rdata["start_id"])
                    tre["end_id"] = max(tre["end_id"], rdata["end_id"])
                    tre.setdefault("files", []).extend(rdata.get("files", []))
                else:
                    t["resolutions"][q] = rdata
        else:
            target["seasons"][skey] = sdata

    # Append movies
    target.setdefault("movies", []).extend(source.get("movies", []))

    # Append OVAs
    target.setdefault("ovas", []).extend(source.get("ovas", []))

    # Append specials
    target.setdefault("specials", []).extend(source.get("specials", []))

    # Merge caps
    all_caps = target.setdefault("caps", []) + source.get("caps", [])
    seen = set()
    target["caps"] = []
    for c in all_caps:
        if c["id"] not in seen:
            seen.add(c["id"])
            target["caps"].append(c)


# ══════════════════════════════════════════════════════════════════════
# DEDUPLICATE MOVIES by caption or filename — same movie at different
# resolutions ends up as separate entries. We merge resolution variants
# while keeping distinct movies separate.
# ══════════════════════════════════════════════════════════════════════
def dedup_movies_by_proximity(merged: dict) -> dict:
    """Merge movie/OVA/special entries that are the same content at
    different resolutions.

    Strategy:
    - If entries share a caption: merge by exact normalized caption.
    - If entries have NO captions: extract a filename-based key from
      the resolution entries' files. Different movies will have different
      words in their filenames; same movie at different resolutions will
      share the same stem. This is used as the primary grouping key.
    - As a fallback for truly indistinguishable entries: merge by ID
      proximity (window=25).
    - Renumber sequentially so merged franchises don't have gaps."""
    def _caption_key(entry: dict) -> str:
        caps = entry.get("caps", [])
        if not caps:
            return ""
        text = caps[0].get("text", "").strip()
        return " ".join(text.lower().split())

    def _filename_key(entry: dict) -> str:
        """Extract a normalized key using the movie/OVA/special number prefix.

        Both "Overlord Movie03 [The Sacred Kingdom] 480p" and
        "Overlord_Movie03_The_Sacred_Kingdom_1080p_Dual_" reduce to
        "overlord movie03" — the number suffix is the content identifier."""
        for rdata in entry.get("resolutions", {}).values():
            files = rdata.get("files", [])
            if files:
                fn = files[0].get("filename", "")
                if fn:
                    # Strip extension, @ suffix
                    base = fn.rsplit(".", 1)[0]
                    at_idx = base.find("@")
                    if at_idx != -1:
                        base = base[:at_idx].strip()
                    # Normalize underscores to spaces
                    base = base.replace("_", " ")
                    # Extract title + content-number prefix
                    # "Overlord Movie03 The Sacred Kingdom ..." → "Overlord Movie03"
                    m = re.search(
                        r"^(.+?)\s*(Movie\s*\d+|OVA\s*\d+|Special\s*\d+|OAD\s*\d+)",
                        base, re.IGNORECASE,
                    )
                    if m:
                        prefix = f"{m.group(1)} {m.group(2)}"
                    else:
                        # Fallback: first 3 words for entries without numbers
                        prefix = " ".join(base.split()[:3])
                    key = " ".join(prefix.lower().split())
                    if key:
                        return key
        # Fallback: use start_id to keep entries separate
        return f"__nofiles_{entry.get('start_id', 0)}"

    for franchise, data in merged.items():
        for key in ("movies", "ovas", "specials"):
            entries = data.get(key, [])
            if not entries:
                continue

            # Sort by start_id for stability
            entries.sort(key=lambda x: x["start_id"])
            groups: list[list[dict]] = []

            for e in entries:
                ck = _caption_key(e)
                joined = False
                for g in groups:
                    g_ck = _caption_key(g[0])
                    # Match by exact caption (if both have captions)
                    if ck and g_ck and ck == g_ck:
                        g.append(e)
                        joined = True
                        break
                    # If both have NO captions, use filename key ONLY.
                    # (ID proximity fallback was causing false merges —
                    # distinct movies uploaded close together share
                    # similar IDs but different filenames.)
                    if not ck and not g_ck:
                        e_fk = _filename_key(e)
                        g_fk = _filename_key(g[0])
                        # Same filename stem = same content at different resolutions
                        if e_fk and g_fk and e_fk == g_fk:
                            g.append(e)
                            joined = True
                            break
                        # If filename keys differ, DO NOT merge — they're different content.
                if not joined:
                    groups.append([e])

            merged_entries = []
            for idx, group in enumerate(groups):
                type_label = {"movies": "Movie", "ovas": "OVA", "specials": "Special"}[key]
                base_name = f"{type_label} {idx + 1}"

                if len(group) == 1:
                    group[0]["name"] = base_name
                    merged_entries.append(group[0])
                else:
                    merged_entry = {
                        "name": base_name,
                        "caps": [],
                        "resolutions": {},
                        "start_id": min(e["start_id"] for e in group),
                        "end_id": max(e["end_id"] for e in group),
                        "file_count": sum(e["file_count"] for e in group),
                        "audio": group[0].get("audio", "unknown"),
                    }
                    for e in group:
                        merged_entry["caps"].extend(e.get("caps", []))
                        for q, rdata in e.get("resolutions", {}).items():
                            if q in merged_entry["resolutions"]:
                                mr = merged_entry["resolutions"][q]
                                mr["file_count"] += rdata["file_count"]
                                mr["start_id"] = min(mr["start_id"], rdata["start_id"])
                                mr["end_id"] = max(mr["end_id"], rdata["end_id"])
                            else:
                                merged_entry["resolutions"][q] = dict(rdata)
                    seen = set()
                    deduped_caps = []
                    for c in merged_entry["caps"]:
                        if c["id"] not in seen:
                            seen.add(c["id"])
                            deduped_caps.append(c)
                    merged_entry["caps"] = deduped_caps
                    merged_entries.append(merged_entry)
            data[key] = merged_entries

    return merged


def main():
    # ── Load current tree ──
    tree_path = OUT_DIR / "PACK_TREE.json"
    print(f"Loading {tree_path}...")
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    total_entries_before = len(tree)
    print(f"  {total_entries_before} entries before merge")

    # ── Map each entry to its franchise ──
    # Phase 1: normalize keys (lowercase) for grouping
    # Phase 2: for each group, pick the best display title (prefer title-cased)
    # Phase 3: apply FRANCHISE_MAP to get canonical franchise name

    # Group entries by normalized key
    groups: dict[str, list[tuple[str, dict]]] = {}
    for title, data in tree.items():
        norm = title.lower().strip()
        groups.setdefault(norm, []).append((title, data))

    # Merge within each group, choosing the best display name
    merged: dict[str, dict] = {}
    franchise_map: dict[str, str] = {}
    merged_count = 0

    for norm_key, entries in groups.items():
        # Pick best display name: prefer title-cased, then shortest non-ALL-CAPS
        titles = [t for t, _ in entries]
        best_title = titles[0]
        for t in titles:
            if t == t.title() or not t.isupper():
                best_title = t
                break
        # If all are ALL-CAPS, pick the one that looks most natural
        if best_title.isupper() and any(not t.isupper() for t in titles):
            best_title = next(t for t in titles if not t.isupper())

        # Apply FRANCHISE_MAP
        canonical = resolve_franchise(best_title)

        for orig_title, data in entries:
            franchise_map[orig_title] = canonical

        if canonical not in merged:
            merged[canonical] = {
                "caps": [],
                "seasons": {},
                "movies": [],
                "ovas": [],
                "specials": [],
            }
        for _, data in entries:
            merge_entries(merged[canonical], data)

        if len(entries) > 1 or best_title != canonical:
            for orig_title, _ in entries:
                if orig_title != canonical:
                    pass  # Will be counted and printed below

    # ── Print what got merged ──
    for title, canonical in sorted(franchise_map.items()):
        if title != canonical:
            merged_count += 1
            print(f"  🔄 '{title}' → '{canonical}'")

    print(f"\n  {merged_count} entries merged into franchises")
    print(f"  {total_entries_before} → {len(merged)} series after merge")

    # ── Deduplicate movies by proximity (same movie at different resolutions) ──
    print("\nDeduplicating movies by proximity...")
    merged = dedup_movies_by_proximity(merged)

    # ── Validate file count ──
    total_files = sum(
        sum(s.get("file_count", 0) for s in d.get("seasons", {}).values())
        + sum(m.get("file_count", 0) for m in d.get("movies", []))
        + sum(o.get("file_count", 0) for o in d.get("ovas", []))
        + sum(s.get("file_count", 0) for s in d.get("specials", []))
        for d in merged.values()
    )
    print(f"  Total files: {total_files}")

    if total_files != 17596:
        print(f"  ⚠️  WARNING: file count changed! Expected 17596, got {total_files}")

    # ── Write outputs ──
    # Sort merged by key
    sorted_merged = dict(sorted(merged.items()))

    # PACK_TREE.json
    json_path = OUT_DIR / "PACK_TREE.json"
    json_path.write_text(json.dumps(sorted_merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  ✅ {json_path}")

    # PACK_TREE.md — inline the generator to avoid import issues
    md_content = generate_md(sorted_merged)
    md_path = OUT_DIR / "PACK_TREE.md"
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  ✅ {md_path}")

    # PACK_TREE.html
    html_content = generate_html(sorted_merged)
    html_path = OUT_DIR / "PACK_TREE.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  ✅ {html_path}")

    # ── Summary ──
    total_seasons = sum(len(d.get("seasons", {})) for d in merged.values())
    total_movies = sum(len(d.get("movies", [])) for d in merged.values())
    total_ovas = sum(len(d.get("ovas", [])) for d in merged.values())
    total_specials = sum(len(d.get("specials", [])) for d in merged.values())

    print(f"\n{'=' * 60}")
    print(f"Franchise Merge Complete!")
    print(f"  Series:    {len(merged)}")
    print(f"  Seasons:   {total_seasons}")
    print(f"  Movies:    {total_movies}")
    print(f"  OVAs:      {total_ovas}")
    print(f"  Specials:  {total_specials}")
    print(f"  Total files: {total_files}")
    print(f"{'=' * 60}")


# ══════════════════════════════════════════════════════════════════════
# OUTPUT GENERATORS (inlined from build_pack_tree.py)
# ══════════════════════════════════════════════════════════════════════
def generate_md(tree_json: dict) -> str:
    """Generate PACK_TREE.md from JSON tree."""
    lines = [
        f"# Anime Weebs | Database - Pack Tree",
        f"",
        f"- **Anime entries:** {len(tree_json)}",
        f"- **Channel:** [{CHANNEL}]({CHANNEL_URL})",
        f"",
    ]

    total_files = 0
    total_seasons = 0
    total_movies = 0
    total_ovas = 0
    total_specials = 0

    lines.append("---")
    lines.append("")

    for idx, (series, data) in enumerate(tree_json.items(), 1):
        lines.append(f"## {idx}. {series}")
        lines.append("")

        if data["seasons"]:
            lines.append("### Seasons")
            for skey, sdata in data["seasons"].items():
                fc = sdata["file_count"]
                sid = sdata["start_id"]
                eid = sdata["end_id"]
                audio = sdata.get("audio", "unknown")
                total_files += fc
                total_seasons += 1
                lines.append(
                    f"- **{skey}**: {fc} files | "
                    f"**START:** [{sid}]({CHANNEL_URL}/{sid}) | "
                    f"**END:** [{eid}]({CHANNEL_URL}/{eid})"
                    + (f" | Audio: {audio}" if audio and audio != "unknown" else "")
                )
            lines.append("")

        if data["movies"]:
            lines.append("### Movies")
            for m in data["movies"]:
                fc = m["file_count"]
                sid = m["start_id"]
                eid = m["end_id"]
                total_files += fc
                total_movies += 1
                lines.append(
                    f"- **{m['name']}**: {fc} files | "
                    f"**START:** [{sid}]({CHANNEL_URL}/{sid}) | "
                    f"**END:** [{eid}]({CHANNEL_URL}/{eid})"
                )
            lines.append("")

        if data["ovas"]:
            lines.append("### OVAs")
            for o in data["ovas"]:
                fc = o["file_count"]
                sid = o["start_id"]
                eid = o["end_id"]
                total_files += fc
                total_ovas += 1
                lines.append(
                    f"- **{o['name']}**: {fc} files | "
                    f"**START:** [{sid}]({CHANNEL_URL}/{sid}) | "
                    f"**END:** [{eid}]({CHANNEL_URL}/{eid})"
                )
            lines.append("")

        if data["specials"]:
            lines.append("### Specials")
            for s in data["specials"]:
                fc = s["file_count"]
                sid = s["start_id"]
                eid = s["end_id"]
                total_files += fc
                total_specials += 1
                lines.append(
                    f"- **{s['name']}**: {fc} files | "
                    f"**START:** [{sid}]({CHANNEL_URL}/{sid}) | "
                    f"**END:** [{eid}]({CHANNEL_URL}/{eid})"
                )
            lines.append("")

        lines.append("---")

    lines.insert(4, f"**Content:** {total_files} files, {total_seasons} seasons, "
                     f"{total_movies} movies, {total_ovas} OVAs, {total_specials} specials")
    lines.insert(5, "")

    return "\n".join(lines)


def generate_html(tree_json: dict) -> str:
    """Generate a navigational HTML file with hyperlinks."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anime Weebs - Pack Tree</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0f0f1a; color: #e0e0e0; padding: 20px; }
  h1 { color: #7c3aed; margin-bottom: 10px; }
  .summary { color: #888; margin-bottom: 20px; }
  .series { margin-bottom: 30px; border: 1px solid #2a2a3a; border-radius: 8px;
            overflow: hidden; }
  .series-header { background: #1a1a2e; padding: 12px 16px; cursor: pointer;
                   display: flex; justify-content: space-between; align-items: center; }
  .series-header:hover { background: #25254a; }
  .series-title { font-size: 1.1em; font-weight: bold; color: #a78bfa; }
  .series-meta { font-size: 0.85em; color: #666; }
  .series-body { padding: 16px; display: none; }
  .series-body.open { display: block; }
  .section { margin-bottom: 12px; }
  .section-label { font-weight: bold; color: #6d28d9; margin-bottom: 4px; }
  .entry { display: flex; justify-content: space-between; align-items: center;
           padding: 6px 12px; background: #1a1a2e; border-radius: 4px;
           margin-bottom: 4px; }
  .entry:hover { background: #25254a; }
  .entry a { color: #60a5fa; text-decoration: none; }
  .entry a:hover { text-decoration: underline; }
  .audio-tag { background: #374151; color: #9ca3af; padding: 1px 6px;
               border-radius: 3px; font-size: 0.8em; }
  .toggle-all { margin-bottom: 16px; }
  .toggle-all button { background: #7c3aed; color: white; border: none;
                       padding: 8px 16px; border-radius: 6px; cursor: pointer;
                       margin-right: 8px; }
  .toggle-all button:hover { background: #6d28d9; }
  .search-box { margin-bottom: 16px; }
  .search-box input { width: 100%; padding: 10px 16px; background: #1a1a2e;
                      border: 1px solid #2a2a3a; border-radius: 8px;
                      color: #e0e0e0; font-size: 1em; }
  .search-box input:focus { outline: none; border-color: #7c3aed; }
</style>
</head>
<body>
<h1>Anime Weebs · Pack Tree</h1>
<div class="summary" id="summary"></div>
<div class="toggle-all">
  <button onclick="toggleAll(true)">Expand All</button>
  <button onclick="toggleAll(false)">Collapse All</button>
</div>
<div class="search-box">
  <input type="text" id="search" placeholder="Search series..." oninput="filterSeries()">
</div>
<div id="tree"></div>
<script>
const treeData = __TREE_DATA__;
const CHANNEL = "__CHANNEL__";
const CHANNEL_URL = "__CHANNEL_URL__";

function buildTree() {
  const container = document.getElementById('tree');
  let idx = 0;
  let totalFiles = 0, totalSeasons = 0, totalMovies = 0, totalOVAs = 0, totalSpecials = 0;

  for (const [series, data] of Object.entries(treeData)) {
    idx++;
    const div = document.createElement('div');
    div.className = 'series';
    div.setAttribute('data-name', series.toLowerCase());

    let meta = [];
    const seasonCount = Object.keys(data.seasons || {}).length;
    const movieCount = (data.movies || []).length;
    const ovaCount = (data.ovas || []).length;
    const specialCount = (data.specials || []).length;

    if (seasonCount) meta.push(`${seasonCount} season${seasonCount>1?'s':''}`);
    if (movieCount) meta.push(`${movieCount} movie${movieCount>1?'s':''}`);
    if (ovaCount) meta.push(`${ovaCount} OVA${ovaCount>1?'s':''}`);
    if (specialCount) meta.push(`${specialCount} special${specialCount>1?'s':''}`);

    totalSeasons += seasonCount;
    totalMovies += movieCount;
    totalOVAs += ovaCount;
    totalSpecials += specialCount;

    div.innerHTML = `
      <div class="series-header" onclick="this.parentElement.querySelector('.series-body').classList.toggle('open')">
        <span class="series-title">${idx}. ${escapeHtml(series)}</span>
        <span class="series-meta">${meta.join(' \u00b7 ')}</span>
      </div>
      <div class="series-body">
        ${buildSeasons(data.seasons)}
        ${buildMovies(data.movies)}
        ${buildOVAs(data.ovas)}
        ${buildSpecials(data.specials)}
      </div>`;

    container.appendChild(div);
  }

  document.getElementById('summary').textContent =
    `${Object.keys(treeData).length} series \u00b7 ${totalSeasons} seasons \u00b7 ${totalMovies} movies \u00b7 ${totalOVAs} OVAs \u00b7 ${totalSpecials} specials`;
}

function buildSeasons(seasons) {
  if (!seasons || !Object.keys(seasons).length) return '';
  let html = '<div class="section"><div class="section-label">📺 Seasons</div>';
  for (const [key, s] of Object.entries(seasons)) {
    const fc = s.file_count || 0;
    const sid = s.start_id;
    const eid = s.end_id;
    const audio = s.audio && s.audio !== 'unknown' ? s.audio : '';
    html += `<div class="entry">
      <span>${escapeHtml(key)} \u2014 ${fc} files</span>
      <span>
        ${audio ? `<span class="audio-tag">${escapeHtml(audio)}</span> ` : ''}
        <a href="${CHANNEL_URL}/${sid}" target="_blank">Start \u2192</a>
        &nbsp;\u00b7&nbsp;
        <a href="${CHANNEL_URL}/${eid}" target="_blank">End \u2192</a>
      </span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function buildMovies(movies) {
  if (!movies || !movies.length) return '';
  let html = '<div class="section"><div class="section-label">🎬 Movies</div>';
  for (const m of movies) {
    html += `<div class="entry">
      <span>${escapeHtml(m.name)} \u2014 ${m.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${m.start_id}" target="_blank">Start \u2192</a>
        &nbsp;\u00b7&nbsp;
        <a href="${CHANNEL_URL}/${m.end_id}" target="_blank">End \u2192</a>
      </span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function buildOVAs(ovas) {
  if (!ovas || !ovas.length) return '';
  let html = '<div class="section"><div class="section-label">💀 OVAs</div>';
  for (const o of ovas) {
    html += `<div class="entry">
      <span>${escapeHtml(o.name)} \u2014 ${o.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${o.start_id}" target="_blank">Start \u2192</a>
        &nbsp;\u00b7&nbsp;
        <a href="${CHANNEL_URL}/${o.end_id}" target="_blank">End \u2192</a>
      </span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function buildSpecials(specials) {
  if (!specials || !specials.length) return '';
  let html = '<div class="section"><div class="section-label">⭐ Specials</div>';
  for (const s of specials) {
    html += `<div class="entry">
      <span>${escapeHtml(s.name)} \u2014 ${s.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${s.start_id}" target="_blank">Start \u2192</a>
        &nbsp;\u00b7&nbsp;
        <a href="${CHANNEL_URL}/${s.end_id}" target="_blank">End \u2192</a>
      </span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function toggleAll(open) {
  document.querySelectorAll('.series-body').forEach(b => {
    if (open) b.classList.add('open'); else b.classList.remove('open');
  });
}

function filterSeries() {
  const q = document.getElementById('search').value.toLowerCase();
  document.querySelectorAll('.series').forEach(s => {
    s.style.display = s.getAttribute('data-name').includes(q) ? '' : 'none';
  });
}

function escapeHtml(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

buildTree();
</script>
</body>
</html>"""

    html = html.replace("__TREE_DATA__", json.dumps(tree_json, ensure_ascii=False))
    html = html.replace("__CHANNEL__", CHANNEL)
    html = html.replace("__CHANNEL_URL__", CHANNEL_URL)
    return html


if __name__ == "__main__":
    main()
