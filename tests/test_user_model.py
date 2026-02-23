"""Tests for the User model (Phase 4 — Stream 1)."""

from __future__ import annotations

import uuid

from src.models.user import User


class TestUserModel:
    def test_instantiation_with_explicit_id(self) -> None:
        """User can be created with an explicit UUID id."""
        uid = uuid.uuid4()
        user = User(id=uid, is_active=True)
        assert user.id == uid

    def test_uuid_fields_are_distinct(self) -> None:
        """Two User instances with distinct UUIDs are not equal."""
        u1 = User(id=uuid.uuid4())
        u2 = User(id=uuid.uuid4())
        assert u1.id != u2.id
        # Both are valid UUID4 values
        uuid.UUID(str(u1.id))
        uuid.UUID(str(u2.id))

    def test_is_active_accepts_true(self) -> None:
        """is_active field accepts and stores True."""
        user = User(is_active=True)
        assert user.is_active is True

    def test_email_nullable(self) -> None:
        """email can be None (Telegram-only users have no email in MVP)."""
        user = User()
        user.email = None
        assert user.email is None

    def test_email_can_be_set(self) -> None:
        """email field accepts a string value."""
        user = User()
        user.email = "trainer@pokecenter.com"
        assert user.email == "trainer@pokecenter.com"

    def test_repr_contains_key_info(self) -> None:
        """__repr__ includes id and email."""
        user = User()
        user.email = "ash@pallet.town"
        r = repr(user)
        assert "User" in r
        assert "email=" in r
        assert "is_active=" in r
