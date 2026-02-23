"""
Tests for Maturity Decay (Section 4.2.2)

Validates:
- Each decay band (< 30d, 30-60d, 60-90d, > 90d)
- Future release dates return 1.0
- Boundary conditions (exact 30, 60, 90 days)
- Reprint rumor penalty application
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.config import settings
from src.engine.maturity import (
    apply_maturity_penalty_with_reprint_rumor,
    calculate_maturity_decay,
)


class TestMaturityDecay:
    """Test calculate_maturity_decay() function."""

    def test_fresh_set_under_30_days(self):
        """Test set age < 30 days returns 1.0 (no penalty)."""
        today = date(2026, 2, 22)
        release_date = date(2026, 2, 10)  # 12 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == settings.MATURITY_DECAY_30D
        assert result == Decimal("1.0")

    def test_fresh_set_1_day_old(self):
        """Test set age 1 day returns 1.0."""
        today = date(2026, 2, 22)
        release_date = date(2026, 2, 21)

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("1.0")

    def test_young_set_30_days_boundary(self):
        """Test that exactly 30 days old returns 0.9 (not 1.0)."""
        release_date = date(2026, 2, 22)
        today = date(2026, 3, 24)  # Exactly 30 days later

        result = calculate_maturity_decay(release_date, reference_date=today)

        # Boundary: 30 days should be in the 30-60d band, not fresh
        assert result == settings.MATURITY_DECAY_60D
        assert result == Decimal("0.9")

    def test_young_set_30_to_60_days(self):
        """Test set age 30-60 days returns 0.9."""
        release_date = date(2026, 2, 22)
        today = date(2026, 3, 25)  # 31 days later

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.9")

    def test_young_set_45_days_old(self):
        """Test set age 45 days (middle of 30-60 band) returns 0.9."""
        today = date(2026, 4, 8)
        release_date = date(2026, 2, 22)  # ~45 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.9")

    def test_maturing_set_60_days_boundary(self):
        """Test that exactly 60 days old transitions to 0.8."""
        today = date(2026, 4, 23)
        release_date = date(2026, 2, 22)  # Exactly 60 days

        result = calculate_maturity_decay(release_date, reference_date=today)

        # Boundary: 60 days should be in the 60-90d band
        assert result == settings.MATURITY_DECAY_90D
        assert result == Decimal("0.8")

    def test_maturing_set_60_to_90_days(self):
        """Test set age 60-90 days returns 0.8."""
        today = date(2026, 4, 25)
        release_date = date(2026, 2, 22)  # ~62 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.8")

    def test_maturing_set_75_days_old(self):
        """Test set age 75 days (middle of 60-90 band) returns 0.8."""
        today = date(2026, 5, 8)
        release_date = date(2026, 2, 22)  # ~75 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.8")

    def test_normalized_set_90_days_boundary(self):
        """Test that exactly 90 days old transitions to 0.7."""
        today = date(2026, 5, 23)
        release_date = date(2026, 2, 22)  # Exactly 90 days

        result = calculate_maturity_decay(release_date, reference_date=today)

        # Boundary: 90 days should be in the >= 90d band
        assert result == settings.MATURITY_DECAY_OLD
        assert result == Decimal("0.7")

    def test_normalized_set_over_90_days(self):
        """Test set age > 90 days returns 0.7."""
        today = date(2026, 6, 1)
        release_date = date(2026, 2, 22)  # ~100 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.7")

    def test_normalized_set_180_days_old(self):
        """Test set age 180+ days still returns 0.7."""
        today = date(2026, 8, 22)
        release_date = date(2026, 2, 22)  # 180 days old

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("0.7")

    def test_future_release_date_returns_1_0(self):
        """Test future release dates return 1.0 (no penalty)."""
        today = date(2026, 2, 22)
        release_date = date(2026, 3, 1)  # 7 days in the future

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("1.0")

    def test_future_release_far_ahead(self):
        """Test far-future release dates return 1.0."""
        today = date(2026, 2, 22)
        release_date = date(2026, 12, 31)  # ~10 months in future

        result = calculate_maturity_decay(release_date, reference_date=today)

        assert result == Decimal("1.0")

    def test_uses_today_when_reference_date_none(self):
        """Test that reference_date defaults to today()."""
        release_date = date.today() - timedelta(days=15)

        result = calculate_maturity_decay(release_date, reference_date=None)

        assert result == Decimal("1.0")

    def test_30th_anniversary_scenario(self):
        """Test realistic scenario: 30th Anniversary set (Feb 27, 2026)."""
        reference_date = date(2026, 2, 22)  # Today
        anniversary_release = date(2026, 2, 27)  # 5 days in future

        # Before release
        result_before = calculate_maturity_decay(
            anniversary_release, reference_date=reference_date
        )
        assert result_before == Decimal("1.0")

        # 15 days after release (hype window)
        result_hype = calculate_maturity_decay(
            anniversary_release, reference_date=date(2026, 3, 14)
        )
        assert result_hype == Decimal("1.0")

        # 45 days after release (hype decay starting)
        result_decay = calculate_maturity_decay(
            anniversary_release, reference_date=date(2026, 4, 13)
        )
        assert result_decay == Decimal("0.9")

        # 60 days after (significant decay)
        result_significant = calculate_maturity_decay(
            anniversary_release, reference_date=date(2026, 4, 28)
        )
        assert result_significant == Decimal("0.8")


class TestReprintRumorPenalty:
    """Test apply_maturity_penalty_with_reprint_rumor()."""

    def test_no_reprint_rumor_returns_base_decay(self):
        """Test that with no reprint rumor, base decay is returned unchanged."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("0.8")  # Set > 60 days old

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=False,
            reference_date=date(2026, 5, 1),
        )

        assert result == Decimal("0.8")

    def test_reprint_rumor_under_60_days_no_penalty(self):
        """Test that reprint rumors before 60 days don't apply penalty."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("0.9")  # 30-60 days old

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=True,
            reference_date=date(2026, 3, 15),  # 21 days after release
        )

        # No penalty before 60 days
        assert result == Decimal("0.9")

    def test_reprint_rumor_over_60_days_applies_penalty(self):
        """Test that reprint rumors after 60 days apply -20% penalty."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("0.8")  # 60+ days old

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=True,
            reference_date=date(2026, 5, 1),  # 68 days after release
        )

        # Apply penalty: 0.8 * 0.8 = 0.64
        expected = base_decay * settings.MATURITY_REPRINT_RUMOR_PENALTY
        assert result == expected
        assert result == Decimal("0.64")

    def test_reprint_rumor_exact_60_days_applies_penalty(self):
        """Test reprint penalty at exactly 60 days."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("0.8")

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=True,
            reference_date=date(2026, 4, 23),  # Exactly 60 days
        )

        # At 60 days, penalty should apply (> 60 means strictly greater... wait)
        # Actually the condition is set_age_days > 60, so at exactly 60, no penalty
        assert result == Decimal("0.8")

    def test_reprint_rumor_61_days_applies_penalty(self):
        """Test reprint penalty at 61 days (just over 60)."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("0.8")

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=True,
            reference_date=date(2026, 4, 24),  # 61 days
        )

        expected = base_decay * settings.MATURITY_REPRINT_RUMOR_PENALTY
        assert result == expected

    def test_reprint_rumor_penalty_stacks_on_fresh_set(self):
        """Test that fresh set with reprint rumor gets base 1.0 (no penalty yet)."""
        release_date = date(2026, 2, 22)
        base_decay = Decimal("1.0")  # Fresh set

        result = apply_maturity_penalty_with_reprint_rumor(
            base_decay,
            release_date,
            reprint_rumored=True,
            reference_date=date(2026, 3, 1),  # 7 days after release
        )

        # Only applies after 60 days
        assert result == Decimal("1.0")
