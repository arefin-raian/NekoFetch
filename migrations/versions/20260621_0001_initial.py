"""initial schema

Baseline migration. Because the ORM models are the single source of truth and this is the
first revision, it materializes the entire current schema from ``Base.metadata`` rather than
duplicating every table's DDL by hand. Subsequent revisions should be generated with
``alembic revision --autogenerate`` and contain explicit diffs.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-21
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from nekofetch.infrastructure.database.postgres.base import Base

# Ensure all tables are registered on the metadata.
from nekofetch.infrastructure.database.postgres import models  # noqa: F401

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
