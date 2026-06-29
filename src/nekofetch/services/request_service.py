"""Request service — the public request workflow.

Creates requests with human-friendly codes (``REQ-1048``), reports queue position,
and lists a user's requests. Honors the ``request_system`` feature toggle.
"""

from __future__ import annotations

from dataclasses import dataclass

from nekofetch.core.constants import REQUEST_PREFIX
from nekofetch.core.container import Container
from nekofetch.core.exceptions import FeatureDisabled, NotFound
from nekofetch.domain.enums import AudioType, DownloadScope, RequestStatus
from nekofetch.infrastructure.database.postgres.models import Request
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.request_repo import RequestRepository
from nekofetch.infrastructure.repositories.user_repo import UserRepository


@dataclass(slots=True)
class RequestReceipt:
    code: str
    position: int
    status: str


class RequestService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def submit(
        self,
        *,
        telegram_id: int,
        source: str,
        source_ref: str,
        anime_title: str,
        scope: DownloadScope,
        season: int | None = None,
        episodes: list[int] | None = None,
        resolution: str | None = None,
        audio: AudioType | None = None,
        anime_doc_id: str | None = None,
        franchise_data: dict | None = None,
    ) -> RequestReceipt:
        if not self._c.config.features.request_system:
            raise FeatureDisabled("request_system")

        async with session_scope(self._c.pg_sessionmaker) as session:
            users = UserRepository(session)
            requests = RequestRepository(session)

            user = await users.get_by_telegram_id(telegram_id)
            if user is None:
                raise NotFound("user")

            seq = await requests.next_sequence()
            code = f"{REQUEST_PREFIX}-{seq}"
            req = Request(
                code=code,
                user_id=user.id,
                anime_doc_id=anime_doc_id,
                anime_title=anime_title,
                source=source,
                source_ref=source_ref,
                scope=scope.value,
                season=season,
                episodes=episodes,
                resolution=resolution,
                audio=audio,
                franchise_data=franchise_data,
                status=RequestStatus.PENDING,
            )
            await requests.add(req)
            await session.flush()
            position = await requests.pending_position(req.id)
            req.position = position
            receipt = RequestReceipt(code=code, position=position, status=req.status.value)

        from nekofetch.services.log_channel_service import LogChannelService

        logcc = LogChannelService(self._c)
        await logcc.event(
            "request", "submitted", code=code, anime=anime_title, user=telegram_id,
            scope=scope.value, season=season,
            source=source, episodes=episodes,
            franchise_seasons=franchise_data.get("franchise_seasons") if franchise_data else None,
            relations=len(franchise_data.get("relations", [])) if franchise_data else None,
        )
        # Operational control center: post an actionable request card so staff can
        # assign a source (Telegram / Website / Torrent) or reject — inline.
        await logcc.post_request_card(
            code=code, title=anime_title, by=str(telegram_id),
            scope=scope.value.replace("_", " ").title(),
        )
        return receipt

    async def list_pending(self, *, limit: int = 50) -> list[Request]:
        """Requests awaiting staff review (oldest first), detached for safe UI reads."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            rows = await RequestRepository(session).list_by_status(
                RequestStatus.PENDING, limit=limit
            )
            for r in rows:
                session.expunge(r)
            return rows

    async def update_source(self, code: str, new_source: str) -> Request:
        """Update the source plugin assigned to a request."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            req.source = new_source
            await session.flush()
            title = req.anime_title
            session.expunge(req)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "request", "source_assigned", code=code, anime=title, source=new_source
        )
        return req

    async def retry_episodes(
        self, code: str, episodes: list[int], *, new_source: str | None = None
    ) -> Request:
        """Re-queue a request for ONLY the given (previously stuck) episode numbers,
        optionally switching to a different source. The download worker filters by
        ``req.episodes``, so a fresh job re-attempts just those episodes without
        re-downloading the whole series."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            req.episodes = sorted(set(episodes)) or None
            if new_source:
                req.source = new_source
            req.status = RequestStatus.QUEUED
            await session.flush()
            title, source = req.anime_title, req.source
            session.expunge(req)
        from nekofetch.services.log_channel_service import LogChannelService
        await LogChannelService(self._c).event(
            "request", "retry", code=code, anime=title, source=source,
        )
        return req

    async def update_source_ref(self, code: str, source: str, source_ref: str) -> None:
        """Pin a request to a specific source + native ref (e.g. a chosen torrent)."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            req.source = source
            req.source_ref = source_ref

    async def reject(self, code: str) -> Request:
        """Mark a request rejected; logged to the log channel."""
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            req.status = RequestStatus.REJECTED
            await session.flush()
            title = req.anime_title
            session.expunge(req)

        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event(
            "request", "rejected", code=code, anime=title
        )
        return req

    async def list_for_user(self, telegram_id: int, *, limit: int = 20) -> list[Request]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            users = UserRepository(session)
            requests = RequestRepository(session)
            user = await users.get_by_telegram_id(telegram_id)
            if user is None:
                return []
            rows = await requests.list_for_user(user.id, limit=limit)
            for r in rows:
                session.expunge(r)
            return rows

    async def get(self, code: str) -> Request:
        async with session_scope(self._c.pg_sessionmaker) as session:
            req = await RequestRepository(session).get_by_code(code)
            if req is None:
                raise NotFound(code)
            session.expunge(req)
            return req
