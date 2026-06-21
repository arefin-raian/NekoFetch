"""Linkvertise shortlink adapter.

Builds a Linkvertise *dynamic link* that redirects to the target URL after the user
completes it. Requires your Linkvertise publisher id (``shortlink.linkvertise_user_id``).

The dynamic-link scheme encodes the destination as base64 in the ``r`` query parameter:

    https://link-to.net/<user_id>/<n>/dynamic?r=<base64(target)>

If no user id is configured, this falls back to returning the target unchanged so the flow
still works during setup.
"""

from __future__ import annotations

import base64

from nekofetch.core.logging import get_logger
from nekofetch.providers.shortlink.base import ShortlinkProvider

log = get_logger(__name__)


class LinkvertiseProvider(ShortlinkProvider):
    name = "linkvertise"

    def __init__(self, user_id: str = "") -> None:
        self.user_id = user_id

    async def create_short_link(self, target_url: str) -> str:
        if not self.user_id:
            log.warning("shortlink.linkvertise.no_user_id")
            return target_url
        encoded = base64.b64encode(target_url.encode("utf-8")).decode("ascii")
        # The middle segment is an arbitrary number; keep it stable per target length.
        n = (len(target_url) % 900) + 100
        return f"https://link-to.net/{self.user_id}/{n}/dynamic?r={encoded}"
