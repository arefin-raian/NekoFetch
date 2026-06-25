"""Nyaa source validation harness.

Phase 1 (cheap, all titles): search -> rank -> episodes -> ordering. Validates
  search accuracy, dual-audio detection, seeder prioritization, episode ordering,
  movie/season/special handling -- all from tiny .torrent metadata, no content.
Phase 2 (expensive, subset): download EP1 via aria2c + ffmpeg transcode. Validates
  the torrent download, naming preservation, and resolution generation.

Outputs: playground/nyaa_test/RESULTS.json + run.log + downloaded media.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nekofetch.sources._hls import find_ffprobe  # noqa: E402
from nekofetch.sources._transcode import transcode_renditions  # noqa: E402
from nekofetch.sources.nyaa import NyaaSource, is_dual_audio  # noqa: E402

ROOT = Path(__file__).parent / "nyaa_test"
FFPROBE = find_ffprobe()

# (query, expectation note, download-in-phase-2?)
TITLES = [
    ("Attack on Titan", "dual-audio, multi-season batch", True),
    ("Frieren", "recent series, SxxExx naming", False),
    ("Bocchi the Rock", "single-cour series", True),
    ("A Silent Voice", "movie (single file)", False),
    ("Cowboy Bebop", "classic + movie present", False),
    ("Spy x Family", "dual-audio, multi-cour", False),
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (ROOT / "run.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ffprobe(path: str) -> dict:
    r = subprocess.run([FFPROBE, "-v", "quiet", "-print_format", "json",
                        "-show_format", "-show_streams", path], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


async def phase1(n: NyaaSource, query: str, note: str) -> dict:
    rec: dict = {"query": query, "note": note}
    res = await n.search(query)
    rec["result_count"] = len(res)
    if not res:
        rec["error"] = "no results"
        return rec
    # ranking: collect top-8 for inspection
    ranked = [json.loads(s.source_ref) for s in res[:8]]
    rec["top"] = {"title": ranked[0]["title"], "seeders": ranked[0]["seeders"],
                  "dual_audio": ranked[0]["dual_audio"], "size": ranked[0]["size_text"],
                  "trusted": ranked[0]["trusted"]}
    # validate ranking: any dual-audio present should outrank non-dual; within
    # a group, seeders must be descending.
    da = [r for r in ranked if r["dual_audio"]]
    rec["dual_audio_candidates"] = len(da)
    rec["ranking_ok"] = (
        all(ranked[i]["seeders"] >= ranked[i + 1]["seeders"]
            for i in range(len(da) - 1))  # dual group sorted by seeders
        and (not da or ranked[0]["dual_audio"])  # a dual release leads if any exist
    )
    # episodes / ordering
    eps = await n.get_episodes(res[0].source_ref)
    rec["episode_count"] = len(eps)
    kinds: dict[str, int] = {}
    seqs = []
    for ep in eps:
        e = json.loads(ep.source_ref)
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        seqs.append((ep.number, e["season"], e.get("episode"), e["kind"], e["name"]))
    rec["kinds"] = kinds
    rec["ep1"] = {"name": seqs[0][4], "season": seqs[0][1], "episode": seqs[0][2]} if seqs else None
    # ordering monotonic for main episodes
    main = [s for s in seqs if s[3] == "episode" and s[2] is not None]
    rec["ordering_monotonic"] = all(main[i][2] <= main[i + 1][2] or main[i][1] < main[i + 1][1]
                                    for i in range(len(main) - 1))
    rec["sample"] = [{"EP": s[0], "name": s[4][:60]} for s in seqs[:3]]
    return rec


async def phase2(n: NyaaSource, query: str, rec: dict) -> None:
    res = await n.search(query)
    if not res:
        return
    eps = await n.get_episodes(res[0].source_ref)
    if not eps:
        return
    v = await n.get_variants(eps[0].source_ref)
    e = json.loads(eps[0].source_ref)
    out_dir = ROOT / query.replace(" ", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"  [{query}] downloading EP1: {e['name']} ({e['length']/1048576:.0f}MB)")
    t0 = time.monotonic()
    try:
        r = await n.download(v[0], out_dir / "ep01")
    except Exception as exc:
        rec["download"] = {"error": str(exc)}
        log(f"  [{query}] download FAILED: {exc}")
        return
    dl_s = round(time.monotonic() - t0, 0)
    src = Path(r["path"])
    rec["download"] = {
        "name": r["name"], "size_mb": round(r["bytes"] / 1048576, 1),
        "name_preserved": r["name"] == e["name"], "seconds": dl_s,
        "speed_mbps": round((r["bytes"] / 1048576) / dl_s, 2) if dl_s else None,
    }
    probe = ffprobe(str(src))
    v0 = next((s for s in probe.get("streams", []) if s["codec_type"] == "video"), {})
    rec["source_probe"] = {
        "duration_s": round(float(probe.get("format", {}).get("duration", 0)), 0),
        "resolution": f"{v0.get('width')}x{v0.get('height')}", "vcodec": v0.get("codec_name"),
        "audio_tracks": sum(1 for s in probe.get("streams", []) if s["codec_type"] == "audio"),
        "sub_tracks": sum(1 for s in probe.get("streams", []) if s["codec_type"] == "subtitle"),
    }
    log(f"  [{query}] transcoding (veryfast)...")
    t0 = time.monotonic()
    m = await transcode_renditions(src, out_dir / "renditions", "ep01",
                                   source_resolution=e.get("resolution"), preset="veryfast")
    m["transcode_seconds"] = round(time.monotonic() - t0, 0)
    rec["transcode"] = m
    log(f"  [{query}] renditions: "
        f"{[(x.get('label'), x.get('size_mb')) for x in m['renditions']]} "
        f"oversized_1080={m['oversized_1080']}")


async def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "run.log").write_text("", encoding="utf-8")
    log("=== NYAA SOURCE VALIDATION ===")
    # dual-audio fuzzy unit check
    fuzz = {s: is_dual_audio(s) for s in
            ["Dual Audio", "Dual-Audio", "Dual_Audio", "[DualAudio]", "DUAL.AUDIO",
             "Multi Audio", "dual subtitle"]}
    log(f"dual-audio fuzzy: {fuzz}")

    records: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "dual_audio_fuzzy": fuzz, "cases": []}
    n = NyaaSource()
    try:
        for query, note, dl in TITLES:
            log(f"CASE {query} ({note})")
            rec = {}
            try:
                rec = await phase1(n, query, note)
            except Exception as exc:
                rec = {"query": query, "error": f"{exc}\n{traceback.format_exc()[-300:]}"}
            records["cases"].append(rec)
            (ROOT / "RESULTS.json").write_text(json.dumps(records, indent=2, default=str),
                                               encoding="utf-8")
        # phase 2 downloads (subset)
        log("--- PHASE 2: downloads + transcode ---")
        for query, note, dl in TITLES:
            if not dl:
                continue
            rec = next((c for c in records["cases"] if c.get("query") == query), None)
            if rec is None or rec.get("error"):
                continue
            try:
                await asyncio.wait_for(phase2(n, query, rec), timeout=1500)
            except Exception as exc:
                rec["phase2_error"] = str(exc)
                log(f"  [{query}] phase2 error: {exc}")
            (ROOT / "RESULTS.json").write_text(json.dumps(records, indent=2, default=str),
                                               encoding="utf-8")
    finally:
        await n.close()
    log("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
