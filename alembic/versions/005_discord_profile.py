"""Add discord_channel_id to user_profiles

Revision ID: 005_discord_profile
Revises: 004_synergy_schema
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "005_discord_profile"
down_revision: Union[str, None] = "004_synergy_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("discord_channel_id", sa.BIGINT(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "discord_channel_id")
