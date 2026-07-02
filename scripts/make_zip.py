"""Create nekofetch.zip — all tracked files + .env, excluding cache/temp junk."""
import os
import pathlib
import subprocess
import zipfile

REPO = pathlib.Path(__file__).resolve().parent.parent
os.chdir(REPO)

# ── Exclusion patterns (directories and file names) ──────────────────────
EXCLUDE_DIRS = {
    "tools",            # 296 MB ffmpeg binaries
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".venv",
    "venv",
    ".git",
    ".claude",
    "sessions",
    ".idea",
    ".vscode",
    "playground/downloads",
    "playground/test_results",
    "playground/full_test",
    "playground/nyaa_test",
}

EXCLUDE_SUFFIXES = {
    ".pyc", ".pyo", ".session", ".session-journal",
    ".DS_Store", "Thumbs.db",
}

def should_exclude(path: pathlib.Path) -> bool:
    """Return True if *path* should be skipped.

    *path* is relative to the repo root (from ``git ls-files`` or manual).
    """
    name = path.name
    # File suffixes
    if any(name.endswith(s) for s in EXCLUDE_SUFFIXES):
        return True
    # Any parent directory in the exclude list
    # path.parts for a relative path: e.g. ("playground", "downloads", "file.py")
    for part in path.parts[:-1]:  # skip the filename itself
        if part in EXCLUDE_DIRS:
            return True
    return False

def main():
    # ── Gather all tracked files (working-tree state) ───────────────────
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=REPO,
    )
    tracked = {pathlib.Path(p) for p in result.stdout.strip().split("\n") if p}

    # ── Add critical untracked files ────────────────────────────────────
    extra = {
        pathlib.Path(".env"),
        # Any other important untracked files
    }

    all_paths: set[pathlib.Path] = tracked | extra

    # ── Write zip ──────────────────────────────────────────────────────
    zip_path = REPO / "nekofetch.zip"
    count = skipped = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(all_paths):
            if should_exclude(p):
                skipped += 1
                continue
            if not p.exists():
                skipped += 1
                continue
            zf.write(p)
            count += 1

    size_mb = zip_path.stat().st_size / 1_048_576
    print(f"✅ {zip_path.name} created: {count} files included, {skipped} skipped")
    print(f"   Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
