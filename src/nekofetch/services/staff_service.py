"""Staff & user management.

Promote/demote staff, ban/unban, and approve users. Every privileged action writes an
``AuditLog`` row and emits a log-channel event. The env admin whitelist is always admin and
cannot be demoted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from nekofetch.core.container import Container
from nekofetch.core.exceptions import NotFound, PermissionDenied
from nekofetch.domain.enums import Role
from nekofetch.infrastructure.database.postgres.models import AuditLog
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.user_repo import UserRepository


@dataclass(slots=True)
class StaffMember:
    telegram_id: int
    name: str
    role: str
    banned: bool


class StaffService:
    def __init__(self, container: Container) -> None:
        self._c = container

    async def list_team(self) -> list[StaffMember]:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            members = await repo.list_by_role(Role.STAFF)
            members += await repo.list_by_role(Role.ADMIN)
            return [
                StaffMember(
                    telegram_id=u.telegram_id,
                    name=u.username or u.first_name or str(u.telegram_id),
                    role=self._effective_role(u.telegram_id, u.role),
                    banned=u.is_banned,
                )
                for u in members
            ]

    def _effective_role(self, telegram_id: int, stored: str) -> str:
        return Role.ADMIN.value if telegram_id in self._c.env.admin_ids else str(stored)

    async def add_staff(self, actor_id: int, telegram_id: int) -> None:
        await self._set_role(actor_id, telegram_id, Role.STAFF, "add_staff")

    async def remove_staff(self, actor_id: int, telegram_id: int) -> None:
        if telegram_id in self._c.env.admin_ids:
            raise PermissionDenied("Cannot demote a whitelisted admin.")
        await self._set_role(actor_id, telegram_id, Role.USER, "remove_staff")

    async def _set_role(self, actor_id: int, telegram_id: int, role: Role, action: str) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            user = await repo.get_or_create(telegram_id, username=None, first_name=None)
            user.role = role
            await self._audit(session, actor_id, action, str(telegram_id), {"role": role.value})
        await self._notify(action, actor=actor_id, target=telegram_id, role=role.value)

    async def set_banned(self, actor_id: int, telegram_id: int, banned: bool) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            if await repo.set_banned(telegram_id, banned) is None:
                raise NotFound(str(telegram_id))
            await self._audit(session, actor_id, "ban" if banned else "unban", str(telegram_id))
        await self._notify("ban" if banned else "unban", actor=actor_id, target=telegram_id)

    async def set_approved(self, actor_id: int, telegram_id: int, approved: bool) -> None:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            if await repo.set_approved(telegram_id, approved) is None:
                raise NotFound(str(telegram_id))
            await self._audit(session, actor_id, "approve" if approved else "unapprove",
                              str(telegram_id))
        await self._notify("approve" if approved else "unapprove", actor=actor_id, target=telegram_id)

    async def _audit(self, session, actor_id: int, action: str, target: str,
                     detail: dict | None = None) -> None:
        if not self._c.config.features.audit_logs:
            return
        session.add(
            AuditLog(
                ts=datetime.now(timezone.utc), actor_id=actor_id,
                action=action, target=target, detail=detail,
            )
        )

    async def _notify(self, action: str, **fields) -> None:
        from nekofetch.services.log_channel_service import LogChannelService

        await LogChannelService(self._c).event("admin", action, **fields)
