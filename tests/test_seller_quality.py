"""Tests for Seller Quality Floor (Section 5)."""

from __future__ import annotations

from decimal import Decimal

from src.config import settings
from src.engine.seller_quality import check_seller_quality


def test_check_seller_quality_passes_at_exact_thresholds() -> None:
    """Section 5: rating and sales thresholds are inclusive floors."""
    result = check_seller_quality(
        rating=settings.MIN_SELLER_RATING,
        sale_count=settings.MIN_SELLER_SALES,
    )
    assert result is True


def test_check_seller_quality_rejects_rating_below_floor() -> None:
    """Section 5: seller rating below 97% must be rejected."""
    low_rating = settings.MIN_SELLER_RATING - Decimal("0.1")
    result = check_seller_quality(
        rating=low_rating,
        sale_count=settings.MIN_SELLER_SALES,
    )
    assert result is False


def test_check_seller_quality_rejects_sale_count_below_floor() -> None:
    """Section 5: seller sale count below 100 must be rejected."""
    result = check_seller_quality(
        rating=settings.MIN_SELLER_RATING,
        sale_count=settings.MIN_SELLER_SALES - 1,
    )
    assert result is False

