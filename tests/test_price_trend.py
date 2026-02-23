"""
Tests for engine/price_trend.py — 7-Day Price Trend Calculator.

Uses aiosqlite in-memory database so no Postgres is required.
Only the price_history table is created (via its own MetaData) so that
PostgreSQL-only types in other models (JSONB, ARRAY) do not block SQLite.
All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.engine.price_trend import TREND_WINDOW_DAYS, get_7day_trend
from src.models.price_history import PriceHistory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _days_ago(n: float) -> datetime:
    return _now() - timedelta(days=n)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """In-memory SQLite database with only the price_history table."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Build an isolated MetaData that only contains price_history so that
    # PostgreSQL-only types (JSONB, UUID dialect type, ARRAY) in other models
    # do not cause SQLite compilation errors.
    isolated_meta = MetaData()
    PriceHistory.__table__.to_metadata(isolated_meta)

    async with engine.begin() as conn:
        await conn.run_sync(isolated_meta.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _insert_row(
    session: AsyncSession,
    card_id: str,
    source: str,
    price_usd: Decimal | None,
    price_eur: Decimal | None,
    recorded_at: datetime,
) -> None:
    # Supply the UUID explicitly so SQLite doesn't need gen_random_uuid().
    row = PriceHistory(
        id=str(uuid.uuid4()),
        card_id=card_id,
        source=source,
        price_usd=price_usd,
        price_eur=price_eur,
        recorded_at=recorded_at,
    )
    session.add(row)
    await session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_data_returns_zero(db_session: AsyncSession) -> None:
    """No price_history rows → Decimal('0.00')."""
    result = await get_7day_trend("sv3-1", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_single_data_point_returns_zero(db_session: AsyncSession) -> None:
    """Single row is not enough for regression → Decimal('0.00')."""
    await _insert_row(db_session, "sv3-1", "justtcg", Decimal("50.00"), None, _days_ago(1))
    result = await get_7day_trend("sv3-1", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_two_points_rising_price(db_session: AsyncSession) -> None:
    """Two points where price doubled → positive trend."""
    await _insert_row(db_session, "sv3-2", "justtcg", Decimal("10.00"), None, _days_ago(2))
    await _insert_row(db_session, "sv3-2", "justtcg", Decimal("20.00"), None, _days_ago(1))
    result = await get_7day_trend("sv3-2", "justtcg", db_session)
    assert result > Decimal("0.00"), f"Expected positive trend, got {result}"


@pytest.mark.asyncio
async def test_two_points_falling_price(db_session: AsyncSession) -> None:
    """Two points where price halved → negative trend."""
    await _insert_row(db_session, "sv3-3", "justtcg", Decimal("20.00"), None, _days_ago(2))
    await _insert_row(db_session, "sv3-3", "justtcg", Decimal("10.00"), None, _days_ago(1))
    result = await get_7day_trend("sv3-3", "justtcg", db_session)
    assert result < Decimal("0.00"), f"Expected negative trend, got {result}"


@pytest.mark.asyncio
async def test_seven_points_stable_near_zero(db_session: AsyncSession) -> None:
    """Seven points at nearly the same price → trend near 0."""
    base_price = Decimal("50.00")
    for i in range(7):
        await _insert_row(
            db_session, "sv3-4", "justtcg",
            base_price, None,
            _days_ago(7 - i),
        )
    result = await get_7day_trend("sv3-4", "justtcg", db_session)
    assert abs(result) < Decimal("0.01"), f"Expected near-zero trend, got {result}"


@pytest.mark.asyncio
async def test_seven_points_strong_uptrend(db_session: AsyncSession) -> None:
    """Seven points with strong linear uptrend → positive Decimal."""
    for i in range(7):
        price = Decimal(str(10 + i * 5))   # $10, $15, $20 … $40
        await _insert_row(
            db_session, "sv3-5", "justtcg",
            price, None,
            _days_ago(7 - i),
        )
    result = await get_7day_trend("sv3-5", "justtcg", db_session)
    assert result > Decimal("0.00"), f"Expected positive trend, got {result}"


@pytest.mark.asyncio
async def test_seven_points_strong_downtrend_below_falling_knife(
    db_session: AsyncSession,
) -> None:
    """
    Seven points falling from $50 to near $0 over 6 days.

    Daily rate ≈ -(50/6)/25 ≈ -0.33, which is well below the
    FALLING_KNIFE_THRESHOLD of -0.10.
    """
    for i in range(7):
        price = Decimal(str(max(1, 50 - i * 8)))  # $50, $42, $34, $26, $18, $10, $2
        await _insert_row(
            db_session, "sv3-6", "justtcg",
            price, None,
            _days_ago(7 - i),
        )
    result = await get_7day_trend("sv3-6", "justtcg", db_session)
    assert result < Decimal("-0.10"), (
        f"Expected trend below falling-knife threshold (-0.10), got {result}"
    )


@pytest.mark.asyncio
async def test_data_older_than_7_days_excluded(db_session: AsyncSession) -> None:
    """
    Row recorded 8 days ago is outside the window and must be excluded.
    Only the single row within window is present → insufficient → 0.00.
    """
    await _insert_row(db_session, "sv3-7", "justtcg", Decimal("5.00"), None, _days_ago(8))
    await _insert_row(db_session, "sv3-7", "justtcg", Decimal("50.00"), None, _days_ago(1))
    # Only 1 usable row within 7-day window → return 0.00
    result = await get_7day_trend("sv3-7", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_only_matching_card_id_used(db_session: AsyncSession) -> None:
    """Rows for a different card_id must not influence the result."""
    # Insert a big falling trend for a different card
    for i in range(7):
        price = Decimal(str(max(1, 100 - i * 15)))
        await _insert_row(
            db_session, "sv3-DECOY", "justtcg",
            price, None,
            _days_ago(7 - i),
        )
    # Our target card has no rows → should return 0
    result = await get_7day_trend("sv3-8", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_only_matching_source_used(db_session: AsyncSession) -> None:
    """Rows for a different source must not influence the result."""
    # Insert a big uptrend for a different source
    for i in range(7):
        price = Decimal(str(10 + i * 10))
        await _insert_row(
            db_session, "sv3-9", "poketrace",
            price, None,
            _days_ago(7 - i),
        )
    # Our target source (justtcg) has no rows
    result = await get_7day_trend("sv3-9", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_price_eur_fallback_when_usd_is_none(db_session: AsyncSession) -> None:
    """When price_usd is None, price_eur must be used for regression."""
    await _insert_row(
        db_session, "sv3-10", "justtcg",
        None, Decimal("10.00"),
        _days_ago(2),
    )
    await _insert_row(
        db_session, "sv3-10", "justtcg",
        None, Decimal("20.00"),
        _days_ago(1),
    )
    result = await get_7day_trend("sv3-10", "justtcg", db_session)
    assert result > Decimal("0.00"), (
        f"Expected positive trend using EUR fallback, got {result}"
    )


@pytest.mark.asyncio
async def test_division_by_zero_protection_all_same_price(
    db_session: AsyncSession,
) -> None:
    """
    When all prices are exactly equal the slope is 0, avg_price != 0,
    and the result must be 0.00 (not a ZeroDivisionError).
    """
    for i in range(5):
        await _insert_row(
            db_session, "sv3-11", "justtcg",
            Decimal("25.00"), None,
            _days_ago(5 - i),
        )
    result = await get_7day_trend("sv3-11", "justtcg", db_session)
    assert result == Decimal("0.00")


@pytest.mark.asyncio
async def test_large_price_swing_edge_case(db_session: AsyncSession) -> None:
    """
    Extreme price swing ($1 → $1000) over 2 days must not raise
    and must return a large positive number.
    """
    await _insert_row(db_session, "sv3-12", "justtcg", Decimal("1.00"), None, _days_ago(2))
    await _insert_row(db_session, "sv3-12", "justtcg", Decimal("1000.00"), None, _days_ago(1))
    result = await get_7day_trend("sv3-12", "justtcg", db_session)
    assert result > Decimal("1.0"), f"Expected large positive trend, got {result}"


@pytest.mark.asyncio
async def test_mixed_null_nonnull_prices(db_session: AsyncSession) -> None:
    """
    Rows with both prices null are skipped; remaining rows drive the trend.
    With 3 valid rows (rising) out of 5, result should be positive.
    """
    await _insert_row(db_session, "sv3-13", "justtcg", None, None, _days_ago(5))   # skipped
    await _insert_row(db_session, "sv3-13", "justtcg", Decimal("10.00"), None, _days_ago(4))
    await _insert_row(db_session, "sv3-13", "justtcg", None, None, _days_ago(3))   # skipped
    await _insert_row(db_session, "sv3-13", "justtcg", Decimal("20.00"), None, _days_ago(2))
    await _insert_row(db_session, "sv3-13", "justtcg", Decimal("30.00"), None, _days_ago(1))
    result = await get_7day_trend("sv3-13", "justtcg", db_session)
    assert result > Decimal("0.00"), f"Expected positive trend from valid rows, got {result}"


@pytest.mark.asyncio
async def test_decimal_precision_not_float_artifacts(db_session: AsyncSession) -> None:
    """
    Result must be a Decimal (not float) and must have reasonable precision
    — no floating-point noise like 0.333333333333...7.
    """
    for i in range(7):
        price = Decimal(str(100 + i * 3))
        await _insert_row(
            db_session, "sv3-14", "justtcg",
            price, None,
            _days_ago(7 - i),
        )
    result = await get_7day_trend("sv3-14", "justtcg", db_session)
    assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
    # Decimal places should be ≤ 6 (rounded in implementation)
    sign, digits, exponent = result.as_tuple()
    assert exponent >= -6, f"Too many decimal places in {result}"
