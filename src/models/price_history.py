"""
TCG Radar — Price History Model (Phase 2, Stream A)

Append-only log of price snapshots per card per source.
Never updated — each poll cycle appends a new row.
Used by engine/price_trend.py to compute 7-day trend slope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DECIMAL, TIMESTAMP, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class PriceHistory(Base):
    """
    Append-only price snapshot per card per source.

    Keyed by auto-generated UUID. Every poll cycle for a card_id+source
    pair inserts a new row — no upsert, no update. This gives the 7-day
    sliding window that engine/price_trend.py uses for slope calculation.

    Index: (card_id, source, recorded_at) supports efficient range scans.
    """

    __tablename__ = "price_history"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="UUID primary key, server-generated",
    )
    card_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="pokemontcg.io canonical ID: {set_code}-{card_number}",
    )
    source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Data source: 'justtcg', 'pokemontcg', 'poketrace'",
    )
    price_usd: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2),
        nullable=True,
        comment="Price in USD at time of snapshot",
    )
    price_eur: Mapped[Decimal | None] = mapped_column(
        DECIMAL(10, 2),
        nullable=True,
        comment="Price in EUR at time of snapshot",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="UTC timestamp of when this price was recorded",
    )

    # Composite index for efficient 7-day window queries
    __table_args__ = (
        Index(
            "ix_price_history_card_source_recorded",
            "card_id",
            "source",
            "recorded_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PriceHistory card_id={self.card_id!r} source={self.source!r} "
            f"usd={self.price_usd} eur={self.price_eur} at={self.recorded_at}>"
        )
