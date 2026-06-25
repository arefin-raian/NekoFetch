"""Torrent metadata: a minimal bencode decoder + episode ordering.

No third-party torrent library is required to read a ``.torrent``'s file list —
bencode is trivial. We use the file list to map a release's videos to an ordered
EP1..EPN sequence while preserving the original filenames, and to classify
movies / specials / OVAs.
"""

from __future__ import annotations

import re

VIDEO_EXT = (".mkv", ".mp4", ".avi", ".ts", ".m4v", ".mov")


# --------------------------------------------------------------------------- #
# bencode
# --------------------------------------------------------------------------- #

def bdecode(data: bytes):
    """Decode a bencoded byte string into Python objects."""
    def parse(i: int):
        c = data[i:i + 1]
        if c == b"i":
            j = data.index(b"e", i)
            return int(data[i + 1:j]), j + 1
        if c.isdigit():
            colon = data.index(b":", i)
            n = int(data[i:colon])
            start = colon + 1
            return data[start:start + n], start + n
        if c == b"l":
            i += 1
            out = []
            while data[i:i + 1] != b"e":
                v, i = parse(i)
                out.append(v)
            return out, i + 1
        if c == b"d":
            i += 1
            out = {}
            while data[i:i + 1] != b"e":
                k, i = parse(i)
                v, i = parse(i)
                out[k] = v
            return out, i + 1
        raise ValueError(f"invalid bencode at byte {i}")

    value, _ = parse(0)
    return value


def torrent_files(data: bytes) -> tuple[str, list[dict]]:
    """Return (torrent_name, files) from raw .torrent bytes.

    Each file: ``{"path": rel/path, "name": basename, "length": bytes, "index": i}``
    (index is the bencode file order — needed for aria2c ``--select-file``).
    """
    meta = bdecode(data)
    info = meta[b"info"]
    name = info[b"name"].decode("utf-8", "replace")
    files: list[dict] = []
    if b"files" in info:
        for idx, f in enumerate(info[b"files"], start=1):
            parts = [p.decode("utf-8", "replace") for p in f[b"path"]]
            rel = "/".join(parts)
            files.append({"path": f"{name}/{rel}", "name": parts[-1],
                          "length": f[b"length"], "index": idx})
    else:
        files.append({"path": name, "name": name, "length": info[b"length"], "index": 1})
    return name, files


# --------------------------------------------------------------------------- #
# episode ordering
# --------------------------------------------------------------------------- #

_EXT_RE = re.compile(r"\.(mkv|mp4|avi|ts|m4v|mov)$", re.IGNORECASE)
_RES_RE = re.compile(r"(\d{3,4})p", re.IGNORECASE)


def parse_release_meta(name: str) -> dict:
    """Classify one filename: kind, season, episode number, resolution."""
    base = _EXT_RE.sub("", name)
    low = base.lower()

    kind = "episode"
    if re.search(r"\b(ncop|nced|opening|ending|preview|menu|pv)\b", low):
        kind = "extra"
    elif re.search(r"\bova\b", low):
        kind = "ova"
    elif re.search(r"\b(special|specials|sp\d+|extra|oad)\b", low):
        kind = "special"
    elif re.search(r"\bmovie\b", low):
        kind = "movie"

    # season — try the most explicit forms first; default 1 if only episodes given
    season = 1
    ms = (re.search(r"\bs(\d{1,2})\s*e\s*\d", low)        # S1E1 / S01 E01 / S1 E 1
          or re.search(r"\bseason\s*(\d{1,2})\b", low)     # Season 1
          or re.search(r"\bs(\d{1,2})\b", low))            # S2
    if ms:
        season = int(ms.group(1))

    # episode number — ordered most-specific → least, stop at first hit.
    # Anchored on the STABLE 'E<num>' / 'episode <num>' / separator-number forms
    # rather than any audio/quality keyword (Dual/Sub/Multi vary, these don't).
    episode = None
    for pat in (
        r"\bs\d{1,2}\s*e\s*(\d{1,3})\b",                  # S1 E12 / S01E01 / S1 E 12
        r"\bseason\s*\d{1,2}\s*episode\s*(\d{1,3})\b",    # Season 1 Episode 1
        r"\bepisode\s*(\d{1,3})\b",                       # Episode 12
        r"\bep\s*[._-]?\s*(\d{1,3})\b",                   # EP01 / Ep.1
        r"(?:^|[\s\-_])e(\d{1,3})\b",                     # - E17 / E17 / _E001
        r"-\s*(\d{1,3})(?:v\d)?\s*[\(\[]",                # - 24 [Dual]
        r"-\s*(\d{1,3})(?:v\d)?(?=\s|$)",                 # - 24
        r"\s(\d{1,3})\s*[\(\[]",                          #  24 (1080p)
        r"#(\d{1,3})\b",                                  # #01
    ):
        m = re.search(pat, low)
        if m:
            episode = int(m.group(1))
            break

    res = None
    mr = _RES_RE.search(low)
    if mr:
        res = f"{mr.group(1)}p"

    return {"kind": kind, "season": season, "episode": episode,
            "resolution": res, "base": base}


def _natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def order_episodes(files: list[dict]) -> list[dict]:
    """Order a release's video files into an EP1..EPN sequence.

    Returns each kept file augmented with ``seq`` (1-based), ``season``,
    ``episode``, ``kind``, ``resolution`` and the original ``name``/``path``.
    Movies/specials/OVAs/extras are ordered after the main episodes. Original
    filenames are preserved; only the sequence index is synthesised.
    """
    vids = [f for f in files if f["name"].lower().endswith(VIDEO_EXT)]
    if not vids:
        return []
    enriched = []
    for f in vids:
        m = parse_release_meta(f["name"])
        enriched.append({**f, **m})

    # A lone video file with no detectable episode number is almost always a
    # movie (e.g. "A Silent Voice"), even without the word "movie" in the name.
    if len(enriched) == 1 and enriched[0]["kind"] == "episode" \
            and enriched[0]["episode"] is None:
        enriched[0]["kind"] = "movie"

    main = [e for e in enriched if e["kind"] == "episode"]
    movies = [e for e in enriched if e["kind"] == "movie"]
    extras = [e for e in enriched if e["kind"] in ("special", "ova", "extra")]

    # If episode numbers were detected for the main set, sort by (season, ep);
    # otherwise fall back to a natural filename sort (stable per release).
    if main and all(e["episode"] is not None for e in main):
        main.sort(key=lambda e: (e["season"], e["episode"]))
    else:
        main.sort(key=lambda e: _natural_key(e["name"]))
    movies.sort(key=lambda e: _natural_key(e["name"]))
    extras.sort(key=lambda e: _natural_key(e["name"]))

    ordered = main + movies + extras
    for seq, e in enumerate(ordered, start=1):
        e["seq"] = seq
    return ordered
