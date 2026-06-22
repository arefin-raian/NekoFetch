"""Request repository."""

from __future__ import annotations

from sqlalchemy import func, select

from nekofetch.domain.enums import RequestStatus
from nekofetch.infrastructure.database.postgres.models import Request
from nekofetch.infrastructure.repositories.base import BaseRepository


class RequestRepository(BaseRepository[Request]):
    model = Request

    async def get_by_code(self, code: str) -> Request | None:
        result = await self.session.execute(select(Request).where(Request.code == code))
        return result.scalar_one_or_none()

    async def list_by_status(
        self, status: RequestStatus, *, limit: int = 50
    ) -> list[Request]:
        """Oldest-first requests in a given status (drives the review queue)."""
        result = await self.session.execute(
            select(Request)
            .where(Request.status == status)
            .order_by(Request.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: int, *, limit: int = 20) -> list[Request]:
        result = await self.session.execute(
            select(Request)
            .where(Request.user_id == user_id)
            .order_by(Request.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def next_sequence(self) -> int:
        """Monotonic counter for human-friendly request codes (REQ-1048)."""
        result = await self.session.execute(select(func.count()).select_from(Request))
        return int(result.scalar_one()) + 1049  # start the visible series near 1048

    async def pending_position(self, request_id: int) -> int:
        """1-based position of a request among those awaiting download."""
        active = {RequestStatus.PENDING, RequestStatus.APPROVED, RequestStatus.QUEUED}
        result = await self.session.execute(
            select(Request.id)
            .where(Request.status.in_(active))
            .order_by(Request.created_at.asc())
        )
        ids = [row[0] for row in result.all()]
        return ids.index(request_id) + 1 if request_id in ids else 0
