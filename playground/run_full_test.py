"""Detailed verification harness for BOTH sources.

Downloads ep1 across an era-diverse title set from KickAssAnime and AniKoto, then
performs deep analysis of every output:
  - container + format (ffprobe)
  - video stream: codec, resolution, fps, duration
  - audio tracks: count, languages, codecs, durations (+ drift vs video)
  - subtitle tracks: count, languages, codec
  - label correctness (audio-track count vs SUBBED/DUBBED/Dual/Multi)
  - corruption decode-check (ffmpeg decodes a slice; reports decode errors)
  - subtitle hygiene: 'kaa.mx' watermark ABSENT, '@AniXWeebs' branding PRESENT

Outputs:
  playground/full_test/<source>/<title>/...        media + sidecars
  playground/full_test/RESULTS_FULL.json           structured machine record
  playground/full_test/run.log                      incremental log
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nekofetch.sources._hls import find_ffmpeg, find_ffprobe, ts_is_clean  # noqa: E402
from nekofetch.sources.anikoto import AnikotoSource  # noqa: E402
from nekofetch.sources.kickassanime import KickAssAnimeSource  # noqa: E402
from nekofetch.domain.enums import AudioType  # noqa: E402

ROOT = Path(__file__).parent / "full_test"
FFMPEG = find_ffmpeg()
FFPROBE = find_ffprobe()
PNG_SIG = b"\x89PNG\r\n\x1a\n"

# (display, search query, era). Spans 1998->2024 and BOTH KAA audio shapes.
TITLES = [
    ("Cowboy Bebop", "Cowboy Bebop", "1998 classic"),
    ("Death Note", "Death Note", "2006 older"),
    ("Attack on Titan", "Attack on Titan", "2013 mid"),
    ("Demon Slayer", "Demon Slayer", "2019 mid"),
    ("Frieren", "Frieren", "2023 recent"),
    ("Solo Leveling", "Solo Leveling", "2024 recent"),
]

EXPECTED_AUDIO = {"SUBBED": 1, "DUBBED": 1, "Dual Audio": 2, "Multi Audio": 3}


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (ROOT / "run.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "_", s).strip("_").lower()


def ffprobe(path: Path) -> dict:
    r = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {}


def decode_check(path: Path, seconds: int = 12) -> dict:
    """Decode a slice with ffmpeg; any stderr output means decode errors."""
    r = subprocess.run(
        [FFMPEG, "-v", "error", "-xerror", "-t", str(seconds), "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    err = r.stderr.strip()
    return {"clean": r.returncode == 0 and not err, "errors": err[:300]}


def extract_subtitle_text(path: Path, index: int = 0) -> str:
    r = subprocess.run(
        [FFMPEG, "-v", "quiet", "-i", str(path), "-map", f"0:s:{index}", "-f", "ass", "-"],
        capture_output=True, text=True,
    )
    return r.stdout


def analyze(path: Path) -> dict:
    info: dict = {"name": path.name, "size_mb": round(path.stat().st_size / 1048576, 2)}
    raw_head = path.open("rb").read(16)
    info["residual_png_in_header"] = raw_head[:8] == PNG_SIG
    if path.suffix == ".ts":
        info["ts_clean"] = ts_is_clean(path.read_bytes())

    probe = ffprobe(path)
    fmt = probe.get("format", {})
    info["format"] = fmt.get("format_name")
    info["duration_s"] = round(float(fmt.get("duration", 0)), 1)
    v, audios, subs = None, [], []
    for s in probe.get("streams", []):
        t = s.get("codec_type")
        if t == "video" and v is None:
            v = {"codec": s.get("codec_name"), "w": s.get("width"), "h": s.get("height"),
                 "fps": s.get("r_frame_rate"), "dur": round(float(s.get("duration", fmt.get("duration", 0) or 0)), 1)}
        elif t == "audio":
            audios.append({"codec": s.get("codec_name"),
                           "lang": s.get("tags", {}).get("language", "?"),
                           "title": s.get("tags", {}).get("title", ""),
                           "channels": s.get("channels"),
                           "dur": round(float(s.get("duration", 0) or 0), 1)})
        elif t == "subtitle":
            subs.append({"codec": s.get("codec_name"),
                         "lang": s.get("tags", {}).get("language", "?"),
                         "title": s.get("tags", {}).get("title", "")})
    info["video"] = v
    info["audio"] = audios
    info["subtitles_count"] = len(subs)
    info["subtitle_langs"] = [s["lang"] for s in subs]
    info["decode"] = decode_check(path)

    # audio/video duration drift
    if v and audios:
        drifts = [abs((a["dur"] or 0) - (v["dur"] or 0)) for a in audios if a["dur"]]
        info["max_av_drift_s"] = round(max(drifts), 1) if drifts else None

    # subtitle hygiene on first sub track
    if subs:
        txt = extract_subtitle_text(path, 0)
        info["sub_check"] = {
            "watermark_kaa_mx": "kaa.mx" in txt.lower(),
            "branding_anixweebs": "@AniXWeebs" in txt,
            "telegram_blue": "D99E22" in txt,
        }
    return info


def verify(label: str, analysis: dict) -> list[str]:
    """Return a list of problems; empty == all good."""
    problems = []
    if analysis.get("residual_png_in_header"):
        problems.append("CORRUPT: PNG header (mask not stripped)")
    dec = analysis.get("decode", {})
    if not dec.get("clean"):
        problems.append(f"DECODE ERRORS: {dec.get('errors','')[:120]}")
    if analysis.get("ts_clean") is False:
        problems.append("TS integrity < 99.9%")
    exp = EXPECTED_AUDIO.get(label)
    got = len(analysis.get("audio", []))
    if exp is not None and got != exp:
        problems.append(f"AUDIO COUNT mismatch: label={label} expects {exp}, got {got}")
    drift = analysis.get("max_av_drift_s")
    if drift is not None and drift > 2.0:
        problems.append(f"A/V DRIFT {drift}s")
    sc = analysis.get("sub_check")
    if sc:
        if sc["watermark_kaa_mx"]:
            problems.append("WATERMARK kaa.mx still present in subtitle")
        if not sc["branding_anixweebs"]:
            problems.append("BRANDING @AniXWeebs missing from subtitle")
    return problems


async def run_one(source, src_name, display, query, era, rec):
    out_dir = ROOT / src_name / slug(display)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        results = await source.search(query)
        results = [r for r in results
                   if not re.search(r"\b(pv|recap|digest|official|mini)\b", r.source_ref)] or results
        rec["search_count"] = len(results)
        if not results:
            rec["error"] = "no search results"
            return
        stub = results[0]
        rec["picked"] = {"ref": stub.source_ref, "title": stub.title}
        details = await source.get_details(stub.source_ref)
        rec["details"] = {"title": details.title, "year": details.release_date,
                          "genres": details.genres[:5], "synopsis": bool(details.synopsis)}
        eps = await source.get_episodes(stub.source_ref)
        if hasattr(source, "_resolve_episode_refs"):
            await source._resolve_episode_refs(eps)
        rec["episode_count"] = len(eps)
        ep1 = next((e for e in eps if e.number == 1), eps[0] if eps else None)
        if not ep1:
            rec["error"] = "no ep1"
            return
        variants = await source.get_variants(ep1.source_ref)
        rec["variant_count"] = len(variants)
        # pick the SUBBED-side variant (KAA assembles full multi-audio from it)
        variant = next((v for v in variants if v.audio == AudioType.SUBBED), variants[0] if variants else None)
        if not variant:
            rec["error"] = "no variant"
            return
        # set 720p
        vinfo = json.loads(variant.source_ref)
        if "quality" in vinfo:
            vinfo["quality"] = "720"
            variant.source_ref = json.dumps(vinfo)

        existing = [p for p in out_dir.glob("ep01.*") if p.suffix in (".mkv", ".ts", ".mp4")]
        t0 = time.monotonic()
        if existing:
            rec["download"] = {"skipped": existing[0].name}
            media = existing[0]
            res = {}
        else:
            log(f"  DL {src_name}/{display} ...")
            res = await source.download(variant, out_dir / "ep01")
            media = sorted(out_dir.glob("ep01.*"),
                           key=lambda p: p.stat().st_size, reverse=True)[0]
        elapsed = round(time.monotonic() - t0, 1)
        rec["label"] = res.get("label")
        rec["audio_tracks_reported"] = res.get("audio_tracks")
        rec["warnings"] = res.get("warnings", [])
        rec["elapsed_s"] = elapsed
        a = analyze(media)
        rec["analysis"] = a
        rec["problems"] = verify(res.get("label", ""), a)
        log(f"    {display}: label={res.get('label')} "
            f"V={bool(a.get('video'))} A={len(a.get('audio',[]))} S={a.get('subtitles_count')} "
            f"decode={'OK' if a.get('decode',{}).get('clean') else 'ERR'} "
            f"problems={len(rec['problems'])}")
    except Exception as e:
        rec["error"] = f"{e}\n{traceback.format_exc()[-300:]}"
        log(f"    {display}: EXCEPTION {e}")


async def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "run.log").write_text("", encoding="utf-8")
    log(f"=== FULL VERIFICATION TEST === ffmpeg={bool(FFMPEG)} ffprobe={bool(FFPROBE)}")
    records = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "sources": {}}

    for src_name, factory in [
        ("kickassanime", lambda: KickAssAnimeSource(preferred_quality="720p")),
        ("anikoto", lambda: AnikotoSource(preferred_quality="720")),
    ]:
        log(f"--- SOURCE: {src_name} ---")
        source = factory()
        cases = []
        try:
            for display, query, era in TITLES:
                rec = {"title": display, "era": era, "query": query}
                log(f"CASE {src_name} :: {display} ({era})")
                try:
                    await asyncio.wait_for(
                        run_one(source, src_name, display, query, era, rec), timeout=600
                    )
                except asyncio.TimeoutError:
                    rec["error"] = "timed out (>600s)"
                    log(f"    {display}: TIMEOUT")
                cases.append(rec)
                records["sources"][src_name] = cases
                (ROOT / "RESULTS_FULL.json").write_text(
                    json.dumps(records, indent=2, default=str), encoding="utf-8")
                await asyncio.sleep(6)  # be gentle on the CDN between episodes
        finally:
            await source.close()

    log("=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
