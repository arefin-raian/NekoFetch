"""Section artwork — random selection with no back-to-back repeats.

Every major UI surface shows a 16:9 image. We rotate through the pool in
``images/`` randomly, but never return the same artwork twice in a row, so a
message that re-renders (e.g. an edit) doesn't keep showing the same picture.
"""

from __future__ import annotations

import random
from pathlib import Path

# repo-root/images  (this file is src/nekofetch/ui/artwork.py)
ART_DIR = Path(__file__).resolve().parents[3] / "images"


class ArtworkPicker:
    """Picks a random artwork, avoiding an immediate repeat of the last pick."""

    def __init__(self, directory: Path = ART_DIR) -> None:
        self.directory = directory
        self._last: Path | None = None

    def available(self) -> list[Path]:
        imgs = sorted(self.directory.glob("art_*.jpg"))
        return imgs or sorted(self.directory.glob("*.jpg"))

    def pick(self) -> Path | None:
        imgs = self.available()
        if not imgs:
            return None
        if len(imgs) == 1:
            self._last = imgs[0]
            return imgs[0]
        choices = [p for p in imgs if p != self._last]
        choice = random.choice(choices)
        self._last = choice
        return choice


# Module-level default so callers share the same no-repeat history.
_default = ArtworkPicker()


def pick_artwork() -> Path | None:
    """Return the path to a random section artwork (never the same one twice
    consecutively), or ``None`` if the image pool is empty."""
    return _default.pick()
