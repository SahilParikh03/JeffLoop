"""
TCG Radar — Trend-Adjusted Velocity (Section 4.3)

Falling Knife Filter: Detects cards with high sales velocity driven by
panic selling rather than genuine demand.

Classification matrix:
    |              | Price Rising/Flat  | Price Falling (< -10%/day) |
    |:-------------|:-------------------|:---------------------------|
    | High V (≥1.5)| MOMENTUM           | LIQUIDATION (SUPPRESS)     |
    | Low V (<1.5) | STABLE             | DECLINING                  |

Only LIQUIDATION signals are suppressed.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class TrendClassification(str, Enum):
    """Section 4.3 — Four-cell trend classification."""
    MOMENTUM = "momentum"           # High V + rising/flat price
    LIQUIDATION = "liquidation"     # High V + falling price (SUPPRESS)
    STABLE = "stable"               # Low V + rising/flat price
    DECLINING = "declining"         # Low V + falling price


def classify_trend(
    velocity_score: Decimal,
    price_trend_daily: Decimal,
    velocity_threshold: Decimal | None = None,
    falling_knife_threshold: Decimal | None = None,
) -> tuple[TrendClassification, bool]:
    """
    Classify a card's trend using velocity × price-trend matrix.

    Args:
        velocity_score: V_s (sales velocity score).
        price_trend_daily: Daily price change as a decimal (e.g., -0.15 = -15%/day).
        velocity_threshold: Override for high-velocity cutoff (default: VELOCITY_TIER_1_FLOOR).
        falling_knife_threshold: Override for falling knife cutoff (default: FALLING_KNIFE_THRESHOLD).

    Returns:
        Tuple of (classification, suppress).
        suppress=True ONLY for LIQUIDATION (high velocity + falling price).
    """
    v_thresh = velocity_threshold if velocity_threshold is not None else settings.VELOCITY_TIER_1_FLOOR
    fk_thresh = falling_knife_threshold if falling_knife_threshold is not None else settings.FALLING_KNIFE_THRESHOLD

    high_velocity = velocity_score >= v_thresh
    falling_price = price_trend_daily <= fk_thresh

    if high_velocity and falling_price:
        classification = TrendClassification.LIQUIDATION
        suppress = True
    elif high_velocity and not falling_price:
        classification = TrendClassification.MOMENTUM
        suppress = False
    elif not high_velocity and falling_price:
        classification = TrendClassification.DECLINING
        suppress = False
    else:
        classification = TrendClassification.STABLE
        suppress = False

    logger.debug(
        "trend_classified",
        velocity_score=str(velocity_score),
        price_trend_daily=str(price_trend_daily),
        classification=classification.value,
        suppress=suppress,
        source="trend",
    )
    return classification, suppress
