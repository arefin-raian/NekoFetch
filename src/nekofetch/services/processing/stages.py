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


class VerifyStage(Stage):
    stage = ProcessingStage.VERIFY

    def enabled(self) -> bool:
        return self.c.config.processing.verify_files

    async def process(self, ctx: StageContext) -> None:
        for f in ctx.files:
            path = Path(f.local_path) if f.local_path else None
            ok = bool(path and path.exists() and path.stat().st_size > 0)
            if ok and f.size_bytes:
                ok = path.stat().st_size == f.size_bytes
            f.verified = ok
            if not ok:
                ctx.notes.append(f"verify failed: {f.local_path}")


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


class BrandingStage(Stage):
    stage = ProcessingStage.BRANDING

    def enabled(self) -> bool:
        return self.c.config.processing.branding and self.c.config.branding.enabled

    async def process(self, ctx: StageContext) -> None:
        # Branding here is metadata/caption-level (see BrandingService). Optional video
        # watermarking is gated separately by watermark.enabled and applied in a full build.
        if self.c.config.watermark.enabled:
            ctx.notes.append("watermark: enabled (applied during transcode in full build)")


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
        ThumbnailStage(container),
        StoreStage(container),
    ]
