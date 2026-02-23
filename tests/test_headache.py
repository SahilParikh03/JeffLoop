"""Tests for Headache Score / Labor-to-Loot (Section 4.4)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config import HeadacheTier, settings
from src.engine.headache import calculate_headache_score


def test_calculate_headache_score_happy_path_tier_1() -> None:
    """Section 4.4: H > 15 should classify as tier 1."""
    score, tier = calculate_headache_score(
        net_profit=Decimal("60"),
        num_transactions=3,
    )

    assert score == Decimal("20")
    assert tier == HeadacheTier.TIER_1.value


def test_calculate_headache_score_boundary_h_equals_15_is_tier_2() -> None:
    """Section 4.4: H == 15 belongs to tier 2 (not tier 1)."""
    score, tier = calculate_headache_score(
        net_profit=settings.HEADACHE_TIER_1_FLOOR,
        num_transactions=1,
    )

    assert score == settings.HEADACHE_TIER_1_FLOOR
    assert tier == HeadacheTier.TIER_2.value


def test_calculate_headache_score_boundary_h_equals_5_is_tier_3() -> None:
    """Section 4.4: H == 5 belongs to tier 3 because tier 2 is strictly > 5."""
    score, tier = calculate_headache_score(
        net_profit=settings.HEADACHE_TIER_2_FLOOR,
        num_transactions=1,
    )

    assert score == settings.HEADACHE_TIER_2_FLOOR
    assert tier == HeadacheTier.TIER_3.value


def test_calculate_headache_score_raises_for_non_positive_transactions() -> None:
    """Section 4.4: Number_of_Transactions must be positive."""
    with pytest.raises(ValueError, match="num_transactions must be greater than 0"):
        calculate_headache_score(
            net_profit=Decimal("10"),
            num_transactions=0,
        )

