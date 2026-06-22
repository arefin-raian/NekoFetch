"""SQLAlchemy declarative base and common column mixins."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TypeVar

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

_E = TypeVar("_E", bound=Enum)


class EnumStr(TypeDecorator):
    """Persist a (Str)Enum as ``VARCHAR`` but always load it back as the enum.

    The columns were declared ``Mapped[SomeEnum]`` over a plain ``String`` column, so
    SQLAlchemy stored the value fine but handed it back as a bare ``str`` — making
    attribute access like ``row.audio.value`` blow up with ``'str' object has no
    attribute 'value'`` after a round-trip through the database.

    This keeps the exact same DDL (still ``VARCHAR(n)``, so **no migration**) while
    coercing values to the enum on read and to their string on write. Works whether the
    in-memory value is already the enum or a plain string.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[_E], length: int = 16, **kw: object) -> None:
        self._enum_cls = enum_cls
        super().__init__(length=length, **kw)

    def process_bind_param(self, value: object, dialect: object) -> str | None:
        if value is None:
            return None
        return value.value if isinstance(value, Enum) else str(value)

    def process_result_value(self, value: object, dialect: object) -> object:
        if value is None:
            return None
        return self._enum_cls(value)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PKMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
