"""
TCG Radar — 7-Day Price Trend Calculator

Computes daily price change rate from price_history for trend classification.
Used by generator.py for trend classification (Section 4.3).

Algorithm:
    1. Query price_history for (card_id, source) in the last 7 days, ASC.
    2. If fewer than 2 data points, return Decimal("0.00") — no trend data.
    3. Compute least-squares linear regression slope over (x=days, y=price).
    4. Normalize: daily_change_fraction = slope / mean(price)
    5. Return the Decimal result (e.g., -0.05 = -5%/day).

Price selection: price_usd preferred; falls back to price_eur when USD is None.
Rows where both prices are None are excluded from regression.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.price_history import PriceHistory

logger = structlog.get_logger(__name__)

# Number of days in the trend window
TREND_WINDOW_DAYS: int = 7


def _least_squares_slope(xs: list[float], ys: list[float]) -> float:
    """
    Compute the least-squares linear regression slope (dy/dx).

    Returns 0.0 if the denominator is zero (all x values identical,
    which cannot happen given distinct timestamps — but guarded anyway).

    Args:
        xs: Independent variable values (days from first point).
        ys: Dependent variable values (price).

    Returns:
        Slope as a float. 0.0 if the system is degenerate.
    """
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0.0:
        return 0.0

    return (n * sum_xy - sum_x * sum_y) / denom


async def get_7day_trend(
    card_id: str,
    source: str,
    session: AsyncSession,
) -> Decimal:
    """
    Calculate 7-day price trend as daily fractional change.

    Queries the last 7 days of price_history for the given card_id + source,
    runs a least-squares regression, and returns the normalised daily rate.

    Args:
        card_id: pokemontcg.io canonical card identifier.
        source:  Data source name (e.g. 'justtcg', 'poketrace').
        session: Async SQLAlchemy session.

    Returns:
        Daily price change as a Decimal fraction (e.g. -0.05 = -5%/day).
        Returns Decimal("0.00") when fewer than 2 usable data points exist.
    """
    cutoff: datetime = datetime.now(timezone.utc) - timedelta(days=TREND_WINDOW_DAYS)

    stmt = (
        select(PriceHistory)
        .where(
            PriceHistory.card_id == card_id,
            PriceHistory.source == source,
            PriceHistory.recorded_at >= cutoff,
        )
        .order_by(PriceHistory.recorded_at.asc())
    )

    result = await session.execute(stmt)
    rows: Sequence[PriceHistory] = result.scalars().all()

    logger.debug(
        "price_trend_query",
        card_id=card_id,
        source=source,
        rows_found=len(rows),
        cutoff=cutoff.isoformat(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # --- Build usable (x, y) pairs ---
    # x = days from the first data point (float for regression)
    # y = price_usd preferred; fallback to price_eur
    xs: list[float] = []
    ys: list[float] = []

    if not rows:
        return Decimal("0.00")

    origin: datetime = rows[0].recorded_at

    for row in rows:
        # Select price: prefer USD, fall back to EUR
        price: Decimal | None = row.price_usd if row.price_usd is not None else row.price_eur
        if price is None:
            # Skip rows where both prices are null
            continue

        # Compute x as fractional days from origin
        delta_seconds: float = (row.recorded_at - origin).total_seconds()
        x_days: float = delta_seconds / 86400.0

        xs.append(x_days)
        ys.append(float(price))

    if len(xs) < 2:
        logger.debug(
            "price_trend_insufficient_data",
            card_id=card_id,
            source=source,
            usable_points=len(xs),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return Decimal("0.00")

    # --- Compute slope (price units per day) ---
    slope: float = _least_squares_slope(xs, ys)

    # --- Normalise by average price → fractional daily change ---
    avg_price: float = sum(ys) / len(ys)
    if avg_price == 0.0:
        # Division-by-zero guard: price is zero (should never happen for real cards)
        logger.warning(
            "price_trend_zero_avg_price",
            card_id=card_id,
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return Decimal("0.00")

    daily_change_fraction: float = slope / avg_price

    try:
        result_decimal = Decimal(str(round(daily_change_fraction, 6)))
    except InvalidOperation:
        result_decimal = Decimal("0.00")

    logger.debug(
        "price_trend_calculated",
        card_id=card_id,
        source=source,
        data_points=len(xs),
        slope=round(slope, 6),
        avg_price=round(avg_price, 4),
        daily_change_fraction=round(daily_change_fraction, 6),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    return result_decimal
