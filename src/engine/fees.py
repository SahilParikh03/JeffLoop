"""
TCG Radar — Platform Fee Calculator (Section 4.1.1)

Tiered platform fees for TCGPlayer, eBay, and Cardmarket.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

_TWO_DP = Decimal("0.01")


class Platform(str, Enum):
    TCGPLAYER = "tcgplayer"
    EBAY = "ebay"
    CARDMARKET = "cardmarket"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def calculate_platform_fees(price: Decimal, platform: Platform) -> Decimal:
    """
    Calculate selling platform fees for a given price.

    Formulas:
    - TCGPlayer: min(P × 0.1075, $75) + $0.30
    - eBay: P × 0.1325
    - Cardmarket: P × 0.05

    Args:
        price: The sell price (P_target).
        platform: Which marketplace.

    Returns:
        Decimal fee amount (2dp).

    Raises:
        ValueError: If price is negative.
    """
    if price < Decimal("0"):
        raise ValueError("price must be non-negative")

    if platform == Platform.TCGPLAYER:
        variable = min(price * settings.TCGPLAYER_FEE_RATE, settings.TCGPLAYER_FEE_CAP)
        fee = _quantize(variable + settings.TCGPLAYER_FIXED_FEE)
    elif platform == Platform.EBAY:
        fee = _quantize(price * settings.EBAY_FEE_RATE)
    elif platform == Platform.CARDMARKET:
        fee = _quantize(price * settings.CARDMARKET_PRO_FEE_RATE)
    else:
        raise ValueError(f"Unsupported platform: {platform}")

    logger.debug(
        "platform_fee_calculated",
        price=str(price),
        platform=platform.value,
        fee=str(fee),
        source="fees",
    )
    return fee
