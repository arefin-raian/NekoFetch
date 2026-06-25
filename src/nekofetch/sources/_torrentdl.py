"""Fast torrent download via aria2c (multi-connection BitTorrent + DHT).

aria2c is the fastest practical option without compiling libtorrent: a single
static binary that does parallel piece fetching across many peers, DHT, and
selective single-file downloads (so a test can grab just EP1 from a batch).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import httpx

from nekofetch.core.logging import get_logger
from nekofetch.sources.base import ProgressCallback

log = get_logger(__name__)

# Well-seeded public trackers added on top of the torrent's own — improves peer
# discovery and start-up speed for popular releases.
_EXTRA_TRACKERS = ",".join([
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "http://nyaa.tracker.wf:7777/announce",
])

_PROGRESS_RE = re.compile(r"\((\d+)%\)")


def find_aria2() -> str | None:
    found = shutil.which("aria2c") or shutil.which("aria2c.exe")
    if found:
        return found
    for base in (Path(__file__).resolve().parents[3], Path.cwd()):
        for name in ("aria2c.exe", "aria2c"):
            cand = base / "tools" / name
            if cand.exists():
                return str(cand)
    return None


async def download_torrent_file(
    info: dict,
    dest: Path,
    *,
    on_progress: ProgressCallback | None = None,
    max_seconds: int = 1800,
    stop_idle: int = 180,
) -> dict:
    """Download a single file from a torrent, preserving its original name.

    ``info`` carries ``torrent_url``, ``file_index`` (1-based, bencode order),
    ``path`` and ``name``. Returns the downloaded file path + stats. Raises on
    failure so callers can react.
    """
    aria2 = find_aria2()
    if not aria2:
        raise RuntimeError("aria2c not found (expected on PATH or in tools/)")

    work = dest.parent
    work.mkdir(parents=True, exist_ok=True)

    # Fetch the .torrent (small) ourselves so aria2 starts immediately.
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"}) as c:
        tr = await c.get(info["torrent_url"])
        tr.raise_for_status()
    torrent_path = work / ".release.torrent"
    torrent_path.write_bytes(tr.content)

    # Flatten the selected file to <dir>/<name>, dropping the (often very long)
    # release folder — avoids Windows MAX_PATH (260) failures on batch releases
    # while still preserving the original filename.
    out_name = info["name"]
    cmd = [
        aria2,
        "--dir", str(work),
        "--select-file", str(info["file_index"]),
        f"--index-out={info['file_index']}={out_name}",
        "--seed-time=0",                       # stop seeding the moment it's done
        f"--bt-stop-timeout={stop_idle}",      # give up if no progress for a while
        "--max-connection-per-server=16",
        "--split=16",
        "--bt-max-peers=200",
        "--bt-request-peer-speed-limit=100M",
        "--enable-dht=true",
        "--dht-listen-port=6881-6999",
        "--listen-port=6881-6999",
        f"--bt-tracker={_EXTRA_TRACKERS}",
        "--summary-interval=2",
        "--console-log-level=warn",
        "--bt-save-metadata=false",
        "--allow-overwrite=true",
        str(torrent_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )

    last_pct = -1

    async def pump() -> None:
        nonlocal last_pct
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace")
            m = _PROGRESS_RE.search(line)
            if m and on_progress:
                pct = int(m.group(1))
                if pct != last_pct:
                    last_pct = pct
                    await on_progress(pct, 100)

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=max_seconds)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"torrent download timed out after {max_seconds}s") from None

    if proc.returncode != 0:
        raise RuntimeError(f"aria2c exited {proc.returncode}")

    # With --index-out the file lands flat at work/<name>.
    out = work / out_name
    if not out.exists():
        matches = list(work.rglob(info["name"]))
        if not matches:
            raise RuntimeError(f"downloaded file not found: {info['name']}")
        out = matches[0]

    torrent_path.unlink(missing_ok=True)
    aria_ctrl = out.with_name(out.name + ".aria2")
    aria_ctrl.unlink(missing_ok=True)

    size = out.stat().st_size
    if on_progress:
        await on_progress(100, 100)
    import hashlib
    sha = hashlib.sha256()
    sha.update(out.read_bytes())
    return {
        "path": str(out),
        "name": out.name,
        "bytes": size,
        "checksum": sha.hexdigest(),
        "complete": True,
    }
