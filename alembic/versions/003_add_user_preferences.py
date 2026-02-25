"""Add user_preferences table for model switching.

Revision ID: 003
Revises: 002
Create Date: 2026-02-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "preferred_model",
            sa.VARCHAR(50),
            nullable=False,
            server_default="claude",
        ),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
