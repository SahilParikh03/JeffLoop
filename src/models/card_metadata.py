"""
TCG Radar — Card Metadata Model

Stores card metadata from pokemontcg.io API. Critical for:
- Variant ID Validation (Section 4.7) — canonical card identity
- Rotation Calendar (Section 7) — regulation mark lookups
- Maturity Decay (Section 4.2.2) — set release date for age calculation
- Deep Links — TCGPlayer/Cardmarket URLs
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import DATE, TIMESTAMP, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class CardMetadata(Base):
    """
    Card metadata from pokemontcg.io.

    The card_id uses the pokemontcg.io canonical format: "{set_code}-{card_number}"
    (e.g., "sv1-25" = Scarlet & Violet base set, card #25).

    This is the source of truth for Variant ID Validation (Section 4.7).
    """

    __tablename__ = "card_metadata"

    card_id: Mapped[str] = mapped_column(
        String,
        primary_key=True,
        comment="pokemontcg.io canonical ID: {set_code}-{card_number}",
    )
    name: Mapped[str] = mapped_column(
        String, nullable=False, comment="Card name (e.g., 'Charizard ex')"
    )
    set_code: Mapped[str] = mapped_column(
        String, nullable=False, comment="Set code (e.g., 'sv1')"
    )
    set_name: Mapped[str] = mapped_column(
        String, nullable=False, comment="Set name (e.g., 'Scarlet & Violet')"
    )
    card_number: Mapped[str] = mapped_column(
        String, nullable=False, comment="Card number within set (e.g., '25')"
    )
    regulation_mark: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment="Regulation mark (G, H, etc.) — used for rotation calendar (Section 7)",
    )
    set_release_date: Mapped[date | None] = mapped_column(
        DATE,
        nullable=True,
        comment="Set release date — used for Maturity Decay calculation (Section 4.2.2)",
    )
    legality_standard: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Standard format legality"
    )
    legality_expanded: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Expanded format legality"
    )
    tcgplayer_url: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Deep link to TCGPlayer listing"
    )
    cardmarket_url: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Deep link to Cardmarket listing"
    )
    image_url: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Card image URL"
    )
    last_updated: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="Last metadata refresh timestamp",
    )

    def __repr__(self) -> str:
        return (
            f"<CardMetadata card_id={self.card_id!r} name={self.name!r} "
            f"reg_mark={self.regulation_mark!r}>"
        )
