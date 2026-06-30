"""add bot_content_posts table

Adds the ``bot_content_posts`` table that stores pre-generated content
posts (watch guide, info card, season cards, footer) for each distribution
bot. Posts are delivered in order when a user starts the bot.

Revision ID: 0003_add_bot_content_posts
Revises: 0002_add_franchise_data
Create Date: 2026-07-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_add_bot_content_posts"
down_revision: str | None = "0002_add_franchise_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_content_posts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("post_type", sa.String(32), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("button_data", postgresql.JSONB(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["bot_id"], ["bots.id"],
            name=op.f("fk_bot_content_posts_bot_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_content_posts")),
    )
    op.create_index(
        op.f("ix_bot_content_posts_bot_id"),
        "bot_content_posts", ["bot_id"],
    )
    op.create_index(
        op.f("ix_bot_content_posts_order"),
        "bot_content_posts", ["bot_id", "order"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bot_content_posts_order"), table_name="bot_content_posts")
    op.drop_index(op.f("ix_bot_content_posts_bot_id"), table_name="bot_content_posts")
    op.drop_table("bot_content_posts")
