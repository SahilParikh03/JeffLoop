"""
TCG Radar — Currency Conversion with Pessimistic Buffer (Section 4.1)

EUR/USD conversion with a 2% buffer applied pessimistically:
- When BUYING in EUR: assume EUR is 2% more expensive than spot rate
- When SELLING in USD: assume USD is 2% weaker than spot rate

This ensures profit calculations are conservative. The buffer is
user-configurable via DEFAULT_FOREX_BUFFER in config.

All money values use Decimal — never float — to avoid rounding errors
in financial calculations.

get_current_forex_rate() is async and uses a live API with a 15-minute
in-memory cache. Falls back to settings.EUR_USD_RATE on any failure or
when no API key is configured.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Default 2% buffer from spec Section 4.1
_DEFAULT_BUFFER = Decimal("0.02")

# Module-level cache (in-memory, not persisted across restarts)
_forex_cache: dict[str, Any] = {}


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


async def get_current_forex_rate() -> Decimal:
    """
    Return the current EUR/USD exchange rate.

    Uses live API with 15-minute in-memory cache.
    Falls back to settings.EUR_USD_RATE on any failure or missing API key.

    Returns Decimal rounded to 6 decimal places, with 2% pessimistic buffer already applied.
    """
    from src.config import settings
    import httpx
    from datetime import datetime, timezone

    # If no API key configured, use static rate directly
    if not settings.EXCHANGERATE_API_KEY:
        logger.debug(
            "forex_no_api_key_using_static",
            rate=str(settings.EUR_USD_RATE),
            source="forex",
        )
        return settings.EUR_USD_RATE

    # Check cache freshness
    now = datetime.now(timezone.utc)
    if _forex_cache:
        age_seconds = (now - _forex_cache["fetched_at"]).total_seconds()
        if age_seconds < settings.FOREX_CACHE_TTL_SECONDS:
            logger.debug(
                "forex_cache_hit",
                rate=str(_forex_cache["rate"]),
                age_seconds=int(age_seconds),
                source="forex",
            )
            return _forex_cache["rate"]

    # Fetch from live API
    try:
        url = f"{settings.EXCHANGERATE_API_URL}/{settings.EXCHANGERATE_API_KEY}/latest/EUR"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        raw_rate = Decimal(str(data["conversion_rates"]["USD"]))
        # Apply 2% pessimistic buffer
        buffered_rate = (raw_rate * Decimal("0.98")).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

        # Update cache
        _forex_cache["rate"] = buffered_rate
        _forex_cache["fetched_at"] = now

        logger.info(
            "forex_rate_refreshed",
            raw_rate=str(raw_rate),
            buffered_rate=str(buffered_rate),
            source="forex",
        )
        return buffered_rate

    except Exception as e:
        logger.warning(
            "forex_api_failed_using_fallback",
            error=str(e),
            fallback_rate=str(settings.EUR_USD_RATE),
            source="forex",
        )
        return settings.EUR_USD_RATE
