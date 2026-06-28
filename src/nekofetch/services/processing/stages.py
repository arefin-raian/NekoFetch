"""Concrete processing stages.

External media tooling (ffmpeg / mkvpropedit) is invoked via subprocess and guarded by
feature toggles, so the pipeline runs even where a tool or capability is unavailable —
it simply records a note and moves on rather than failing the whole job.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from nekofetch.core.logging import get_logger
from nekofetch.domain.enums import ProcessingStage
from nekofetch.services.branding_service import BrandingService
from nekofetch.services.processing.base import Stage, StageContext
from nekofetch.ui import templates

log = get_logger(__name__)


async def _run(*args: str) -> tuple[int, str]:
    """Run a subprocess; return (rc, stderr). rc=-1 if the binary is missing."""
    if shutil.which(args[0]) is None:
        return -1, f"{args[0]} not found"
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await proc.communicate()
    return proc.returncode or 0, err.decode(errors="ignore")


async def _ffprobe_ok(ffprobe: str, path: Path) -> tuple[bool, str]:
    """Decode-probe a media file. A non-corrupt file parses cleanly, has at least
    one video stream, and a positive duration. Returns (ok, reason)."""
    import json

    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-of", "json",
            "-show_format", "-show_streams", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120)
    except Exception as exc:  # noqa: BLE001
        return False, f"probe error: {exc}"
    if proc.returncode != 0:
        return False, (err.decode(errors="ignore").strip()[:120] or "ffprobe error")
    try:
        data = json.loads(out or b"{}")
    except ValueError:
        return False, "unparseable ffprobe output"
    streams = data.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        return False, "no video stream"
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return False, "zero/unknown duration"
    return True, "ok"


class VerifyStage(Stage):
    stage = ProcessingStage.VERIFY

    def enabled(self) -> bool:
        return self.c.config.processing.verify_files

    async def process(self, ctx: StageContext) -> None:
        from nekofetch.core.exceptions import ProcessingError
        from nekofetch.sources._hls import find_ffprobe

        ffprobe = find_ffprobe()
        corrupt: list[str] = []
        for f in ctx.files:
            path = Path(f.local_path) if f.local_path else None
            if not (path and path.exists() and path.stat().st_size > 0):
                f.verified = False
                corrupt.append(f"{Path(f.local_path).name if f.local_path else '?'}: missing/empty")
                continue
            if ffprobe:
                ok, reason = await _ffprobe_ok(ffprobe, path)
            else:  # no ffprobe — fall back to a size-only check, can't prove corrupt
                ok, reason = True, "ffprobe unavailable (size-only check)"
                ctx.notes.append("verify: ffprobe unavailable, size-only check")
            f.verified = ok
            if not ok:
                corrupt.append(f"{path.name}: {reason}")
        # Corrupt files must never reach the database channel — fail the whole job
        # so it's surfaced and can be retried, rather than silently shipping garbage.
        if corrupt:
            raise ProcessingError("corrupt file(s): " + "; ".join(corrupt[:5]))


class RenameStage(Stage):
    stage = ProcessingStage.RENAME

    def enabled(self) -> bool:
        return self.c.config.rename.enabled

    async def process(self, ctx: StageContext) -> None:
        branding = BrandingService(self.c)
        tmpl = self.c.config.rename.template
        for f in ctx.files:
            new_name = templates.render_filename(
                tmpl,
                title=ctx.request.anime_title,
                season=f"{f.season or 1:02d}",
                episode=f"{f.episode or 0:03d}",
                resolution=f.resolution or "",
                audio=(f.audio.value if f.audio else ""),
                source=ctx.request.source,
                group=branding.group,
            )
            ext = Path(f.local_path).suffix if f.local_path else f".{f.container or 'mkv'}"
            f.final_name = f"{new_name}{ext}"
            if f.local_path:
                dest = Path(f.local_path).with_name(f.final_name)
                try:
                    Path(f.local_path).rename(dest)
                    f.local_path = str(dest)
                except OSError as exc:
                    ctx.notes.append(f"rename skipped: {exc}")


class MetadataStage(Stage):
    stage = ProcessingStage.METADATA

    def enabled(self) -> bool:
        return self.c.config.features.metadata_editing and self.c.config.metadata.enabled

    async def process(self, ctx: StageContext) -> None:
        meta = self.c.config.metadata
        branding = BrandingService(self.c).metadata_fields()
        for f in ctx.files:
            if not f.local_path:
                continue
            container = (f.container or "").lower()
            if container not in meta.supported_containers:
                ctx.notes.append(f"metadata: unsupported container {container}")
                continue
            tags: list[str] = []
            if meta.update_title:
                tags += ["--edit", "info", "--set", f"title={ctx.request.anime_title}"]
            # mkvpropedit handles MKV titles; ffmpeg covers other containers in a full build.
            if container == "mkv" and tags:
                rc, err = await _run("mkvpropedit", f.local_path, *tags)
                if rc != 0:
                    ctx.notes.append(f"metadata: {err.strip() or 'mkvpropedit unavailable'}")
            if branding:
                ctx.notes.append(f"metadata branding: {', '.join(branding)}")


_CORNER_OVERLAY = {
    "top_left": "10:10",
    "top_right": "main_w-overlay_w-10:10",
    "bottom_left": "10:main_h-overlay_h-10",
    "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10",
}
_CORNER_TEXT = {
    "top_left": "x=10:y=10",
    "top_right": "x=w-tw-10:y=10",
    "bottom_left": "x=10:y=h-th-10",
    "bottom_right": "x=w-tw-10:y=h-th-10",
}


class BrandingStage(Stage):
    stage = ProcessingStage.BRANDING

    def enabled(self) -> bool:
        return self.c.config.processing.branding and self.c.config.branding.enabled

    async def process(self, ctx: StageContext) -> None:
        # Branding here is metadata/caption-level (see BrandingService). Video watermarking
        # is a separate, opt-in stage below.
        return None


class WatermarkStage(Stage):
    """Optional video watermark overlay (text or image) via ffmpeg.

    Opt-in (``watermark.enabled``) and re-encodes video, so it is off by default. Honors
    corner, opacity, and scale. Falls back to a note (not a failure) when ffmpeg is missing.
    """

    stage = ProcessingStage.BRANDING

    def enabled(self) -> bool:
        return self.c.config.watermark.enabled

    def _filter(self, w) -> tuple[str, list[str]]:
        """Build the ffmpeg filter and any extra input args for the configured watermark."""
        if w.type == "image" and w.image_path:
            pos = _CORNER_OVERLAY.get(w.corner, _CORNER_OVERLAY["bottom_right"])
            # scale watermark to a fraction of video width, apply opacity, overlay
            flt = (
                f"[1:v]format=rgba,colorchannelmixer=aa={w.opacity},"
                f"scale=iw*{w.scale}:-1[wm];[0:v][wm]overlay={pos}"
            )
            return flt, ["-i", w.image_path]
        # text watermark
        pos = _CORNER_TEXT.get(w.corner, _CORNER_TEXT["bottom_right"])
        text = (w.text or "").replace(":", r"\:").replace("'", r"\'")
        fontsize = "h*" + str(max(w.scale, 0.03))
        flt = (
            f"drawtext=text='{text}':fontcolor=white@{w.opacity}:"
            f"fontsize={fontsize}:{pos}:box=1:boxcolor=black@0.3:boxborderw=6"
        )
        return flt, []

    async def process(self, ctx: StageContext) -> None:
        w = self.c.config.watermark
        for f in ctx.files:
            if not f.local_path:
                continue
            src = Path(f.local_path)
            out = src.with_name(src.stem + ".wm" + src.suffix)
            flt, extra_inputs = self._filter(w)
            args = ["ffmpeg", "-y", "-i", str(src), *extra_inputs,
                    "-filter_complex" if extra_inputs else "-vf", flt,
                    "-c:a", "copy", str(out)]
            rc, err = await _run(*args)
            if rc != 0:
                ctx.notes.append(f"watermark: {err.strip() or 'ffmpeg unavailable'}")
                continue
            try:
                out.replace(src)  # swap in the watermarked file
            except OSError as exc:
                ctx.notes.append(f"watermark swap failed: {exc}")


class ThumbnailStage(Stage):
    stage = ProcessingStage.THUMBNAIL

    def enabled(self) -> bool:
        return self.c.config.features.thumbnail_generation and self.c.config.thumbnail.enabled

    async def process(self, ctx: StageContext) -> None:
        for f in ctx.files:
            if not f.local_path or not self.c.config.thumbnail.generate_previews:
                continue
            thumb = Path(f.local_path).with_suffix(".thumb.jpg")
            rc, err = await _run(
                "ffmpeg", "-y", "-i", f.local_path, "-ss", "00:00:30", "-vframes", "1",
                "-vf", "scale=320:-1", str(thumb),
            )
            if rc != 0:
                ctx.notes.append(f"thumbnail: {err.strip() or 'ffmpeg unavailable'}")


class StoreStage(Stage):
    stage = ProcessingStage.STORE

    def enabled(self) -> bool:
        return True

    async def process(self, ctx: StageContext) -> None:
        for f in ctx.files:
            f.processed = True


def default_stages(container) -> list[Stage]:
    return [
        VerifyStage(container),
        RenameStage(container),
        MetadataStage(container),
        BrandingStage(container),
        WatermarkStage(container),
        ThumbnailStage(container),
        StoreStage(container),
    ]
