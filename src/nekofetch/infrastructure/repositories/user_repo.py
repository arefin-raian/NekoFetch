"""User repository."""

from __future__ import annotations

from sqlalchemy import func, select

from nekofetch.domain.enums import Role
from nekofetch.infrastructure.database.postgres.models import User
from nekofetch.infrastructure.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, telegram_id: int, *, username: str | None, first_name: str | None
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            await self.add(user)
        return user

    async def set_role(self, telegram_id: int, role: Role) -> User | None:
        user = await self.get_by_telegram_id(telegram_id)
        if user is not None:
            user.role = role
        return user

    async def list_by_role(self, role: Role) -> list[User]:
        result = await self.session.execute(select(User).where(User.role == role))
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(User))
        return int(result.scalar_one())

    async def all_telegram_ids(self, *, include_banned: bool = False) -> list[int]:
        stmt = select(User.telegram_id)
        if not include_banned:
            stmt = stmt.where(User.is_banned.is_(False))
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
