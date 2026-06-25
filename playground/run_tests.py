"""NekoFetch source stress-test harness.

Drives BOTH sources (KickAssAnime + AniKoto) across a curated, era-diverse set
of popular anime. For each (source, title) it exercises the full pipeline:
search -> details -> episodes -> variants -> download (ep1, sub + dub where
available), then performs byte-level analysis of every output.

Everything is captured into playground/test_results/:
  test_results/<source>/<title>/epXX_<kind>.<ext>   downloaded media + sidecars
  test_results/RESULTS.json                          structured machine record
  test_results/run.log                               incremental human log

Resumable: existing, already-validated outputs are skipped.
Run:  .venv/Scripts/python.exe playground/run_tests.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nekofetch.sources._hls import TS_PKT, ts_is_clean  # noqa: E402
from nekofetch.sources.anikoto import AnikotoSource  # noqa: E402
from nekofetch.sources.kickassanime import KickAssAnimeSource  # noqa: E402
from nekofetch.domain.enums import AudioType  # noqa: E402

ROOT = Path(__file__).parent / "test_results"
PNG_SIG = b"\x89PNG\r\n\x1a\n"


# Era-diverse, broadly popular titles. ~12-episode seasons preferred where the
# show has one; others included for era coverage.
TITLES = [
    {"name": "Frieren Beyond Journeys End", "query": "Frieren", "era": "2023 (recent)"},
    {"name": "Jujutsu Kaisen", "query": "Jujutsu Kaisen", "era": "2020 (recent)"},
    {"name": "Kimetsu no Yaiba", "query": "Demon Slayer", "era": "2019 (mid)"},
    {"name": "Shingeki no Kyojin", "query": "Attack on Titan", "era": "2013 (mid)"},
    {"name": "Erased", "query": "Erased", "era": "2016 (mid, 12 eps)"},
    {"name": "Death Note", "query": "Death Note", "era": "2006 (older)"},
    {"name": "Cowboy Bebop", "query": "Cowboy Bebop", "era": "1998 (classic)"},
]


def slugify(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name).strip("_").lower()


@dataclass
class CaseRecord:
    source: str
    title: str
    era: str
    query: str
    stages: dict = field(default_factory=dict)
    downloads: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (ROOT / "run.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def analyze_file(path: Path) -> dict:
    """Byte-level analysis of a downloaded media file."""
    info: dict = {"name": path.name, "ext": path.suffix.lstrip(".")}
    if not path.exists():
        info["error"] = "missing"
        return info
    data = path.read_bytes()
    info["bytes"] = len(data)
    info["size_mb"] = round(len(data) / 1048576, 2)
    head = data[:16]
    info["magic"] = head[:8].hex()
    # container sniff
    if head[4:8] == b"ftyp":
        info["container"] = "mp4/mov"
    elif head[:1] == b"\x47":
        info["container"] = "mpeg-ts"
    elif head[:4] == b"\x1aE\xdf\xa3":
        info["container"] = "matroska/webm"
    elif head[:8] == PNG_SIG:
        info["container"] = "PNG(!!corrupt — masked stream not stripped)"
    else:
        info["container"] = "unknown"
    # residual PNG masks (the original corruption signature)
    png_count = data.count(PNG_SIG)
    info["residual_png_masks"] = png_count
    # TS integrity
    if info["container"] == "mpeg-ts":
        info["ts_clean"] = ts_is_clean(data)
        rem = len(data) % TS_PKT
        start = rem if data[rem:rem + 1] == b"\x47" else 0
        grid = range(start, len(data) - TS_PKT, TS_PKT)
        hits = sum(1 for k in grid if data[k] == 0x47)
        info["ts_sync_pct"] = round(100 * hits / len(grid), 2) if len(grid) else 0
    # too-small heuristic (error page / truncated)
    info["suspicious_small"] = len(data) < 1_000_000
    return info


def analyze_subtitle(path: Path) -> dict:
    info = {"name": path.name, "bytes": path.stat().st_size}
    raw = path.read_bytes()
    info["is_webvtt"] = raw[:6] == b"WEBVTT"
    info["is_srt"] = bool(re.match(rb"\s*1\s*\r?\n\d{2}:\d{2}:\d{2}", raw[:64]))
    info["cue_count"] = raw.count(b"-->")
    info["empty"] = len(raw) == 0
    return info


async def run_case(source, src_name: str, t: dict, rec: CaseRecord) -> None:
    out_dir = ROOT / src_name / slugify(t["name"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- search ----
    try:
        results = await source.search(t["query"])
        rec.stages["search"] = {"count": len(results),
                                "top": results[0].title if results else None,
                                "top_ref": results[0].source_ref if results else None}
        if not results:
            rec.errors.append("search returned no results")
            return
        stub = results[0]
    except Exception as e:
        rec.errors.append(f"search failed: {e}")
        return

    # ---- details ----
    try:
        details = await source.get_details(stub.source_ref)
        rec.stages["details"] = {
            "title": details.title, "year": details.release_date,
            "genres": details.genres[:6], "has_synopsis": bool(details.synopsis),
            "poster": bool(details.poster_url),
        }
        if not details.title:
            rec.warnings.append("details: empty title")
        if not details.synopsis:
            rec.warnings.append("details: missing synopsis")
    except Exception as e:
        rec.errors.append(f"details failed: {e}")

    # ---- episodes ----
    try:
        eps = await source.get_episodes(stub.source_ref)
        if hasattr(source, "_resolve_episode_refs"):
            await source._resolve_episode_refs(eps)
        rec.stages["episodes"] = {"count": len(eps),
                                  "first_num": eps[0].number if eps else None,
                                  "first_title": eps[0].title if eps else None}
        if not eps:
            rec.errors.append("no episodes")
            return
    except Exception as e:
        rec.errors.append(f"episodes failed: {e}")
        return

    # Select ep1 candidates per audio. KAA encodes language in the ref; AniKoto
    # exposes both audios as separate variants of one episode.
    ep1_by_lang: dict[str, object] = {}
    for ep in eps:
        if ep.number != 1:
            continue
        lang = "default"
        m = re.search(r"/(ja-JP|en-US)/", ep.source_ref)
        if m:
            lang = m.group(1)
        ep1_by_lang.setdefault(lang, ep)
    rec.stages["ep1_langs"] = list(ep1_by_lang.keys())

    # ---- variants + download ----
    # Build a list of (kind_label, quality, variant) to download.
    plan: list[tuple[str, str, object]] = []
    try:
        for lang, ep in ep1_by_lang.items():
            variants = await source.get_variants(ep.source_ref)
            vsummary = [{"audio": v.audio.name, "res": v.resolution,
                         "subs": v.subtitles} for v in variants]
            rec.stages.setdefault("variants", {})[lang] = vsummary
            if not variants:
                rec.warnings.append(f"no variants for lang={lang}")
                continue
            # pick one SUBBED and one DUBBED
            sub_v = next((v for v in variants if v.audio == AudioType.SUBBED), None)
            dub_v = next((v for v in variants if v.audio == AudioType.DUBBED), None)
            if sub_v and not any(p[0] == "sub" for p in plan):
                plan.append(("sub", "720", sub_v))
            if dub_v and not any(p[0] == "dub" for p in plan):
                plan.append(("dub", "1080", dub_v))
    except Exception as e:
        rec.errors.append(f"variants failed: {e}\n{traceback.format_exc()[-400:]}")

    for kind, quality, variant in plan:
        dest = out_dir / f"ep01_{kind}"
        # resume: skip if a non-trivial output already exists
        existing = [p for p in out_dir.glob(f"ep01_{kind}.*")
                    if p.suffix in (".ts", ".mp4", ".mkv") and p.stat().st_size > 1_000_000]
        dl: dict = {"kind": kind, "quality": quality, "audio": variant.audio.name}
        try:
            # set quality on the source if it supports it
            if hasattr(variant, "source_ref"):
                info = json.loads(variant.source_ref)
                if "quality" in info:
                    info["quality"] = quality
                    variant.source_ref = json.dumps(info)
            t0 = time.monotonic()
            if existing:
                dl["skipped_existing"] = existing[0].name
                result = {"bytes": existing[0].stat().st_size, "complete": True}
                media = existing[0]
            else:
                log(f"  DL {src_name}/{t['name']} {kind}@{quality} ...")
                result = await source.download(variant, dest)
            dl["elapsed_s"] = round(time.monotonic() - t0, 1)
            dl["result"] = {k: v for k, v in result.items() if k != "checksum"}
            mb = result.get("bytes", 0) / 1048576
            dl["throughput_mbps"] = round(mb / dl["elapsed_s"], 2) if dl["elapsed_s"] else None
            # analyze media
            media = sorted(out_dir.glob(f"ep01_{kind}.*"),
                           key=lambda p: p.stat().st_size, reverse=True)[0]
            dl["analysis"] = analyze_file(media)
            # analyze subtitle sidecars
            subs = [analyze_subtitle(p) for p in out_dir.glob(f"ep01_{kind}.*")
                    if p.suffix in (".vtt", ".srt")]
            if subs:
                dl["subtitles"] = subs
            for w in result.get("warnings", []):
                rec.warnings.append(f"{kind}: {w}")
        except Exception as e:
            dl["error"] = str(e)
            rec.errors.append(f"download {kind} failed: {e}")
        rec.downloads.append(dl)


async def benchmark_concurrency() -> dict:
    """Benchmark segment-fetch concurrency on one AniKoto sub stream."""
    from nekofetch.sources._hls import download_hls_ts
    log("Benchmarking concurrency levels on one stream ...")
    src = AnikotoSource(preferred_quality="720")
    out: dict = {"levels": []}
    try:
        eps = await src.get_episodes("naruto-shippuden-c8gov")
        await src._resolve_episode_refs(eps)
        variants = await src.get_variants(eps[0].source_ref)
        sub = next(v for v in variants if v.audio == AudioType.SUBBED)
        info = json.loads(sub.source_ref)
        cand = info["candidates"][0]
        url, ref = cand["video_url"], cand.get("referer")
        hdrs = {"referer": ref, "origin": (ref or "").rstrip("/")}
        bench_dir = ROOT / "_benchmark"
        bench_dir.mkdir(parents=True, exist_ok=True)
        for c in (4, 8, 16, 24):
            stats: dict = {}
            try:
                p = await download_hls_ts(src.http, url, hdrs, "720",
                                          bench_dir / f"c{c}", concurrency=c, stats=stats)
                p.unlink(missing_ok=True)
                out["levels"].append(stats)
                log(f"  concurrency={c}: {stats.get('throughput_mbps')} MB/s "
                    f"({stats.get('elapsed_s')}s)")
            except Exception as e:
                out["levels"].append({"concurrency": c, "error": str(e)})
    except Exception as e:
        out["error"] = str(e)
    finally:
        await src.close()
    return out


async def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "run.log").write_text("", encoding="utf-8")
    log("=== NekoFetch source stress test starting ===")

    records: list[CaseRecord] = []
    sources = {
        "anikoto": lambda: AnikotoSource(preferred_quality="720"),
        "kickassanime": lambda: KickAssAnimeSource(preferred_quality="720p"),
    }

    for src_name, factory in sources.items():
        log(f"--- SOURCE: {src_name} ---")
        source = factory()
        try:
            for t in TITLES:
                rec = CaseRecord(source=src_name, title=t["name"], era=t["era"], query=t["query"])
                log(f"CASE {src_name} :: {t['name']} ({t['era']})")
                try:
                    await run_case(source, src_name, t, rec)
                except Exception as e:
                    rec.errors.append(f"case crashed: {e}\n{traceback.format_exc()[-400:]}")
                records.append(rec)
                # incremental save
                _save(records, None)
        finally:
            await source.close()

    bench = await benchmark_concurrency()
    _save(records, bench)
    log("=== DONE ===")


def _save(records: list[CaseRecord], bench) -> None:
    payload = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": [vars(r) for r in records],
    }
    if bench is not None:
        payload["benchmark"] = bench
    (ROOT / "RESULTS.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
