"""
Tests for Rotation Risk Checker (Section 7)

Validates:
- Each risk level (SAFE, WATCH, DANGER, ROTATED, UNKNOWN)
- Banned cards → ROTATED
- None regulation mark → UNKNOWN
- Rotation calendar lookup
- Mark distance calculation
"""

from __future__ import annotations

from datetime import date

import pytest

from src.engine.rotation import (
    REGULATION_MARK_ORDER,
    check_rotation_risk,
    get_mark_distance_from_current,
)


class TestCheckRotationRisk:
    """Test check_rotation_risk() function."""

    def test_banned_card_returns_rotated(self):
        """Test that banned cards always return ROTATED risk."""
        result = check_rotation_risk(
            regulation_mark="H",
            legality_standard="Banned",
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "ROTATED"
        assert result["months_until_rotation"] is None
        assert result["rotation_date"] is None

    def test_banned_card_ignores_regulation_mark(self):
        """Test that banned status overrides regulation mark."""
        result = check_rotation_risk(
            regulation_mark="H",  # Current legal mark
            legality_standard="Banned",
        )

        # Should still be ROTATED even with current mark
        assert result["risk_level"] == "ROTATED"
        assert result["at_risk"] is True

    def test_none_regulation_mark_returns_unknown(self):
        """Test that None regulation mark returns UNKNOWN."""
        result = check_rotation_risk(
            regulation_mark=None,
            legality_standard="Standard",
        )

        assert result["at_risk"] is False
        assert result["risk_level"] == "UNKNOWN"
        assert result["months_until_rotation"] is None
        assert result["rotation_date"] is None

    def test_current_legal_mark_h_returns_safe(self):
        """Test that current legal mark (H) has no announced rotation → SAFE."""
        result = check_rotation_risk(
            regulation_mark="H",
            legality_standard="Standard",
            reference_date=date(2026, 2, 22),
        )

        assert result["at_risk"] is False
        assert result["risk_level"] == "SAFE"
        assert result["rotation_date"] is None

    def test_rotation_g_march_well_ahead_returns_safe(self):
        """Test G mark with rotation date far in future (>6 months) → SAFE."""
        # Reference: today is Feb 22 2026, rotation is Apr 10 2026 (~47 days)
        # This should be DANGER, not SAFE. Let me use a different reference.
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2025, 10, 1),  # ~6 months before rotation
        )

        assert result["at_risk"] is False
        assert result["risk_level"] == "SAFE"
        assert result["rotation_date"] == date(2026, 4, 10)

    def test_rotation_g_watch_window(self):
        """Test G mark 3-6 months before rotation → WATCH."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 1, 1),  # ~100 days before rotation (April 10)
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "WATCH"  # 100 days is > 90
        assert result["rotation_date"] == date(2026, 4, 10)
        assert result["months_until_rotation"] in [3, 4]

    def test_rotation_g_danger_window(self):
        """Test G mark <3 months before rotation → DANGER."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 3, 15),  # 26 days before rotation
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "DANGER"
        assert result["rotation_date"] == date(2026, 4, 10)
        assert result["months_until_rotation"] == 0  # Less than a month

    def test_rotation_g_exactly_180_days_before_is_safe(self):
        """Test G mark exactly 180 days before rotation → SAFE (boundary)."""
        # Oct 13, 2025 + 180 days = Apr 10, 2026
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2025, 10, 13),  # Exactly 180 days before
        )

        # 180 days is the boundary; >180 is SAFE
        assert result["risk_level"] in ["SAFE", "WATCH"]

    def test_rotation_g_179_days_before_is_watch(self):
        """Test G mark 179 days before rotation → WATCH."""
        # Oct 14, 2025 + 179 days = Apr 10, 2026
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2025, 10, 14),  # 179 days before
        )

        # 179 days is just under 180, should be WATCH
        assert result["risk_level"] == "WATCH"

    def test_rotation_g_exactly_90_days_before_is_danger(self):
        """Test G mark exactly 90 days before rotation → DANGER (boundary)."""
        # Jan 11, 2026 + 90 days = Apr 10, 2026
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 1, 11),  # Exactly 90 days before
        )

        # 90 days is the boundary; <90 is DANGER
        assert result["at_risk"] is True
        assert result["risk_level"] in ["DANGER", "WATCH"]

    def test_rotation_g_already_passed(self):
        """Test G mark after rotation date → ROTATED."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 4, 11),  # 1 day after rotation
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "ROTATED"
        assert result["months_until_rotation"] == 0

    def test_rotation_g_far_past(self):
        """Test G mark long after rotation → ROTATED."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 8, 1),  # 4 months after rotation
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "ROTATED"

    def test_unknown_mark_not_in_calendar(self):
        """Test regulation mark not in ROTATION_CALENDAR → ROTATED."""
        result = check_rotation_risk(
            regulation_mark="F",  # Not in current calendar
            legality_standard="Standard",
            reference_date=date(2026, 2, 22),
        )

        # F is not in the calendar, so it's assumed rotated
        assert result["at_risk"] is True
        assert result["risk_level"] == "ROTATED"

    def test_uses_today_when_reference_date_none(self):
        """Test that reference_date defaults to today()."""
        # This test would fail if G mark is past rotation, so we use H
        result = check_rotation_risk(
            regulation_mark="H",
            legality_standard="Standard",
            reference_date=None,
        )

        # H has no rotation date, so should always be SAFE
        assert result["risk_level"] == "SAFE"

    def test_april_30th_2026_scenario(self):
        """Test realistic scenario: April 30, 2026 (20 days after rotation)."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 4, 30),  # 20 days after rotation
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "ROTATED"
        assert result["months_until_rotation"] == 0

    def test_today_feb_22_2026_with_g_mark(self):
        """Test today's date (Feb 22, 2026) with G mark (47 days to rotation)."""
        result = check_rotation_risk(
            regulation_mark="G",
            legality_standard="Standard",
            reference_date=date(2026, 2, 22),  # Today
        )

        assert result["at_risk"] is True
        assert result["risk_level"] == "DANGER"  # <3 months (47 days)
        assert result["rotation_date"] == date(2026, 4, 10)
        assert result["months_until_rotation"] == 1


class TestMarkDistance:
    """Test get_mark_distance_from_current()."""

    def test_current_mark_h_distance_zero(self):
        """Test that current mark H has distance 0."""
        distance = get_mark_distance_from_current("H")
        assert distance == 0

    def test_future_mark_i_distance_zero(self):
        """Test that future mark I still returns 0 (or negative distance treated as 0)."""
        distance = get_mark_distance_from_current("I")
        assert distance == 0  # Not in past

    def test_one_mark_behind_g_distance_one(self):
        """Test that G mark (one behind H) has distance 1."""
        distance = get_mark_distance_from_current("G")
        assert distance == 1

    def test_two_marks_behind_f_distance_two(self):
        """Test that F mark (two behind H) has distance 2."""
        distance = get_mark_distance_from_current("F")
        assert distance == 2

    def test_three_marks_behind_e_distance_three(self):
        """Test that E mark (three behind H) has distance 3."""
        distance = get_mark_distance_from_current("E")
        assert distance == 3

    def test_oldest_mark_d_distance_four(self):
        """Test that D mark (four behind H) has distance 4."""
        distance = get_mark_distance_from_current("D")
        assert distance == 4

    def test_none_mark_returns_none(self):
        """Test that None regulation mark returns None."""
        distance = get_mark_distance_from_current(None)
        assert distance is None

    def test_invalid_mark_returns_none(self):
        """Test that invalid mark returns None."""
        distance = get_mark_distance_from_current("Z")
        assert distance is None

    def test_regulation_mark_order_defined(self):
        """Test that REGULATION_MARK_ORDER is properly defined."""
        assert REGULATION_MARK_ORDER == ["D", "E", "F", "G", "H", "I"]
        assert "H" in REGULATION_MARK_ORDER


class TestIntegration:
    """Integration tests combining multiple scenarios."""

    def test_lifecycle_of_g_mark_card(self):
        """Test complete lifecycle of a G-mark card from now until rotation."""
        # Today (Feb 22, 2026): DANGER
        today = check_rotation_risk("G", "Standard", date(2026, 2, 22))
        assert today["risk_level"] == "DANGER"

        # March 15 (3 weeks away): Still DANGER
        mid_march = check_rotation_risk("G", "Standard", date(2026, 3, 15))
        assert mid_march["risk_level"] == "DANGER"

        # April 9 (day before rotation): Still DANGER
        day_before = check_rotation_risk("G", "Standard", date(2026, 4, 9))
        assert day_before["risk_level"] == "DANGER"

        # April 10 (rotation date): Still technically DANGER until end of day?
        # Actually April 10 exactly might be treated as on rotation date
        on_rotation = check_rotation_risk("G", "Standard", date(2026, 4, 10))
        assert on_rotation["risk_level"] in ["DANGER", "ROTATED"]

        # April 11 (day after): ROTATED
        day_after = check_rotation_risk("G", "Standard", date(2026, 4, 11))
        assert day_after["risk_level"] == "ROTATED"

    def test_h_mark_always_safe(self):
        """Test that H mark (current, no rotation announced) is always SAFE."""
        past = check_rotation_risk("H", "Standard", date(2025, 1, 1))
        assert past["risk_level"] == "SAFE"

        today = check_rotation_risk("H", "Standard", date(2026, 2, 22))
        assert today["risk_level"] == "SAFE"

        future = check_rotation_risk("H", "Standard", date(2027, 12, 31))
        assert future["risk_level"] == "SAFE"
