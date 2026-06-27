"""add franchise_data column to requests

Adds the JSONB ``franchise_data`` column that stores the Phase 1 AniList
relation graph and franchise breakdown for a request.

Revision ID: 0002_add_franchise_data
Revises: 0001_initial
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_franchise_data"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column("franchise_data", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requests", "franchise_data")
