"""Build a flawless pack tree from all 49 batch dump files.

Handles: aliases, missing captions, movies, OVAs, specials, resolution merging,
duplicate dedup, and generates JSON, MD, and navigational HTML."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Fix Windows Unicode output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DUMP_DIR = Path("index_data/dumps")
OUT_DIR = Path("index_data")
CHANNEL = "Ani_Weebs_Index"
CHANNEL_URL = f"https://t.me/{CHANNEL}"

# ══════════════════════════════════════════════════════════════════════
# ALIAS MAP — community/abbreviated names → canonical titles
# ══════════════════════════════════════════════════════════════════════
ALIAS_MAP: dict[str, str] = {
    "tensura": "That Time I Got Reincarnated as a Slime",
    "roshidere": "Alya Sometimes Hides Her Feelings in Russian",
    "fmab": "Fullmetal Alchemist: Brotherhood",
    "fma": "Fullmetal Alchemist",
    "mha": "My Hero Academia",
    "hxh": "Hunter x Hunter",
    "aot": "Attack on Titan",
    "nge": "Neon Genesis Evangelion",
    "sao": "Sword Art Online",
    "bungou stray dogs": "Bungo Stray Dogs",
    "bunny girl": "Rascal Does Not Dream of Bunny Girl Senpai",
    "mightiest disciple": "Kenichi: The Mightiest Disciple",
    "my smartphone": "In Another World with My Smartphone",
    "loner life": "Loner Life in Another World",
    "girl i like": "The Girl I Like Forgot Her Glasses",
    "love for yamada kun": "My Love Story with Yamada-kun at Lv999",
    "tomo-chan": "Tomo-chan Is a Girl!",
    "tomozaki kun": "Bottom-Tier Character Tomozaki",
    "tomozaki ova": "Bottom-Tier Character Tomozaki",
    "shikimori": "Shikimori's Not Just a Cutie",
    "dangers in heart": "The Dangers in My Heart",
    "ao haru ride": "Blue Spring Ride",
    "gun gale online": "Sword Art Online Alternative: Gun Gale Online",
    "slime diaries": "That Time I Got Reincarnated as a Slime",
    "bleach tybw": "Bleach",
    "re zero": "Re:Zero - Starting Life in Another World",
    "re:zero": "Re:Zero - Starting Life in Another World",
    "jojo": "JoJo's Bizarre Adventure",
    "experiments lain": "Serial Experiments Lain",
    "snow white": "Snow White with Red Hair",
    "angel next door": "The Angel Next Door Spoils Me Rotten",
    "nobody remembers me": "Why Does Nobody Remember Me in This World?",
    "the executioner": "The Executioner",
    "our last crusade": "Our Last Crusade",
    "promised neverland": "The Promised Neverland",
    "eminence in shadow": "The Eminence in Shadow",
    "undead unlucky": "Undead Unluck",
    "platinum end": "Platinum End",
    "shangri la frontier": "Shangri-La Frontier",
    "call of the night": "Call of the Night",
    "heavenly delusion": "Heavenly Delusion",
    "hell's paradise": "Hell's Paradise: Jigokuraku",
    "cyberpunk edgerunners": "Cyberpunk: Edgerunners",
    "terror in resonance": "Terror in Resonance",
    "chainsaw man": "Chainsaw Man",
    "bocchi the rock": "Bocchi the Rock!",
    "noragami": "Noragami",
    "link click": "Link Click",
    "berserk 1997": "Berserk",
    "berserk 2016": "Berserk",
    "berserk 2017": "Berserk",
    "berserk memorial edi": "Berserk",
    "berserk of gluttony": "Berserk of Gluttony",
    "naruto shippuden": "Naruto",
    "apothecary diaries": "The Apothecary Diaries",
    "ranma ½ 2024": "Ranma 1/2",
    "kabaneri": "Kabaneri of the Iron Fortress",
    "kababeri of the iron fortress": "Kabaneri of the Iron Fortress",
    "hyouka": "Hyouka",
    "monogatari": "Monogatari Series",
    "pluto": "Pluto",
    "uzumaki": "Uzumaki",
    "makeine": "Makeine: Too Many Losing Heroines!",
    "shoshimin": "Shoshimin: How to Become Ordinary",
    "isekai shikkaku": "No Longer Allowed in Another World",
    "reincarnated aristocrat": "The Reincarnation of the Strongest Exorcist in Another World",
    "tsukimichi": "Tsukimichi: Moonlit Fantasy",
    "newbie adventurer": "Suppose a Kid from the Last Dungeon Boonies Moved to a Starter Town",
    "failure frame": "Failure Frame: I Became the Strongest and Annihilated Everything with Low-Level Spells",
    "spirit chronicles": "Spirit Chronicles",
    "wistoria wand": "Wistoria: Wand and Sword",
    "kaiju no.8": "Kaiju No. 8",
    "black bullet": "Black Bullet",
    "plastic memories": "Plastic Memories",
    "buddy daddies": "Buddy Daddies",
    "domestic girlfriend": "Domestic Girlfriend",
    "god of highschool": "The God of High School",
    "true beauty": "True Beauty",
    "erased": "Erased",
    "my wife has no emotions": "My Wife Has No Emotion",
    "zom 100": "Zom 100: Bucket List of the Dead",
    "beyond the boundary": "Beyond the Boundary",
    "a condition called love": "A Condition Called Love",
    "days with stepsister": "Days with My Stepsister",
    "komi can't communicate": "Komi Can't Communicate",
    "rent a girlfriend": "Rent-A-Girlfriend",
    "parasyte the maxim": "Parasyte: The Maxim",
    "paranoia agent": "Paranoia Agent",
    "the new gate": "The New Gate",
    "why does nobody": "Why Does Nobody Remember Me in This World?",
    "demon slayer": "Demon Slayer: Kimetsu no Yaiba",
    "mob psycho 100": "Mob Psycho 100",
    "one punch man": "One Punch Man",
    "tokyo ghoul": "Tokyo Ghoul",
    "tokyo revengers": "Tokyo Revengers",
    "frieren": "Frieren: Beyond Journey's End",
    "solo leveling": "Solo Leveling",
    "vinland saga": "Vinland Saga",
    "mushoku tensei": "Mushoku Tensei: Jobless Reincarnation",
    "oshi no ko": "Oshi no Ko",
    "konosuba": "KonoSuba: God's Blessing on This Wonderful World!",
}

# ══════════════════════════════════════════════════════════════════════
# SERIES TITLE NORMALIZATION — maps filename/caption titles to canonical
# ══════════════════════════════════════════════════════════════════════
def normalize_title(raw: str) -> str:
    """Normalize a title to its canonical form."""
    t = raw.strip().rstrip(".")
    lower = t.lower()

    # Direct alias lookup
    if lower in ALIAS_MAP:
        return ALIAS_MAP[lower]

    # Substring alias matching
    for alias, canonical in ALIAS_MAP.items():
        if alias in lower:
            return canonical

    # Common case/formatting fixes
    fixes = {
        "chainsow man": "Chainsaw Man",
        "bungou stray dogs": "Bungo Stray Dogs",
        "shangri la frontier": "Shangri-La Frontier",
        "shangri-la frontier": "Shangri-La Frontier",
        "kaiju no 8": "Kaiju No. 8",
        "kaiju no.8": "Kaiju No. 8",
        "bocchi the rock": "Bocchi the Rock!",
    }
    if lower in fixes:
        return fixes[lower]

    # Title-case for proper noun normalization
    return t


# ══════════════════════════════════════════════════════════════════════
# LOAD ALL BATCHES
# ══════════════════════════════════════════════════════════════════════
def load_all_messages() -> list[dict]:
    """Load and sort all messages from all 49 batch files."""
    all_msgs: list[dict] = []
    for i in range(1, 50):
        fpath = DUMP_DIR / f"batch_{i:03d}.json"
        if not fpath.exists():
            continue
        data = json.loads(fpath.read_text(encoding="utf-8"))
        all_msgs.extend(data)
    all_msgs.sort(key=lambda m: m["id"], reverse=True)
    return all_msgs


# ══════════════════════════════════════════════════════════════════════
# PACK RECONSTRUCTION
# ══════════════════════════════════════════════════════════════════════
def reconstruct_packs(messages: list[dict]) -> list[list[dict]]:
    """Reconstruct packs by splitting on stickers."""
    packs: list[list[dict]] = []
    current: list[dict] = []

    for msg in messages:
        if msg["type"] == "sticker":
            if current:
                packs.append(current)
                current = []
        else:
            current.append(msg)

    if current:
        packs.append(current)
    return packs


# ══════════════════════════════════════════════════════════════════════
# FILE NAME PARSING — multi-step extraction for all filename formats
# ══════════════════════════════════════════════════════════════════════

# Audio patterns in brackets: [Dual], [Sub], [Dub], [Multi], [Subbed], [Dual Audio], etc.
_AUDIO_RE = re.compile(
    r"\[(Sub|Dub|Dual|Multi|Subbed|Dual\s*Audio)\]",
    re.IGNORECASE,
)
# Quality pattern (also captures "Multi Quality" which is a quality, not audio)
_QUALITY_RE = re.compile(r"\b(\d{3,4}p|Multi\s*Quality)\b", re.IGNORECASE)
# Season tag in brackets: [S1 EP01], [Movie], [OVA-01], [Special-2], [S4EP08], etc.
_SEASON_RE = re.compile(
    r"\[([^\]]*(?:S\d|EP|Movie|OVA|OAD|Special|Extra|Winter\s*Cup|EPISODE|P\d+\s*EP)[^\]]*)\]",
    re.IGNORECASE,
)


def parse_filename(fn: str) -> dict | None:
    """Parse ANY filename format into {title, season_tag, quality, audio}.

    Uses multi-step extraction instead of rigid full-string regex:
    1. Strip extension and @Ani_Weebs suffix.
    2. Normalise underscores → spaces (handles _format filenames).
    3. Find quality (480p/720p/1080p/360p/Multi Quality).
    4. Find audio tag in brackets ([Dual], [Sub], [Dub], [Multi], [Subbed], etc.).
    5. Find season tag in brackets ([S1 EP01], [Movie], [OVA-01], [Special-2], etc.).
    6. Everything before the first bracket is the title.
    """
    if not fn:
        return None

    # ── 1. Strip extension ──
    base = fn.rsplit(".", 1)[0]

    # ── 2. Strip @ suffix (everything from @ onward) ──
    at_idx = base.find("@")
    if at_idx != -1:
        base = base[:at_idx].strip()

    # ── 3. Normalise underscores (for `Overlord_Movie03_...` format) ──
    # Only normalise if there are NO spaces (pure underscore format)
    if " " not in base and "_" in base:
        base = base.replace("_", " ")

    # ── 4. Find quality ──
    quality = ""
    q_match = _QUALITY_RE.search(base)
    if q_match:
        quality = q_match.group(1)

    # ── 5. Find audio tag in brackets ──
    audio = ""
    a_match = _AUDIO_RE.search(base)
    if a_match:
        audio = a_match.group(1)

    # ── 6. Find season tag in brackets ──
    season_tag = ""
    s_match = _SEASON_RE.search(base)
    if s_match:
        season_tag = s_match.group(1)

    # ── 7. Title = everything before the first bracket ──
    first_bracket = base.find("[")
    if first_bracket != -1:
        title = base[:first_bracket].strip()
    else:
        # No brackets — strip quality and audio from raw text
        title = base.strip()
        if quality:
            title = title.replace(quality, "").strip()
            # Remove leading/trailing dashes
            title = title.strip(" -")
        if audio and title.endswith(audio):
            title = title[: -len(audio)].strip()

    # Clean up title
    title = re.sub(r"\s{2,}", " ", title).strip()  # collapse spaces
    title = title.rstrip(" -")

    if not title:
        return None

    return {
        "title": title,
        "season_tag": season_tag,
        "quality": quality,
        "audio": audio,
    }


# ══════════════════════════════════════════════════════════════════════
# SEASON TAG PARSING
# ══════════════════════════════════════════════════════════════════════
def parse_season_tag(tag: str) -> dict:
    """Parse a season tag like 'S1 EP01' into structured data."""
    result = {"type": "episode", "season": 0, "episode": 0, "raw": tag}

    if not tag:
        result["type"] = "unknown"
        return result

    # Movie detection
    if re.search(r"Movie", tag, re.IGNORECASE):
        result["type"] = "movie"
        m = re.search(r"Movie\s*[-]?\s*(\d+)", tag, re.IGNORECASE)
        if m:
            result["movie_num"] = int(m.group(1))
        return result

    # OVA detection
    if re.search(r"OVA|OAD", tag, re.IGNORECASE):
        result["type"] = "ova"
        m = re.search(r"(?:OVA|OAD)[-]?\s*(\d+)", tag, re.IGNORECASE)
        if m:
            result["ova_num"] = int(m.group(1))
        return result

    # Special detection
    if re.search(r"Special", tag, re.IGNORECASE):
        result["type"] = "special"
        m = re.search(r"Special[-]?\s*(\d+)", tag, re.IGNORECASE)
        if m:
            result["special_num"] = int(m.group(1))
        return result

    # Extra detection
    if re.search(r"Extra", tag, re.IGNORECASE):
        result["type"] = "extra"
        return result

    # Season + Episode parsing — many formats
    # S1 EP01, S01 EP01, S1-EP01, S1 E01, S1EP01, EP - 001, EP01, etc.
    ep_patterns = [
        re.compile(r"S(\d+)\s*(?:P(\d+)\s*)?EP\s*(\d+)", re.IGNORECASE),
        re.compile(r"S(\d+)\s*(?:P(\d+)\s*)?[-]\s*EP\s*(\d+)", re.IGNORECASE),
        re.compile(r"S(\d+)\s*(?:P(\d+)\s*)?\s+E\s*(\d+)", re.IGNORECASE),
        re.compile(r"S(\d+)\s*EP\s*(\d+)", re.IGNORECASE),
        re.compile(r"S(\d+)\s*[-]\s*EP\s*(\d+)", re.IGNORECASE),
        re.compile(r"EP\s*[-]?\s*(\d+)", re.IGNORECASE),
        re.compile(r"EP\s*(\d+)", re.IGNORECASE),
    ]

    for pat in ep_patterns:
        m = pat.match(tag)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                result["season"] = int(groups[0])
                result["episode"] = int(groups[2])
                if groups[1]:
                    result["part"] = int(groups[1])
            elif len(groups) == 2:
                # Could be S1 EP01 or S1EP01
                if tag.lower().startswith("s"):
                    result["season"] = int(groups[0])
                    result["episode"] = int(groups[1])
                else:
                    result["season"] = 0  # unknown season
                    result["episode"] = int(groups[0])
            elif len(groups) == 1:
                result["season"] = 0
                result["episode"] = int(groups[0])
            return result

    # Partial episode match
    ep_match = re.search(r"(\d+)", tag)
    if ep_match:
        result["episode"] = int(ep_match.group(1))

    return result


# ══════════════════════════════════════════════════════════════════════
# AUDIO TYPE PARSING
# ══════════════════════════════════════════════════════════════════════
def parse_audio(audio_str: str) -> str:
    """Normalize audio type to Sub/Dub/Dual/Multi."""
    a = audio_str.lower().strip()
    if "multi" in a:
        return "Multi"
    if "dual" in a:
        return "Dual"
    if "sub" in a and "dub" in a:
        return "Dual"
    if "dub" in a or "dubbed" in a:
        return "Dub"
    if "sub" in a or "subbed" in a:
        return "Sub"
    return audio_str


def normalize_quality(q: str) -> str:
    """Normalize quality string."""
    q = q.strip().lower()
    if "multi" in q:
        return "Multi"
    if q in ("480p", "720p", "1080p", "360p"):
        return q
    return q


# ══════════════════════════════════════════════════════════════════════
# CAPTION PARSING
# ══════════════════════════════════════════════════════════════════════
def parse_caption(text: str) -> dict | None:
    """Parse a caption like '➠ TITLE : SEASON N\\n➠ 480p [AUDIO]'."""
    if not text or text.startswith("Try After"):
        return None

    lines = text.strip().split("\n")
    if len(lines) < 2:
        return None

    # First line: title + season/movie
    first_line = lines[0].lstrip("➠").strip()
    parts = first_line.split(":", 1)
    if len(parts) < 2:
        return None

    title = parts[0].strip()
    info = parts[1].strip()

    # Determine type
    entry_type = "season"
    season_num = 0
    ep_info = info.upper()

    if "MOVIE" in ep_info:
        entry_type = "movie"
        m = re.search(r"MOVIE\s*(\d+)", ep_info, re.IGNORECASE)
        if m:
            season_num = int(m.group(1))
    elif "OVA" in ep_info or "OAD" in ep_info:
        entry_type = "ova"
    elif "FINAL CHAPTERS" in ep_info:
        entry_type = "season"
        season_num = 99  # special marker
    elif "SEASON" in ep_info or "S1" in ep_info or "S0" in ep_info:
        m = re.search(r"(?:SEASON|S)\s*(\d+)", ep_info, re.IGNORECASE)
        if m:
            season_num = int(m.group(1))
    elif re.match(r"^\d+(?:ST|ND|RD|TH)?\s*(?:SEASON)?", ep_info):
        m = re.search(r"(\d+)", ep_info)
        if m:
            season_num = int(m.group(1))

    # Second line: quality + audio
    second_line = lines[1].lstrip("➠").strip() if len(lines) > 1 else ""
    resolution = ""
    audio = ""
    if second_line:
        res_match = re.search(r"(\d{3,4}p|Multi(?:\s*Quality)?)", second_line)
        if res_match:
            resolution = res_match.group(1)
        audio_match = re.search(r"\[([^\]]+)\]", second_line)
        if audio_match:
            audio = audio_match.group(1)

    return {
        "title": normalize_title(title),
        "type": entry_type,
        "season": season_num,
        "resolution": normalize_quality(resolution),
        "audio": parse_audio(audio),
    }


# ══════════════════════════════════════════════════════════════════════
# MAIN TREE BUILDING
# ══════════════════════════════════════════════════════════════════════
def build_tree() -> dict:
    """Build the complete pack tree."""
    messages = load_all_messages()
    packs = reconstruct_packs(messages)
    print(f"Loaded {len(messages)} messages, {len(packs)} packs")

    # Tree structure: {canonical_title: {seasons: {}, movies: [], ovas: [], specials: []}}
    tree: dict[str, dict] = {}
    # Each entry: {start_id, end_id, file_count, caps: [{id, text}], files: [{id, fn, quality, audio}], audio}

    total_files = 0

    for pack_idx, pack in enumerate(packs):
        if not pack:
            continue

        captions = [m for m in pack if m["type"] == "text"]
        docs_in_pack = [m for m in pack if m["type"] == "document"]

        if not docs_in_pack:
            continue

        total_files += len(docs_in_pack)

        # Determine series from captions first, then filenames
        series = None
        entry_type = "season"
        season_num = 1
        resolution = None
        audio = None

        # Try caption parsing
        for cap in captions:
            parsed = parse_caption(cap["text"])
            if parsed:
                series = parsed["title"]
                entry_type = parsed["type"]
                season_num = parsed["season"]
                resolution = parsed["resolution"]
                audio = parsed["audio"]
                break

        # Fallback to filename-based detection
        if series is None:
            parsed_files = [parse_filename(d.get("file_name", "")) for d in docs_in_pack]
            parsed_files = [p for p in parsed_files if p]
            if parsed_files:
                # Use majority-voted title
                titles = [normalize_title(p["title"]) for p in parsed_files]
                series = Counter(titles).most_common(1)[0][0]

                # Detect type from BOTH season tags AND title keywords
                tags = [parse_season_tag(p["season_tag"]) for p in parsed_files]

                # Also check raw titles for type keywords (OVAs/Movies without brackets)
                raw_titles = [p["title"] for p in parsed_files]
                title_has_movie = any(
                    re.search(r"\bMovie\d*\b", t, re.IGNORECASE) for t in raw_titles
                )
                title_has_ova = any(
                    re.search(r"\bOVA\d*\b", t, re.IGNORECASE) for t in raw_titles
                )
                title_has_special = any(
                    re.search(r"\b(Special|Prelude|Episode\s+\w+)\b", t, re.IGNORECASE)
                    for t in raw_titles
                )

                movie_tags = [t for t in tags if t["type"] == "movie"]
                ova_tags = [t for t in tags if t["type"] == "ova"]
                special_tags = [t for t in tags if t["type"] == "special"]
                season_tags = [t for t in tags if t["type"] == "episode"]

                if movie_tags or title_has_movie:
                    entry_type = "movie"
                elif ova_tags or title_has_ova:
                    entry_type = "ova"
                elif special_tags or title_has_special:
                    entry_type = "special"
                elif season_tags:
                    entry_type = "season"
                    seasons = [t.get("season", 1) for t in season_tags]
                    from statistics import mode as get_mode
                    try:
                        season_num = get_mode(seasons)
                    except Exception:
                        season_num = seasons[0]
                elif season_num == 1 and not season_tags and not movie_tags and not ova_tags:
                    # No season tag found — default to season 1 for episodes
                    entry_type = "season"

                # Detect audio from filenames
                audios = [parse_audio(p["audio"]) for p in parsed_files]
                if audios:
                    audio = Counter(audios).most_common(1)[0][0]

        if series is None:
            continue

        # ── Add to tree ──
        if series not in tree:
            tree[series] = {"seasons": {}, "movies": [], "ovas": [], "specials": []}

        entry = {
            "start_id": docs_in_pack[-1]["id"],  # oldest (lowest ID)
            "end_id": docs_in_pack[0]["id"],      # newest (highest ID)
            "file_count": len(docs_in_pack),
            "caps": [{"id": c["id"], "text": c["text"]} for c in captions],
            "files": [
                {
                    "id": d["id"],
                    "filename": d.get("file_name", ""),
                    "quality": "",
                    "audio": "",
                }
                for d in docs_in_pack
            ],
            "audio": audio or "unknown",
        }

        # Parse individual files for quality/audio
        for f in entry["files"]:
            pf = parse_filename(f["filename"])
            if pf:
                f["quality"] = normalize_quality(pf["quality"])
                f["audio"] = parse_audio(pf["audio"])

        if entry_type == "season":
            key = str(season_num)
            if key in tree[series]["seasons"]:
                # Merge: multiple resolution packs for the same season
                existing = tree[series]["seasons"][key]
                existing["start_id"] = min(existing["start_id"], entry["start_id"])
                existing["end_id"] = max(existing["end_id"], entry["end_id"])
                existing["file_count"] += entry["file_count"]
                existing["files"].extend(entry["files"])
                existing["caps"].extend(entry["caps"])
            else:
                tree[series]["seasons"][key] = entry
        elif entry_type == "movie":
            # Merge movies at different resolutions by matching first file ID range
            # (media-group movies share the same first few IDs)
            first_ids = {f["id"] for f in entry["files"]}
            merged = False
            for existing in tree[series]["movies"]:
                existing_ids = {f["id"] for f in existing["files"]}
                # Merge if they share any file IDs (same movie at different res)
                # OR if titles match and one has quality info and the other doesn't
                if first_ids & existing_ids:
                    existing["start_id"] = min(existing["start_id"], entry["start_id"])
                    existing["end_id"] = max(existing["end_id"], entry["end_id"])
                    existing["file_count"] += entry["file_count"]
                    existing["files"].extend(entry["files"])
                    existing["caps"].extend(entry["caps"])
                    merged = True
                    break
            if not merged:
                tree[series]["movies"].append(entry)
        elif entry_type == "ova":
            # Merge OVAs by shared file IDs (different resolutions of same OVA)
            first_ids = {f["id"] for f in entry["files"]}
            merged = False
            for existing in tree[series]["ovas"]:
                existing_ids = {f["id"] for f in existing["files"]}
                if first_ids & existing_ids:
                    existing["start_id"] = min(existing["start_id"], entry["start_id"])
                    existing["end_id"] = max(existing["end_id"], entry["end_id"])
                    existing["file_count"] += entry["file_count"]
                    existing["files"].extend(entry["files"])
                    existing["caps"].extend(entry["caps"])
                    merged = True
                    break
            if not merged:
                # If no ID overlap, check if same content by title+tag pattern
                tree[series]["ovas"].append(entry)
        elif entry_type == "special":
            first_ids = {f["id"] for f in entry["files"]}
            merged = False
            for existing in tree[series]["specials"]:
                existing_ids = {f["id"] for f in existing["files"]}
                if first_ids & existing_ids:
                    existing["start_id"] = min(existing["start_id"], entry["start_id"])
                    existing["end_id"] = max(existing["end_id"], entry["end_id"])
                    existing["file_count"] += entry["file_count"]
                    existing["files"].extend(entry["files"])
                    existing["caps"].extend(entry["caps"])
                    merged = True
                    break
            if not merged:
                tree[series]["specials"].append(entry)

    print(f"Total files accounted for: {total_files}")
    print(f"Total series: {len(tree)}")

    return tree


# ══════════════════════════════════════════════════════════════════════
# RESOLUTION MERGING — merge same-season packs at different resolutions
# ══════════════════════════════════════════════════════════════════════
def merge_resolutions(tree: dict) -> dict:
    """Merge season entries that differ only by resolution."""
    for series, data in tree.items():
        # Collect all season entries by season number
        new_seasons: dict[str, dict] = {}
        for season_key, entry in data["seasons"].items():
            if season_key in new_seasons:
                # Merge: take wider ID range, combine files
                existing = new_seasons[season_key]
                existing["start_id"] = min(existing["start_id"], entry["start_id"])
                existing["end_id"] = max(existing["end_id"], entry["end_id"])
                existing["file_count"] += entry["file_count"]
                existing["files"].extend(entry["files"])
                existing["caps"].extend(entry["caps"])
            else:
                new_seasons[season_key] = entry

        data["seasons"] = new_seasons
    return tree


# ══════════════════════════════════════════════════════════════════════
# DEDUPLICATE MOVIES / OVAs
# ══════════════════════════════════════════════════════════════════════
def deduplicate_entries(tree: dict) -> dict:
    """Remove duplicate movie/OVA entries that point to the same files."""
    for series, data in tree.items():
        # Dedup movies
        seen_ids: set[tuple] = set()
        unique_movies = []
        for entry in data["movies"]:
            key = (entry["start_id"], entry["end_id"])
            if key not in seen_ids:
                seen_ids.add(key)
                unique_movies.append(entry)
        data["movies"] = unique_movies

        # Dedup OVAs
        seen_ids = set()
        unique_ovas = []
        for entry in data["ovas"]:
            key = (entry["start_id"], entry["end_id"])
            if key not in seen_ids:
                seen_ids.add(key)
                unique_ovas.append(entry)
        data["ovas"] = unique_ovas

        # Dedup specials
        seen_ids = set()
        unique_specials = []
        for entry in data["specials"]:
            key = (entry["start_id"], entry["end_id"])
            if key not in seen_ids:
                seen_ids.add(key)
                unique_specials.append(entry)
        data["specials"] = unique_specials
    return tree


# ══════════════════════════════════════════════════════════════════════
# JSON OUTPUT
# ══════════════════════════════════════════════════════════════════════
def generate_json(tree: dict) -> dict:
    """Convert tree to clean JSON-serializable format."""
    output = {}
    for series in sorted(tree.keys()):
        data = tree[series]
        entry = {
            "caps": [],
            "seasons": {},
            "movies": [],
            "ovas": [],
            "specials": [],
        }

        # Merge all caps across all entries
        all_caps = []
        for s in data["seasons"].values():
            all_caps.extend(s["caps"])
        for m in data["movies"]:
            all_caps.extend(m["caps"])
        for o in data["ovas"]:
            all_caps.extend(o["caps"])
        for s in data["specials"]:
            all_caps.extend(s["caps"])
        # Dedup caps by ID
        seen_cap_ids = set()
        for c in all_caps:
            if c["id"] not in seen_cap_ids:
                seen_cap_ids.add(c["id"])
                entry["caps"].append(c)

        # Seasons
        for skey, sdata in sorted(data["seasons"].items()):
            resolutions = defaultdict(list)
            for f in sdata["files"]:
                resolutions[f["quality"] or "unknown"].append(f)

            entry["seasons"][f"Season {skey}"] = {
                "caps": sdata["caps"],
                "resolutions": {
                    q: {
                        "start_id": min(flist, key=lambda x: x["id"])["id"],
                        "end_id": max(flist, key=lambda x: x["id"])["id"],
                        "file_count": len(flist),
                        "audio": sdata["audio"],
                        "files": sorted(flist, key=lambda x: x["id"]),
                    }
                    for q, flist in resolutions.items()
                    if flist
                },
                "start_id": sdata["start_id"],
                "end_id": sdata["end_id"],
                "file_count": sdata["file_count"],
                "audio": sdata["audio"],
            }

        # Movies
        for i, m in enumerate(data["movies"]):
            resolutions = defaultdict(list)
            for f in m["files"]:
                resolutions[f["quality"] or "unknown"].append(f)
            entry["movies"].append({
                "name": f"Movie {i + 1}",
                "caps": m["caps"],
                "resolutions": {
                    q: {
                        "start_id": min(flist, key=lambda x: x["id"])["id"],
                        "end_id": max(flist, key=lambda x: x["id"])["id"],
                        "file_count": len(flist),
                        "audio": m["audio"],
                        "files": sorted(flist, key=lambda x: x["id"]),
                    }
                    for q, flist in resolutions.items()
                    if flist
                },
                "start_id": m["start_id"],
                "end_id": m["end_id"],
                "file_count": m["file_count"],
                "audio": m["audio"],
            })

        # OVAs
        for i, o in enumerate(data["ovas"]):
            resolutions = defaultdict(list)
            for f in o["files"]:
                resolutions[f["quality"] or "unknown"].append(f)
            entry["ovas"].append({
                "name": f"OVA {i + 1}",
                "caps": o["caps"],
                "resolutions": {
                    q: {
                        "start_id": min(flist, key=lambda x: x["id"])["id"],
                        "end_id": max(flist, key=lambda x: x["id"])["id"],
                        "file_count": len(flist),
                        "audio": o["audio"],
                        "files": sorted(flist, key=lambda x: x["id"]),
                    }
                    for q, flist in resolutions.items()
                    if flist
                },
                "start_id": o["start_id"],
                "end_id": o["end_id"],
                "file_count": o["file_count"],
                "audio": o["audio"],
            })

        # Specials
        for i, s in enumerate(data["specials"]):
            entry["specials"].append({
                "name": f"Special {i + 1}",
                "caps": s["caps"],
                "start_id": s["start_id"],
                "end_id": s["end_id"],
                "file_count": s["file_count"],
                "audio": s["audio"],
            })

        output[series] = entry

    return output


# ══════════════════════════════════════════════════════════════════════
# MARKDOWN OUTPUT
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

    # Count totals
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

        # Seasons
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

        # Movies
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

        # OVAs
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

        # Specials
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

    # Summary
    lines.insert(4, f"**Content:** {total_files} files, {total_seasons} seasons, "
                     f"{total_movies} movies, {total_ovas} OVAs, {total_specials} specials")
    lines.insert(5, "")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# HTML NAVIGATIONAL TREE OUTPUT
# ══════════════════════════════════════════════════════════════════════
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
        <span class="series-meta">${meta.join(' · ')}</span>
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
    `${Object.keys(treeData).length} series · ${totalSeasons} seasons · ${totalMovies} movies · ${totalOVAs} OVAs · ${totalSpecials} specials`;
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
      <span>${escapeHtml(key)} — ${fc} files</span>
      <span>
        ${audio ? `<span class="audio-tag">${escapeHtml(audio)}</span> ` : ''}
        <a href="${CHANNEL_URL}/${sid}" target="_blank">Start →</a>
        &nbsp;·&nbsp;
        <a href="${CHANNEL_URL}/${eid}" target="_blank">End →</a>
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
      <span>${escapeHtml(m.name)} — ${m.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${m.start_id}" target="_blank">Start →</a>
        &nbsp;·&nbsp;
        <a href="${CHANNEL_URL}/${m.end_id}" target="_blank">End →</a>
      </span>
    </div>`;
  }
  html += '</div>';
  return html;
}

function buildOVAs(ovas) {
  if (!ovas || !ovas.length) return '';
  let html = '<div class="section"><div class="section-label">📀 OVAs</div>';
  for (const o of ovas) {
    html += `<div class="entry">
      <span>${escapeHtml(o.name)} — ${o.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${o.start_id}" target="_blank">Start →</a>
        &nbsp;·&nbsp;
        <a href="${CHANNEL_URL}/${o.end_id}" target="_blank">End →</a>
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
      <span>${escapeHtml(s.name)} — ${s.file_count} files</span>
      <span>
        <a href="${CHANNEL_URL}/${s.start_id}" target="_blank">Start →</a>
        &nbsp;·&nbsp;
        <a href="${CHANNEL_URL}/${s.end_id}" target="_blank">End →</a>
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


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
def main():
    print("Building pack tree...")
    tree = build_tree()

    print("Merging resolutions...")
    tree = merge_resolutions(tree)

    print("Deduplicating entries...")
    tree = deduplicate_entries(tree)

    print("Generating JSON...")
    tree_json = generate_json(tree)

    print("Writing outputs...")
    # PACK_TREE.json
    json_path = OUT_DIR / "PACK_TREE.json"
    json_path.write_text(json.dumps(tree_json, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ {json_path}")

    # PACK_TREE.md
    md_path = OUT_DIR / "PACK_TREE.md"
    md_content = generate_md(tree_json)
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  ✅ {md_path}")

    # Navigational HTML
    html_path = OUT_DIR / "PACK_TREE.html"
    html_content = generate_html(tree_json)
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  ✅ {html_path}")

    # Summary stats
    total_files = sum(
        sum(s["file_count"] for s in data["seasons"].values())
        + sum(m["file_count"] for m in data["movies"])
        + sum(o["file_count"] for o in data["ovas"])
        + sum(s["file_count"] for s in data["specials"])
        for data in tree_json.values()
    )
    print(f"\n{'='*60}")
    print(f"Tree complete!")
    print(f"  Series:    {len(tree_json)}")
    print(f"  Seasons:   {sum(len(data['seasons']) for data in tree_json.values())}")
    print(f"  Movies:    {sum(len(data['movies']) for data in tree_json.values())}")
    print(f"  OVAs:      {sum(len(data['ovas']) for data in tree_json.values())}")
    print(f"  Specials:  {sum(len(data['specials']) for data in tree_json.values())}")
    print(f"  Total files: {total_files}")
    print(f"{'='*60}")


if __name__ == "__main__":
    from collections import Counter
    from statistics import mode as get_mode
    main()
