"""
TCG Radar — User Profile Model (Section 8)

Each subscriber has a profile that personalizes every signal.
The user's profile determines fee schedules, shipping estimates,
import duties, forwarder preferences, and signal filters.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    BIGINT,
    BOOLEAN,
    DECIMAL as SA_DECIMAL,
    INTEGER,
    TIMESTAMP,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class UserProfile(Base):
    """
    User profile for signal personalization.

    Every signal's P_real is calculated using this user's specific:
    - Fee schedule (determined by seller_level and preferred_platforms)
    - Country (import duties, VAT, shipping estimates)
    - Forwarder preferences (receiving fee, consolidation fee, insurance rate)
    - Signal filters (min profit, min headache score, card categories)
    """

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="Unique user identifier",
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BIGINT,
        unique=True,
        nullable=True,
        comment="Telegram chat ID for signal delivery (MVP)",
    )
    discord_channel_id: Mapped[int | None] = mapped_column(
        BIGINT,
        nullable=True,
        comment="Discord channel ID for signal delivery (Phase 2)",
    )

    # --- Section 8: Core profile fields ---
    country: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="User country — determines import duties, VAT rate, shipping estimates",
    )
    seller_level: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="Seller tier (e.g., 'tcgplayer_level_2', 'ebay_top_rated', 'cardmarket_pro')",
    )
    preferred_platforms: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Platforms the user sells on — affects fee calculation",
    )

    # --- Signal filters ---
    min_profit_threshold: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2),
        default=Decimal("5.00"),
        server_default="5.00",
        comment="Below this P_real, no signal sent",
    )
    min_headache_score: Mapped[int] = mapped_column(
        INTEGER,
        default=5,
        server_default="5",
        comment="Below this H tier, no signal sent",
    )
    card_categories: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Preferred categories: vintage, modern_competitive, japanese, sealed",
    )
    currency: Mapped[str] = mapped_column(
        String,
        default="USD",
        server_default="USD",
        comment="Display preference (USD/EUR)",
    )

    # --- Import / shipping ---
    import_duty_rate: Mapped[Decimal | None] = mapped_column(
        SA_DECIMAL(5, 4),
        nullable=True,
        comment="User-configurable import duty/VAT estimate (conservative)",
    )

    # --- Forwarder preferences (Section 4.1.2) ---
    forwarder_receiving_fee: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2),
        default=Decimal("3.50"),
        server_default="3.50",
        comment="Per-package receiving fee (default $3.50)",
    )
    forwarder_consolidation_fee: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(10, 2),
        default=Decimal("7.50"),
        server_default="7.50",
        comment="Per-box consolidation fee (default $7.50)",
    )
    insurance_rate: Mapped[Decimal] = mapped_column(
        SA_DECIMAL(5, 4),
        default=Decimal("0.025"),
        server_default="0.025",
        comment="Insurance rate as fraction of declared value (default 2.5%)",
    )
    use_forwarder: Mapped[bool] = mapped_column(
        BOOLEAN,
        default=False,
        server_default="false",
        comment="Whether this user uses a forwarding service",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        comment="Profile creation date",
    )

    def __repr__(self) -> str:
        return (
            f"<UserProfile id={self.id!r} country={self.country!r} "
            f"seller_level={self.seller_level!r}>"
        )
