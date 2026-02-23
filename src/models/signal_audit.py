"""
TCG Radar — Signal Audit Model (Section 14)

Full snapshot of what the system saw when generating a signal.
Used for debugging false positives and resolving user disputes.

No RLS — admin-only, append-only table.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class SignalAudit(Base):
    """
    Immutable audit record attached to each generated signal.

    Stores the raw data snapshot: prices, fee breakdown, scores,
    and user profile at time of calculation.

    No RLS on this table — admin-only access.
    """

    __tablename__ = "signal_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        comment="Unique audit record identifier",
    )
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="FK to signals.id (constraint defined in migration)",
    )

    # --- Snapshot data ---
    source_prices: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Raw price data: {cm_eur, tcg_usd, source, condition, forex_rate}",
    )
    fee_calc: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full fee breakdown: {tcg_fees, customs, shipping, forwarder, insurance}",
    )
    snapshot_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Complete system state: scores, thresholds, user profile snapshot",
    )
    calculation_version: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="v1",
        server_default="v1",
        comment="Versioning for calculation logic changes",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Audit record creation timestamp",
    )

    __table_args__ = (
        Index("ix_signal_audit_signal_id", "signal_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<SignalAudit id={self.id!r} signal_id={self.signal_id!r}>"
        )
