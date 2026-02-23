"""Add price_history table and extend market_prices with seller/velocity columns

Revision ID: 003_phase2_schema
Revises: 002_signals_schema
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "003_phase2_schema"
down_revision: Union[str, None] = "002_signals_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- price_history table (append-only, never upserted) ---
    op.create_table(
        "price_history",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("card_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("price_usd", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("price_eur", sa.DECIMAL(10, 2), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_price_history_card_source_recorded",
        "price_history",
        ["card_id", "source", "recorded_at"],
    )

    # --- Extend market_prices with seller and velocity columns ---
    op.add_column(
        "market_prices",
        sa.Column(
            "seller_id",
            sa.String(),
            nullable=True,
            comment="Seller identifier from scraper",
        ),
    )
    op.add_column(
        "market_prices",
        sa.Column(
            "seller_rating",
            sa.DECIMAL(5, 2),
            nullable=True,
            comment="Seller rating percentage",
        ),
    )
    op.add_column(
        "market_prices",
        sa.Column(
            "seller_sales",
            sa.INTEGER(),
            nullable=True,
            comment="Seller total sales count",
        ),
    )
    op.add_column(
        "market_prices",
        sa.Column(
            "sales_30d",
            sa.INTEGER(),
            nullable=True,
            comment="Sales in last 30 days (PokeTrace)",
        ),
    )
    op.add_column(
        "market_prices",
        sa.Column(
            "active_listings",
            sa.INTEGER(),
            nullable=True,
            comment="Active listing count (PokeTrace)",
        ),
    )


def downgrade() -> None:
    # Remove columns from market_prices in reverse order
    op.drop_column("market_prices", "active_listings")
    op.drop_column("market_prices", "sales_30d")
    op.drop_column("market_prices", "seller_sales")
    op.drop_column("market_prices", "seller_rating")
    op.drop_column("market_prices", "seller_id")

    # Drop price_history table and index
    op.drop_index(
        "ix_price_history_card_source_recorded",
        table_name="price_history",
    )
    op.drop_table("price_history")
