"""
TCG Radar - Sales Velocity Scorer (Section 4.2)
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog

from src.config import VelocityTier, settings

logger = structlog.get_logger(__name__)

_TWO_DP = Decimal("0.01")
_ZERO = Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def calculate_velocity_score(
    daily_sales: Decimal,
    threshold_low: Decimal | None = None,
    threshold_high: Decimal | None = None,
) -> tuple[Decimal, int]:
    """
    Classify daily sales velocity into tier 1/2/3 and return (score, tier).

    Tier rules:
    - daily_sales > high -> tier 1 (hot)
    - low < daily_sales <= high -> tier 2 (moderate)
    - daily_sales <= low -> tier 3 (slow)
    """
    if daily_sales < _ZERO:
        raise ValueError("daily_sales must be non-negative")

    low = threshold_low if threshold_low is not None else settings.VELOCITY_TIER_2_FLOOR
    high = threshold_high if threshold_high is not None else settings.VELOCITY_TIER_1_FLOOR
    if low >= high:
        raise ValueError("threshold_low must be less than threshold_high")

    velocity_score = _quantize(daily_sales)
    if daily_sales > high:
        tier = 1
        tier_label = VelocityTier.LIQUID_GOLD
    elif daily_sales > low:
        tier = 2
        tier_label = VelocityTier.STANDARD_FLIP
    else:
        tier = 3
        tier_label = VelocityTier.BAGHOLDER_RISK

    logger.info(
        "velocity_classified",
        daily_sales=str(velocity_score),
        threshold_low=str(low),
        threshold_high=str(high),
        tier=tier,
        velocity_tier=tier_label.value,
    )
    return velocity_score, tier

