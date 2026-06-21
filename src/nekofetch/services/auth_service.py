"""Authentication & authorization service.

Resolves the acting user, determines their effective role (the ``.env`` admin
whitelist always wins), and answers permission checks used by the bot middleware.
"""

from __future__ import annotations

from nekofetch.core.config import EnvSettings
from nekofetch.core.container import Container
from nekofetch.core.exceptions import PermissionDenied
from nekofetch.domain.enums import ROLE_PERMISSIONS, Permission, Role
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.database.postgres.models import User
from nekofetch.infrastructure.repositories.user_repo import UserRepository


class AuthService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self._env: EnvSettings = container.env

    async def resolve_user(
        self, telegram_id: int, *, username: str | None = None, first_name: str | None = None
    ) -> User:
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            user = await repo.get_or_create(
                telegram_id, username=username, first_name=first_name
            )
            # Admin whitelist from env is authoritative.
            if telegram_id in self._env.admin_ids and user.role != Role.ADMIN:
                user.role = Role.ADMIN
            await session.flush()
            session.expunge(user)
            return user

    def role_of(self, user: User) -> Role:
        if user.telegram_id in self._env.admin_ids:
            return Role.ADMIN
        return Role(user.role)

    def has_permission(self, user: User, permission: Permission) -> bool:
        if user.is_banned:
            return False
        return permission in ROLE_PERMISSIONS.get(self.role_of(user), set())

    def require(self, user: User, permission: Permission) -> None:
        if not self.has_permission(user, permission):
            raise PermissionDenied(f"{self.role_of(user)} lacks {permission}")
