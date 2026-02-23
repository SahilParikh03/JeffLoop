"""
TCG Radar - Seller Quality Floor (Section 5)

Reject listings from low-trust sellers before fee/profit calculations.
Both thresholds must pass:
- rating >= MIN_SELLER_RATING
- sale_count >= MIN_SELLER_SALES
"""

from __future__ import annotations

from decimal import Decimal

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def check_seller_quality(rating: Decimal, sale_count: int) -> bool:
    """
    Validate seller against the quality floor from configuration.

    Args:
        rating: Seller rating percentage (for example, Decimal("97.5")).
        sale_count: Lifetime completed sale count.

    Returns:
        True if both rating and sale_count meet minimum thresholds, else False.
    """
    failed_reasons: list[str] = []

    if rating < settings.MIN_SELLER_RATING:
        failed_reasons.append("rating_below_minimum")

    if sale_count < settings.MIN_SELLER_SALES:
        failed_reasons.append("sale_count_below_minimum")

    if failed_reasons:
        logger.warning(
            "seller_quality_rejected",
            rating=str(rating),
            sale_count=sale_count,
            min_rating=str(settings.MIN_SELLER_RATING),
            min_sales=settings.MIN_SELLER_SALES,
            reasons=failed_reasons,
        )
        return False

    return True

