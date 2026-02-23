"""Tests for signal cascade logic (Section 14)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.config import settings
from src.signals.cascade import (
    compute_cascade_available_at,
    increment_cascade_count,
    should_cascade,
)


_NOW = datetime(2026, 2, 22, 12, 0, 0, tzinfo=timezone.utc)


class TestComputeCascadeAvailableAt:
    def test_default_10_second_cooldown(self) -> None:
        """available_at = expires_at + 10 seconds."""
        expires = _NOW
        result = compute_cascade_available_at(expires)
        assert result == expires + timedelta(seconds=settings.CASCADE_COOLDOWN_SECONDS)

    def test_custom_cooldown(self) -> None:
        expires = _NOW
        result = compute_cascade_available_at(expires, cooldown_seconds=30)
        assert result == expires + timedelta(seconds=30)


class TestShouldCascade:
    def test_ready_after_cooldown(self) -> None:
        """Signal expired 15s ago, not acted on, count=0 → cascade."""
        expires = _NOW - timedelta(seconds=15)
        result, reason = should_cascade(expires, False, 0, reference_time=_NOW)
        assert result is True
        assert reason == "cascade_ready"

    def test_within_cooldown_window(self) -> None:
        """Signal expired 5s ago (within 10s cooldown) → no cascade."""
        expires = _NOW - timedelta(seconds=5)
        result, reason = should_cascade(expires, False, 0, reference_time=_NOW)
        assert result is False
        assert "cooldown_pending" in reason

    def test_exact_cooldown_boundary(self) -> None:
        """Signal expired exactly 10s ago → cascade (>= check)."""
        expires = _NOW - timedelta(seconds=10)
        result, reason = should_cascade(expires, False, 0, reference_time=_NOW)
        assert result is True

    def test_acted_on_blocks_cascade(self) -> None:
        """User acted on signal → no cascade, regardless of timing."""
        expires = _NOW - timedelta(seconds=60)
        result, reason = should_cascade(expires, True, 0, reference_time=_NOW)
        assert result is False
        assert reason == "signal_acted_on"

    def test_cascade_limit_reached(self) -> None:
        """Count at max (5) → no cascade."""
        expires = _NOW - timedelta(seconds=60)
        result, reason = should_cascade(expires, False, 5, reference_time=_NOW)
        assert result is False
        assert "cascade_limit_reached" in reason

    def test_cascade_count_4_still_allowed(self) -> None:
        """Count=4, max=5 → one more cascade allowed."""
        expires = _NOW - timedelta(seconds=60)
        result, reason = should_cascade(expires, False, 4, reference_time=_NOW)
        assert result is True

    def test_not_yet_expired(self) -> None:
        """Signal hasn't expired yet → cooldown hasn't started → no cascade."""
        expires = _NOW + timedelta(seconds=30)
        result, reason = should_cascade(expires, False, 0, reference_time=_NOW)
        assert result is False
        assert "cooldown_pending" in reason

    def test_custom_max_cascades(self) -> None:
        """Override max cascades to 2."""
        expires = _NOW - timedelta(seconds=60)
        result, reason = should_cascade(expires, False, 2, reference_time=_NOW, max_cascades=2)
        assert result is False
        assert "cascade_limit_reached" in reason


class TestIncrementCascadeCount:
    def test_increment_from_zero(self) -> None:
        new_count, limit = increment_cascade_count(0)
        assert new_count == 1
        assert limit is False

    def test_increment_to_limit(self) -> None:
        """4 → 5 → limit_reached=True."""
        new_count, limit = increment_cascade_count(4)
        assert new_count == 5
        assert limit is True

    def test_custom_max(self) -> None:
        new_count, limit = increment_cascade_count(2, max_cascades=3)
        assert new_count == 3
        assert limit is True
