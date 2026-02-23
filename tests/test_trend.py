"""Tests for trend-adjusted velocity (Section 4.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config import settings
from src.engine.trend import TrendClassification, classify_trend


class TestTrendMatrix:
    """Tests for all four cells of the classification matrix."""

    def test_high_v_rising_price_is_momentum(self) -> None:
        """High velocity + rising price = MOMENTUM, no suppression."""
        cls, suppress = classify_trend(Decimal("2.0"), Decimal("0.05"))
        assert cls == TrendClassification.MOMENTUM
        assert suppress is False

    def test_high_v_flat_price_is_momentum(self) -> None:
        """High velocity + flat price = MOMENTUM."""
        cls, suppress = classify_trend(Decimal("1.5"), Decimal("0.00"))
        assert cls == TrendClassification.MOMENTUM
        assert suppress is False

    def test_high_v_falling_price_is_liquidation(self) -> None:
        """High velocity + falling price = LIQUIDATION, SUPPRESS."""
        cls, suppress = classify_trend(Decimal("2.0"), Decimal("-0.15"))
        assert cls == TrendClassification.LIQUIDATION
        assert suppress is True

    def test_low_v_rising_price_is_stable(self) -> None:
        """Low velocity + rising price = STABLE."""
        cls, suppress = classify_trend(Decimal("0.5"), Decimal("0.05"))
        assert cls == TrendClassification.STABLE
        assert suppress is False

    def test_low_v_flat_price_is_stable(self) -> None:
        """Low velocity + flat price = STABLE."""
        cls, suppress = classify_trend(Decimal("0.3"), Decimal("0.00"))
        assert cls == TrendClassification.STABLE
        assert suppress is False

    def test_low_v_falling_price_is_declining(self) -> None:
        """Low velocity + falling price = DECLINING, NOT suppressed."""
        cls, suppress = classify_trend(Decimal("0.5"), Decimal("-0.15"))
        assert cls == TrendClassification.DECLINING
        assert suppress is False


class TestBoundaries:
    """Boundary condition tests."""

    def test_exact_velocity_threshold_is_high(self) -> None:
        """V_s == 1.5 counts as high velocity."""
        cls, _ = classify_trend(Decimal("1.5"), Decimal("0.05"))
        assert cls == TrendClassification.MOMENTUM

    def test_just_below_velocity_threshold_is_low(self) -> None:
        """V_s = 1.49 is low velocity."""
        cls, _ = classify_trend(Decimal("1.49"), Decimal("0.05"))
        assert cls == TrendClassification.STABLE

    def test_exact_falling_knife_threshold(self) -> None:
        """price_trend_daily == -0.10 exactly counts as falling."""
        cls, suppress = classify_trend(Decimal("2.0"), Decimal("-0.10"))
        assert cls == TrendClassification.LIQUIDATION
        assert suppress is True

    def test_just_above_falling_knife_not_falling(self) -> None:
        """price_trend_daily = -0.09 is NOT falling (above threshold)."""
        cls, suppress = classify_trend(Decimal("2.0"), Decimal("-0.09"))
        assert cls == TrendClassification.MOMENTUM
        assert suppress is False

    def test_custom_thresholds(self) -> None:
        """Override thresholds for specialized classification."""
        cls, suppress = classify_trend(
            Decimal("1.0"), Decimal("-0.05"),
            velocity_threshold=Decimal("0.8"),
            falling_knife_threshold=Decimal("-0.03"),
        )
        assert cls == TrendClassification.LIQUIDATION
        assert suppress is True
