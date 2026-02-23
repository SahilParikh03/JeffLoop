"""
TCG Radar — Market Price Model (Section 14, Layer A)

Raw price data from APIs. No signal logic. No tenant data.
This is public market data — no RLS needed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, INTEGER, TIMESTAMP, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class MarketPrice(Base):
    """
    Stores cross-platform card prices from API sources.

    Primary key is (card_id, source) — one row per card per data source.
    Prices update on the API polling cadence (6hr for JustTCG free tier).

    Layer A timestamps do NOT leak signal timing — prices update on a fixed
    cadence unrelated to when signals are generated (Section 14).
    """

    __tablename__ = "market_prices"

    card_id: Mapped[str] = mapped_column(
        String, primary_key=True, comment="pokemontcg.io canonical ID: {set_code}-{card_number}"
    )
    source: Mapped[str] = mapped_column(
        String, primary_key=True, comment="Data source: 'justtcg', 'pokemontcg', 'poketrace'"
    )
    price_usd: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2), nullable=True, comment="Price in USD"
    )
    price_eur: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2), nullable=True, comment="Price in EUR"
    )
    condition: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Card condition (not all sources provide this)"
    )
    last_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last time this price record was updated",
    )

    # Phase 2 — seller data (populated by Layer 3 scraping)
    seller_id: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Seller identifier from scraper"
    )
    seller_rating: Mapped[Decimal | None] = mapped_column(
        DECIMAL(5, 2), nullable=True, comment="Seller rating percentage"
    )
    seller_sales: Mapped[int | None] = mapped_column(
        INTEGER, nullable=True, comment="Seller total sales count"
    )

    # Phase 2 — PokeTrace velocity data
    sales_30d: Mapped[int | None] = mapped_column(
        INTEGER, nullable=True, comment="Sales in last 30 days (PokeTrace)"
    )
    active_listings: Mapped[int | None] = mapped_column(
        INTEGER, nullable=True, comment="Active listing count (PokeTrace)"
    )

    # Index per CLAUDE.md: market_prices(card_id, source)
    __table_args__ = (
        Index("ix_market_prices_card_source", "card_id", "source"),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketPrice card_id={self.card_id!r} source={self.source!r} "
            f"usd={self.price_usd} eur={self.price_eur}>"
        )
