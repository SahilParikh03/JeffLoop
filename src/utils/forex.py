"""
TCG Radar — Currency Conversion with Pessimistic Buffer (Section 4.1)

EUR/USD conversion with a 2% buffer applied pessimistically:
- When BUYING in EUR: assume EUR is 2% more expensive than spot rate
- When SELLING in USD: assume USD is 2% weaker than spot rate

This ensures profit calculations are conservative. The buffer is
user-configurable via DEFAULT_FOREX_BUFFER in config.

All money values use Decimal — never float — to avoid rounding errors
in financial calculations.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog

logger = structlog.get_logger(__name__)

# Default 2% buffer from spec Section 4.1
_DEFAULT_BUFFER = Decimal("0.02")


def convert_eur_to_usd(
    amount_eur: Decimal,
    rate: Decimal,
    buffer: Decimal = _DEFAULT_BUFFER,
) -> Decimal:
    """
    Convert EUR to USD with pessimistic buffer.

    When buying in EUR (to resell in USD), the buffer makes the EUR cost
    appear 2% higher than spot. This is pessimistic because it increases
    our estimated cost basis.

    Args:
        amount_eur: Amount in EUR.
        rate: Spot EUR/USD exchange rate (e.g., 1.08 means 1 EUR = 1.08 USD).
        buffer: Pessimistic buffer applied to the rate (default 2%).

    Returns:
        Amount in USD after applying the pessimistic buffer.

    Examples:
        >>> convert_eur_to_usd(Decimal("100"), Decimal("1.08"))
        Decimal('110.16')  # 100 × 1.08 × 1.02 = 110.16
    """
    if amount_eur < Decimal("0"):
        raise ValueError(f"amount_eur must be non-negative, got {amount_eur}")

    # Pessimistic: EUR costs MORE than spot when we're buying
    buffered_rate = rate * (Decimal("1") + buffer)
    result = (amount_eur * buffered_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    logger.debug(
        "forex_eur_to_usd",
        amount_eur=str(amount_eur),
        spot_rate=str(rate),
        buffer=str(buffer),
        buffered_rate=str(buffered_rate),
        result_usd=str(result),
    )
    return result


def convert_usd_to_eur(
    amount_usd: Decimal,
    rate: Decimal,
    buffer: Decimal = _DEFAULT_BUFFER,
) -> Decimal:
    """
    Convert USD to EUR with pessimistic buffer.

    When selling in USD (to compare against EUR buy price), the buffer
    makes the USD value appear 2% weaker. This is pessimistic because
    it decreases our estimated revenue.

    Args:
        amount_usd: Amount in USD.
        rate: Spot EUR/USD exchange rate (e.g., 1.08 means 1 EUR = 1.08 USD).
        buffer: Pessimistic buffer applied to the rate (default 2%).

    Returns:
        Amount in EUR after applying the pessimistic buffer.

    Examples:
        >>> convert_usd_to_eur(Decimal("108"), Decimal("1.08"))
        Decimal('90.83')  # 108 / (1.08 × 1.02) = 108 / 1.1016 ≈ 98.04
    """
    if amount_usd < Decimal("0"):
        raise ValueError(f"amount_usd must be non-negative, got {amount_usd}")

    if rate <= Decimal("0"):
        raise ValueError(f"rate must be positive, got {rate}")

    # Pessimistic: USD is WEAKER than spot when we're selling
    buffered_rate = rate * (Decimal("1") + buffer)
    result = (amount_usd / buffered_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    logger.debug(
        "forex_usd_to_eur",
        amount_usd=str(amount_usd),
        spot_rate=str(rate),
        buffer=str(buffer),
        buffered_rate=str(buffered_rate),
        result_eur=str(result),
    )
    return result


def get_current_forex_rate() -> Decimal:
    """
    Return the current EUR/USD exchange rate from config.

    MVP: reads from EUR_USD_RATE env var / config default.
    Phase 2: will integrate with a real-time forex API.
    """
    from src.config import settings
    return settings.EUR_USD_RATE
