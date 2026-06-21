"""Time-based access service.

Model: every user gets a free trial on first contact; when it lapses they must complete a
shortlink to receive a **renewal token**, which grants another window. Delivery is gated on
``has_access``. All durations are configurable (``access.*``).

Flow:
    first /start         -> grant trial_days
    access lapses        -> user taps "Get Access" -> generate_token() -> shortlink URL
    user completes link  -> lands on /start token_<token> -> redeem() -> +token_days
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from nekofetch.core.container import Container
from nekofetch.core.exceptions import LinkExpired, NotFound
from nekofetch.core.logging import get_logger
from nekofetch.infrastructure.database.postgres.models import AccessToken
from nekofetch.infrastructure.database.postgres.session import session_scope
from nekofetch.infrastructure.repositories.user_repo import UserRepository

log = get_logger(__name__)


@dataclass(slots=True)
class AccessStatus:
    has_access: bool
    until: datetime | None
    is_trial: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccessService:
    def __init__(self, container: Container) -> None:
        self._c = container
        self.cfg = container.config.access

    async def ensure_and_check(self, telegram_id: int, *, username: str | None = None,
                               first_name: str | None = None) -> AccessStatus:
        """Grant the trial on first contact, then report current access."""
        if not self.cfg.enabled:
            return AccessStatus(True, None, False)
        async with session_scope(self._c.pg_sessionmaker) as session:
            repo = UserRepository(session)
            user = await repo.get_or_create(telegram_id, username=username, first_name=first_name)
            is_trial = False
            if user.access_until is None and self.cfg.free_trial:
                user.access_until = _now() + timedelta(days=self.cfg.trial_days)
                is_trial = True
            until = user.access_until
        has = until is not None and until > _now()
        return AccessStatus(has, until, is_trial)

    async def has_access(self, telegram_id: int) -> bool:
        if not self.cfg.enabled:
            return True
        async with session_scope(self._c.pg_sessionmaker) as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            until = user.access_until if user else None
        return until is not None and until > _now()

    async def generate_token(self, telegram_id: int, *, bot_username: str) -> str:
        """Create a renewal token and return the (shortened) URL the user must visit."""
        token = secrets.token_urlsafe(12)
        expires = _now() + timedelta(hours=self.cfg.token_link_ttl_hours)
        async with session_scope(self._c.pg_sessionmaker) as session:
            session.add(
                AccessToken(
                    token=token, telegram_id=telegram_id,
                    days=self.cfg.token_days, expires_at=expires,
                )
            )
        target = f"https://t.me/{bot_username}?start=token_{token}"
        short = await self._c.shortlink_provider.create_short_link(target)
        log.info("access.token.generated", user=telegram_id)
        return short

    async def redeem(self, token: str, telegram_id: int) -> datetime:
        """Redeem a token: extend the user's access by ``token_days``. Returns new expiry."""
        from sqlalchemy import select

        async with session_scope(self._c.pg_sessionmaker) as session:
            row = (
                await session.execute(select(AccessToken).where(AccessToken.token == token))
            ).scalar_one_or_none()
            if row is None or row.used:
                raise NotFound("token")
            if row.expires_at is not None and row.expires_at < _now():
                raise LinkExpired(token)
            if row.telegram_id != telegram_id:
                raise NotFound("token")  # token belongs to another user

            repo = UserRepository(session)
            user = await repo.get_or_create(telegram_id, username=None, first_name=None)
            base = user.access_until if (user.access_until and user.access_until > _now()) else _now()
            user.access_until = base + timedelta(days=row.days)
            row.used = True
            new_until = user.access_until
        log.info("access.token.redeemed", user=telegram_id, until=new_until.isoformat())
        return new_until
