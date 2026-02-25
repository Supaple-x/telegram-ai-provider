"""Add message_attachments table for multimodal context.

Revision ID: 004
Revises: 003
Create Date: 2026-02-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_type",
            sa.VARCHAR(20),
            nullable=False,
            server_default="image",
        ),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column(
            "media_type",
            sa.VARCHAR(50),
            nullable=False,
            server_default="image/jpeg",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_message_attachments_message_id",
        "message_attachments",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_message_attachments_message_id", table_name="message_attachments")
    op.drop_table("message_attachments")
