"""Initial schema — market_prices, card_metadata, user_profiles

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID

# revision identifiers
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- market_prices (Section 14, Layer A) ---
    op.create_table(
        "market_prices",
        sa.Column("card_id", sa.String(), nullable=False, comment="pokemontcg.io canonical ID"),
        sa.Column("source", sa.String(), nullable=False, comment="Data source: justtcg, pokemontcg, poketrace"),
        sa.Column("price_usd", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("price_eur", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("condition", sa.String(), nullable=True),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("card_id", "source"),
    )
    op.create_index("ix_market_prices_card_source", "market_prices", ["card_id", "source"])

    # --- card_metadata ---
    op.create_table(
        "card_metadata",
        sa.Column("card_id", sa.String(), nullable=False, primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("set_code", sa.String(), nullable=False),
        sa.Column("set_name", sa.String(), nullable=False),
        sa.Column("card_number", sa.String(), nullable=False),
        sa.Column("regulation_mark", sa.String(), nullable=True),
        sa.Column("set_release_date", sa.DATE(), nullable=True),
        sa.Column("legality_standard", sa.String(), nullable=True),
        sa.Column("legality_expanded", sa.String(), nullable=True),
        sa.Column("tcgplayer_url", sa.String(), nullable=True),
        sa.Column("cardmarket_url", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # --- user_profiles (Section 8) ---
    op.create_table(
        "user_profiles",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("telegram_chat_id", sa.BIGINT(), unique=True, nullable=True),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("seller_level", sa.String(), nullable=True),
        sa.Column("preferred_platforms", ARRAY(sa.String()), nullable=True),
        sa.Column("min_profit_threshold", sa.DECIMAL(10, 2), server_default="5.00"),
        sa.Column("min_headache_score", sa.INTEGER(), server_default="5"),
        sa.Column("card_categories", ARRAY(sa.String()), nullable=True),
        sa.Column("currency", sa.String(), server_default="USD"),
        sa.Column("import_duty_rate", sa.DECIMAL(5, 4), nullable=True),
        sa.Column("forwarder_receiving_fee", sa.DECIMAL(10, 2), server_default="3.50"),
        sa.Column("forwarder_consolidation_fee", sa.DECIMAL(10, 2), server_default="7.50"),
        sa.Column("insurance_rate", sa.DECIMAL(5, 4), server_default="0.025"),
        sa.Column("use_forwarder", sa.BOOLEAN(), server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_table("card_metadata")
    op.drop_index("ix_market_prices_card_source", table_name="market_prices")
    op.drop_table("market_prices")
