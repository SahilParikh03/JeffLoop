"""Tests for Seller Density Score and Bundle Logic (Section 4.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config import settings
from src.engine.bundle import BundleResult, BundleTier, calculate_seller_density_score


class TestBundleTiers:
    """SDS tier classification tests."""

    def test_sds_5_is_bundle_alert(self) -> None:
        result = calculate_seller_density_score(5, Decimal("50.00"), Decimal("10.00"))
        assert result.tier == BundleTier.BUNDLE_ALERT
        assert result.sds == 5
        assert result.suppress is False

    def test_sds_10_is_bundle_alert(self) -> None:
        result = calculate_seller_density_score(10, Decimal("30.00"), Decimal("5.00"))
        assert result.tier == BundleTier.BUNDLE_ALERT

    def test_sds_4_is_partial_bundle(self) -> None:
        result = calculate_seller_density_score(4, Decimal("50.00"), Decimal("10.00"))
        assert result.tier == BundleTier.PARTIAL_BUNDLE

    def test_sds_2_is_partial_bundle(self) -> None:
        result = calculate_seller_density_score(2, Decimal("50.00"), Decimal("10.00"))
        assert result.tier == BundleTier.PARTIAL_BUNDLE

    def test_sds_1_is_single_card(self) -> None:
        result = calculate_seller_density_score(1, Decimal("50.00"), Decimal("10.00"))
        assert result.tier == BundleTier.SINGLE_CARD
        assert result.suppress is False


class TestSuppression:
    """SDS=1 + sub-$25 + unprofitable → suppress signal."""

    def test_sds_1_cheap_card_unprofitable_suppressed(self) -> None:
        """The classic case: $10 card, $15 shipping, negative profit."""
        result = calculate_seller_density_score(1, Decimal("10.00"), Decimal("-5.00"))
        assert result.suppress is True
        assert "SDS=1" in result.reason

    def test_sds_1_cheap_card_zero_profit_suppressed(self) -> None:
        """Zero profit also gets suppressed."""
        result = calculate_seller_density_score(1, Decimal("20.00"), Decimal("0.00"))
        assert result.suppress is True

    def test_sds_1_cheap_card_positive_profit_not_suppressed(self) -> None:
        """Positive profit survives, even for cheap singles."""
        result = calculate_seller_density_score(1, Decimal("20.00"), Decimal("1.00"))
        assert result.suppress is False

    def test_sds_1_expensive_card_unprofitable_not_suppressed(self) -> None:
        """$30 card at SDS=1 — above $25 threshold, no suppression."""
        result = calculate_seller_density_score(1, Decimal("30.00"), Decimal("-2.00"))
        assert result.suppress is False

    def test_sds_2_cheap_card_unprofitable_not_suppressed(self) -> None:
        """SDS=2 even with cheap unprofitable card → partial bundle, no suppression."""
        result = calculate_seller_density_score(2, Decimal("10.00"), Decimal("-5.00"))
        assert result.suppress is False
        assert result.tier == BundleTier.PARTIAL_BUNDLE

    def test_sds_1_at_25_threshold_not_suppressed(self) -> None:
        """Card price exactly $25.00 is NOT below threshold, no suppression."""
        result = calculate_seller_density_score(1, Decimal("25.00"), Decimal("-1.00"))
        assert result.suppress is False


class TestValidation:
    def test_zero_card_count_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            calculate_seller_density_score(0, Decimal("10.00"), Decimal("0"))
