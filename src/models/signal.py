"""
TCG Radar — Signal Model (Section 14)

Signals are tenant-isolated via RLS. Every query MUST include tenant_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BOOLEAN,
    DECIMAL as SA_DECIMAL,
    INTEGER,
    TIMESTAMP,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Signal(Base):
    """
    Generated trading signal — tenant-isolated via RLS.

    WARNING: Every query on this table MUST filter by tenant_id.
    Querying without tenant_id is a production security bug.
    """

    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        comment="Unique signal identifier",
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="User/tenant ID — RLS enforced",
    )
    card_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="pokemontcg.io canonical ID",
    )
    card_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Card display name",
    )
    signal_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="arbitrage",
        server_default="arbitrage",
        comment="Signal classification: arbitrage, event_driven, bundle, investment",
    )

    # --- Price data ---
    price_eur: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2), nullable=False, comment="Cardmarket buy price in EUR"
    )
    price_usd: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2), nullable=False, comment="TCGPlayer sell price in USD"
    )
    net_profit: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2), nullable=False, comment="Calculated P_real"
    )
    margin_pct: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(6, 2), nullable=False, comment="Profit margin percentage"
    )

    # --- Scores ---
    velocity_score: Mapped[Decimal | None] = mapped_column(
        SA_DECIMAL(6, 2), nullable=True, comment="V_s velocity score"
    )
    velocity_tier: Mapped[int | None] = mapped_column(
        INTEGER, nullable=True, comment="Velocity tier (1=hot, 2=moderate, 3=slow)"
    )
    headache_score: Mapped[Decimal | None] = mapped_column(
        SA_DECIMAL(10, 2), nullable=True, comment="H labor-to-loot score"
    )
    headache_tier: Mapped[int | None] = mapped_column(
        INTEGER, nullable=True, comment="Headache tier (1=easy, 2=decent, 3=hard)"
    )
    maturity_multiplier: Mapped[Decimal | None] = mapped_column(
        SA_DECIMAL(3, 2), nullable=True, comment="Maturity decay multiplier"
    )

    # --- Metadata ---
    condition: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Card condition grade"
    )
    regulation_mark: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Regulation mark for rotation check"
    )
    rotation_risk: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Risk level: SAFE, WATCH, DANGER, ROTATED"
    )
    trend_classification: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Trend: momentum, liquidation, stable, declining"
    )
    bundle_tier: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Bundle: bundle_alert, partial_bundle, single_card"
    )

    # --- Links ---
    tcgplayer_url: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Deep link to TCGPlayer listing"
    )
    cardmarket_url: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Deep link to Cardmarket listing"
    )

    # --- Cascade ---
    cascade_count: Mapped[int] = mapped_column(
        INTEGER,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of times this signal has cascaded",
    )
    acted_on: Mapped[bool] = mapped_column(
        BOOLEAN,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the user acted on this signal",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="Signal expiry timestamp for cascade logic",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Signal creation timestamp",
    )

    __table_args__ = (
        Index("ix_signals_tenant_created", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Signal id={self.id!r} tenant={self.tenant_id!r} "
            f"card={self.card_id!r} profit={self.net_profit}>"
        )
