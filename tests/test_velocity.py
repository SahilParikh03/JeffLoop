"""Tests for velocity scorer (Section 4.2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config import settings
from src.engine.velocity import calculate_velocity_score


def test_calculate_velocity_score_tier_1_hot() -> None:
    """daily_sales above tier 1 floor should classify as tier 1."""
    sales = settings.VELOCITY_TIER_1_FLOOR + Decimal("0.01")
    score, tier = calculate_velocity_score(sales)

    assert score == sales
    assert tier == 1


def test_calculate_velocity_score_tier_2_moderate() -> None:
    """daily_sales between tier floors should classify as tier 2."""
    sales = Decimal("1.00")
    score, tier = calculate_velocity_score(sales)

    assert score == sales
    assert tier == 2


def test_calculate_velocity_score_tier_3_slow() -> None:
    """daily_sales at or below tier 2 floor should classify as tier 3."""
    score, tier = calculate_velocity_score(settings.VELOCITY_TIER_2_FLOOR)

    assert score == settings.VELOCITY_TIER_2_FLOOR
    assert tier == 3


def test_calculate_velocity_score_boundary_high_is_tier_2() -> None:
    """daily_sales exactly equal to tier 1 floor belongs to tier 2."""
    score, tier = calculate_velocity_score(settings.VELOCITY_TIER_1_FLOOR)

    assert score == settings.VELOCITY_TIER_1_FLOOR
    assert tier == 2


def test_calculate_velocity_score_boundary_low_is_tier_3() -> None:
    """daily_sales exactly equal to tier 2 floor belongs to tier 3."""
    score, tier = calculate_velocity_score(settings.VELOCITY_TIER_2_FLOOR)

    assert score == settings.VELOCITY_TIER_2_FLOOR
    assert tier == 3


def test_calculate_velocity_score_uses_custom_thresholds() -> None:
    """Custom thresholds should override settings defaults."""
    score, tier = calculate_velocity_score(
        daily_sales=Decimal("2.50"),
        threshold_low=Decimal("2.00"),
        threshold_high=Decimal("3.00"),
    )

    assert score == Decimal("2.50")
    assert tier == 2


def test_calculate_velocity_score_negative_daily_sales_raises() -> None:
    """Negative daily sales are invalid."""
    with pytest.raises(ValueError, match="daily_sales must be non-negative"):
        calculate_velocity_score(Decimal("-0.01"))

