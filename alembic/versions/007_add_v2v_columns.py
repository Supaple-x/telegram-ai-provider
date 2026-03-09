"""Add model and source_video_url columns to video_generations for v2v support.

Revision ID: 007
Revises: 006
Create Date: 2026-03-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "video_generations",
        sa.Column("model", sa.VARCHAR(30), nullable=False, server_default="seedance"),
    )
    op.add_column(
        "video_generations",
        sa.Column("source_video_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("video_generations", "source_video_url")
    op.drop_column("video_generations", "model")
