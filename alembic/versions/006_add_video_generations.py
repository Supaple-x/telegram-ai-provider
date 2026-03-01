"""Add video_generations table for Seedance video generation history.

Revision ID: 006
Revises: 005
Create Date: 2026-03-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "video_generations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "mode",
            sa.VARCHAR(20),
            nullable=False,
            server_default="text-to-video",
        ),
        sa.Column(
            "duration",
            sa.VARCHAR(5),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "resolution",
            sa.VARCHAR(10),
            nullable=False,
            server_default="720p",
        ),
        sa.Column(
            "aspect_ratio",
            sa.VARCHAR(10),
            nullable=False,
            server_default="16:9",
        ),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_video_generations_user_id",
        "video_generations",
        ["user_id"],
    )
    op.create_index(
        "idx_video_generations_created_at",
        "video_generations",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_video_generations_created_at", table_name="video_generations")
    op.drop_index("idx_video_generations_user_id", table_name="video_generations")
    op.drop_table("video_generations")
