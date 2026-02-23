"""
TCG Radar — User Model (Phase 4)

Core users table. Provides referential integrity for:
  - signals.tenant_id REFERENCES users(id)
  - user_profiles.id  REFERENCES users(id) (1:1 extension pattern)

Email is nullable — Telegram-only users have no email in MVP.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BOOLEAN, TIMESTAMP, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class User(Base):
    """
    Core user identity record.

    Every tenant_id in signals and every user_profiles.id must reference
    a row in this table. Email is nullable for Telegram-only users (MVP).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        comment="Primary key — shared with user_profiles.id (1:1 extension)",
    )
    email: Mapped[str | None] = mapped_column(
        String,
        unique=True,
        nullable=True,
        comment="Email address (nullable — Telegram-only users have none in MVP)",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        comment="Account creation timestamp",
    )
    is_active: Mapped[bool] = mapped_column(
        BOOLEAN,
        default=True,
        server_default="true",
        comment="Soft-delete flag",
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id!r} email={self.email!r} is_active={self.is_active!r}>"
        )
