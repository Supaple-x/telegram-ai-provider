"""Add composite index on messages(user_id, created_at DESC).

Replaces the single-column idx_messages_user_id which cannot serve
ORDER BY created_at DESC efficiently. The composite index covers both
the WHERE user_id = $1 filter and the DESC sort in get_context().

Revision ID: 005
Revises: 004
Create Date: 2026-02-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_messages_user_created",
        "messages",
        ["user_id", sa.text("created_at DESC")],
    )
    # Old single-column index is now redundant (composite covers user_id lookups)
    op.drop_index("idx_messages_user_id", table_name="messages")


def downgrade() -> None:
    op.create_index("idx_messages_user_id", "messages", ["user_id"])
    op.drop_index("idx_messages_user_created", table_name="messages")
