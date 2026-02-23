"""Add synergy_cooccurrence table

Revision ID: 004_synergy_schema
Revises: 003_phase2_schema
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "004_synergy_schema"
down_revision: Union[str, None] = "003_phase2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- synergy_cooccurrence table ---
    op.create_table(
        "synergy_cooccurrence",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("card_a", sa.String(), nullable=False),
        sa.Column("card_b", sa.String(), nullable=False),
        sa.Column("count", sa.INTEGER(), nullable=False, server_default="0"),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("card_a", "card_b", name="uq_synergy_card_pair"),
    )
    op.create_index("ix_synergy_card_a", "synergy_cooccurrence", ["card_a"])
    op.create_index("ix_synergy_card_b", "synergy_cooccurrence", ["card_b"])


def downgrade() -> None:
    op.drop_index("ix_synergy_card_b", table_name="synergy_cooccurrence")
    op.drop_index("ix_synergy_card_a", table_name="synergy_cooccurrence")
    op.drop_table("synergy_cooccurrence")
