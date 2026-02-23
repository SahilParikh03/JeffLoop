"""
TCG Radar — Effective Price Calculator (Section 4.1)

Computes the effective buy price (COGS in USD) and condition-adjusted sell price.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog

from src.config import settings
from src.utils.condition_map import CardmarketGrade, ConditionMapping, map_condition
from src.utils.forex import convert_eur_to_usd

logger = structlog.get_logger(__name__)

_TWO_DP = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def calculate_effective_buy_price(
    listing_eur: Decimal,
    shipping_eur: Decimal,
    forex_rate: Decimal,
    forex_buffer: Decimal | None = None,
) -> Decimal:
    """
    Calculate effective buy price (COGS) in USD.

    Effective_Buy = (listing_eur + shipping_eur) × forex_rate × (1 + buffer)

    Args:
        listing_eur: Card listing price in EUR.
        shipping_eur: Shipping cost in EUR.
        forex_rate: Spot EUR/USD exchange rate.
        forex_buffer: Pessimistic buffer (default from config: 2%).

    Returns:
        Effective buy price in USD (2dp).

    Raises:
        ValueError: If any input is negative or forex_rate is zero/negative.
    """
    if listing_eur < Decimal("0"):
        raise ValueError("listing_eur must be non-negative")
    if shipping_eur < Decimal("0"):
        raise ValueError("shipping_eur must be non-negative")
    if forex_rate <= Decimal("0"):
        raise ValueError("forex_rate must be positive")

    buffer = forex_buffer if forex_buffer is not None else settings.DEFAULT_FOREX_BUFFER
    total_eur = listing_eur + shipping_eur
    cogs_usd = convert_eur_to_usd(total_eur, forex_rate, buffer=buffer)

    logger.debug(
        "effective_buy_price_calculated",
        listing_eur=str(listing_eur),
        shipping_eur=str(shipping_eur),
        forex_rate=str(forex_rate),
        buffer=str(buffer),
        cogs_usd=str(cogs_usd),
        source="effective_price",
    )
    return cogs_usd


def calculate_condition_adjusted_sell_price(
    tcg_price_usd: Decimal,
    cardmarket_grade: CardmarketGrade,
) -> tuple[Decimal, Decimal]:
    """
    Apply condition penalty to TCGPlayer sell price.

    Cardmarket conditions are pessimistically mapped to TCGPlayer equivalents.
    A Cardmarket "Excellent" card sells as "Lightly Played" on TCGPlayer at -15%.

    Args:
        tcg_price_usd: TCGPlayer Near Mint price in USD.
        cardmarket_grade: The Cardmarket condition grade of the listing.

    Returns:
        Tuple of (adjusted_price, multiplier).
        adjusted_price = tcg_price_usd × multiplier (2dp).

    Raises:
        ValueError: If grade is POOR (signal must be suppressed).
        ValueError: If tcg_price_usd is negative.
    """
    if tcg_price_usd < Decimal("0"):
        raise ValueError("tcg_price_usd must be non-negative")

    mapping: ConditionMapping = map_condition(cardmarket_grade)
    adjusted = _quantize(tcg_price_usd * mapping.price_multiplier)

    logger.debug(
        "condition_adjusted_sell_price",
        tcg_price_usd=str(tcg_price_usd),
        cardmarket_grade=cardmarket_grade.value,
        tcgplayer_grade=mapping.tcgplayer_grade.value,
        multiplier=str(mapping.price_multiplier),
        adjusted_price=str(adjusted),
        source="effective_price",
    )
    return adjusted, mapping.price_multiplier
