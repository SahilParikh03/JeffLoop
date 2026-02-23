"""
Comprehensive tests for SignalGenerator (Layer 4).

Tests the orchestrator pipeline that calls real engine modules:
- Variant check, seller quality, condition mapping
- Net profit, velocity score, maturity decay
- Rotation risk, headache score
- Telegram delivery integration

Minimum 9 test cases, each testing a specific filter stage.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.models.base import Base
from src.models.card_metadata import CardMetadata
from src.models.market_price import MarketPrice
from src.models.user_profile import UserProfile
from src.signals.generator import SignalGenerator
from src.signals.telegram import TelegramNotifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db():
    """Create in-memory SQLite async database for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        # Create only needed tables (SQLite doesn't support ARRAY, so skip user_profiles for full creation)
        await conn.run_sync(MarketPrice.__table__.create, checkfirst=True)
        await conn.run_sync(CardMetadata.__table__.create, checkfirst=True)
        # Manually create user_profiles without ARRAY columns for testing
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id TEXT PRIMARY KEY,
                telegram_chat_id INTEGER,
                country TEXT,
                seller_level TEXT,
                min_profit_threshold REAL,
                min_headache_score INTEGER,
                currency TEXT,
                forwarder_receiving_fee REAL,
                forwarder_consolidation_fee REAL,
                insurance_rate REAL,
                use_forwarder BOOLEAN,
                created_at TEXT
            )
        """))
        # price_history table required by engine/price_trend.py (Phase 2)
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS price_history (
                id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL,
                source TEXT NOT NULL,
                price_usd REAL,
                price_eur REAL,
                recorded_at TEXT NOT NULL
            )
        """))

    SessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    yield SessionLocal

    await engine.dispose()


@pytest.fixture
def mock_notifier():
    """Create a mock TelegramNotifier."""
    notifier = AsyncMock(spec=TelegramNotifier)
    notifier.send_batch_signals = AsyncMock(return_value=2)
    return notifier


@pytest.fixture
async def generator(test_db, mock_notifier):
    """Create SignalGenerator with mocked notifier."""
    return SignalGenerator(session_factory=test_db, notifier=mock_notifier)


# ---------------------------------------------------------------------------
# Test Cases (9+ required)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_1_full_pipeline_happy_path(generator, test_db):
    """Test 1: Full pipeline happy path — card passes all filters → signal generated."""
    # Setup with realistic arbitrage pricing (TCG >> CM)
    async with test_db() as session:
        price = MarketPrice(
            card_id="sv1-25",
            source="justtcg",
            price_usd=Decimal("100.00"),  # Sell price on TCG
            price_eur=Decimal("40.00"),   # Buy price on CM (big spread!)
            condition="NM",
        )
        session.add(price)
        await session.commit()

    # Execute
    signals = await generator.scan_for_signals()

    # Assert
    assert len(signals) > 0
    signal = signals[0]
    assert signal["card_id"] == "sv1-25"
    assert isinstance(signal["net_profit"], Decimal)
    assert isinstance(signal["margin_pct"], Decimal)
    assert "velocity_tier" in signal
    assert "headache_tier" in signal
    assert signal["audit_snapshot"] is not None


@pytest.mark.asyncio
async def test_2_variant_mismatch_filtered(generator, test_db):
    """Test 2: Variant mismatch → card filtered out."""
    # Mock validate_variant to return VARIANT_MISMATCH
    with patch(
        "src.signals.generator.validate_variant",
        return_value="VARIANT_MISMATCH",
    ):
        async with test_db() as session:
            price = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: no signals generated
        assert len(signals) == 0


@pytest.mark.asyncio
async def test_3_seller_below_threshold_filtered(generator, test_db):
    """Test 3: Seller below threshold → card filtered out."""
    # Mock check_seller_quality to return False
    with patch(
        "src.signals.generator.check_seller_quality", return_value=False
    ):
        async with test_db() as session:
            price = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: no signals generated
        assert len(signals) == 0


@pytest.mark.asyncio
async def test_4_poor_condition_filtered(generator, test_db):
    """Test 4: Poor condition → card filtered out."""
    # Mock map_condition to raise ValueError
    with patch(
        "src.signals.generator.map_condition",
        side_effect=ValueError("Poor condition"),
    ):
        async with test_db() as session:
            price = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: no signals generated
        assert len(signals) == 0


@pytest.mark.asyncio
async def test_5_below_profit_threshold_filtered(generator, test_db):
    """Test 5: Below profit threshold → card filtered out."""
    # Mock calculate_net_profit to return low profit
    with patch(
        "src.signals.generator.calculate_net_profit",
        return_value={
            "net_profit": Decimal("1.00"),  # Below default $5 threshold
            "margin_pct": Decimal("5.00"),
            "revenue": Decimal("50.00"),
            "tcg_fees": Decimal("10.00"),
            "customs": Decimal("0.00"),
            "shipping": Decimal("15.00"),
        },
    ):
        async with test_db() as session:
            price = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: no signals generated
        assert len(signals) == 0


@pytest.mark.asyncio
async def test_6_rotation_danger_filtered(generator, test_db):
    """Test 6: Rotation DANGER → card filtered out."""
    # Mock check_rotation_risk to return DANGER
    with patch(
        "src.signals.generator.check_rotation_risk",
        return_value={
            "at_risk": True,
            "risk_level": "DANGER",
            "months_until_rotation": 1,
            "rotation_date": date(2026, 4, 10),
        },
    ):
        async with test_db() as session:
            price = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: no signals generated
        assert len(signals) == 0


@pytest.mark.asyncio
async def test_7_one_bad_card_does_not_crash_scan(generator, test_db):
    """Test 7: One bad card doesn't crash scan — continues processing."""
    # Setup: insert two prices, mock one to raise exception
    with patch(
        "src.signals.generator.validate_variant",
        side_effect=["MATCH", Exception("Database error")],
    ):
        async with test_db() as session:
            price1 = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("50.00"),
                price_eur=Decimal("45.00"),
            )
            price2 = MarketPrice(
                card_id="sv2-30",
                source="justtcg",
                price_usd=Decimal("60.00"),
                price_eur=Decimal("55.00"),
            )
            session.add_all([price1, price2])
            await session.commit()

        # Patch other filters to pass
        with patch(
            "src.signals.generator.check_seller_quality", return_value=True
        ):
            with patch(
                "src.signals.generator.map_condition"
            ) as mock_cond:
                mock_cond.return_value = MagicMock(
                    price_multiplier=Decimal("1.0")
                )

                signals = await generator.scan_for_signals()

                # Assert: scan didn't crash (still a list, not exception)
                assert isinstance(signals, list)


@pytest.mark.asyncio
async def test_8_signals_sorted_by_profit_descending(generator, test_db):
    """Test 8: Signals sorted by net_profit descending."""
    # Mock calculate_net_profit to return controlled profits
    profits = [Decimal("15.00"), Decimal("30.00"), Decimal("10.00")]
    profit_iter = iter(profits)

    def mock_profit(*args, **kwargs):
        profit = next(profit_iter)
        return {
            "net_profit": profit,
            "margin_pct": Decimal("20.00"),
            "revenue": Decimal("100.00"),
            "tcg_fees": Decimal("10.00"),
            "customs": Decimal("0.00"),
            "shipping": Decimal("15.00"),
        }

    with patch(
        "src.signals.generator.calculate_net_profit", side_effect=mock_profit
    ):
        async with test_db() as session:
            for i in range(3):
                price = MarketPrice(
                    card_id=f"sv1-{i}",
                    source="justtcg",
                    price_usd=Decimal("50.00"),
                    price_eur=Decimal("45.00"),
                )
                session.add(price)
            await session.commit()

        signals = await generator.scan_for_signals()

        # Assert: sorted descending by net_profit
        assert len(signals) == 3
        profits_result = [float(s["net_profit"]) for s in signals]
        assert profits_result == [30.0, 15.0, 10.0]


@pytest.mark.asyncio
async def test_9_run_and_notify_sends_telegram(generator, test_db, mock_notifier):
    """Test 9: run_and_notify calls telegram for each user."""
    # Setup (suppress structlog output for this test)
    async with test_db() as session:
        price = MarketPrice(
            card_id="sv1-25",
            source="justtcg",
            price_usd=Decimal("100.00"),  # Profitable spread
            price_eur=Decimal("40.00"),
        )
        session.add(price)
        await session.commit()

        # Create user manually for testing (simulating UserProfile ORM object)
        user = MagicMock()
        user.id = "user-1"
        user.country = "US"
        user.telegram_chat_id = 12345
        user.min_profit_threshold = Decimal("5.00")

    # Execute
    total = await generator.run_and_notify([user])

    # Assert: notifier was called
    mock_notifier.send_batch_signals.assert_called_once()
    args = mock_notifier.send_batch_signals.call_args[0]
    assert args[0] == 12345  # chat_id
    assert isinstance(args[1], list)  # signals
    assert total == 2  # Mock returns 2


@pytest.mark.asyncio
async def test_10_run_and_notify_filters_by_threshold(
    generator, test_db, mock_notifier
):
    """Test 10: run_and_notify filters signals by user's min_profit_threshold."""
    # Mock different profit levels
    profits = [Decimal("3.00"), Decimal("10.00")]
    profit_iter = iter(profits)

    def mock_profit(*args, **kwargs):
        profit = next(profit_iter)
        return {
            "net_profit": profit,
            "margin_pct": Decimal("20.00"),
            "revenue": Decimal("50.00"),
            "tcg_fees": Decimal("10.00"),
            "customs": Decimal("0.00"),
            "shipping": Decimal("15.00"),
        }

    with patch(
        "src.signals.generator.calculate_net_profit", side_effect=mock_profit
    ):
        async with test_db() as session:
            price1 = MarketPrice(
                card_id="sv1-25",
                source="justtcg",
                price_usd=Decimal("30.00"),
                price_eur=Decimal("25.00"),
            )
            price2 = MarketPrice(
                card_id="sv1-26",
                source="justtcg",
                price_usd=Decimal("60.00"),
                price_eur=Decimal("50.00"),
            )
            session.add_all([price1, price2])
            await session.commit()

        user = MagicMock()
        user.id = "user-1"
        user.telegram_chat_id = 12345
        user.min_profit_threshold = Decimal("5.00")

        # Execute
        await generator.run_and_notify([user])

        # Assert: only high-profit signal passed
        call_args = mock_notifier.send_batch_signals.call_args[0]
        signals = call_args[1]
        assert len(signals) == 1
        assert float(signals[0]["net_profit"]) == 10.0


@pytest.mark.asyncio
async def test_11_signal_includes_all_required_fields(generator, test_db):
    """Test 11: Signal dict contains all required fields."""
    # Setup with good pricing
    async with test_db() as session:
        meta = CardMetadata(
            card_id="sv1-25",
            name="Pikachu",
            set_code="sv1",
            set_name="Scarlet & Violet",
            card_number="25",
            regulation_mark="H",
            set_release_date=date(2023, 1, 15),
            legality_standard="Legal",
            tcgplayer_url="https://tcgplayer.com/...",
            cardmarket_url="https://cardmarket.com/...",
        )
        price = MarketPrice(
            card_id="sv1-25",
            source="justtcg",
            price_usd=Decimal("100.00"),  # Good spread
            price_eur=Decimal("40.00"),
        )
        session.add_all([meta, price])
        await session.commit()

    # Execute
    signals = await generator.scan_for_signals()

    # Assert
    assert len(signals) > 0
    signal = signals[0]
    required_fields = [
        "card_id",
        "card_name",
        "net_profit",
        "margin_pct",
        "velocity_tier",
        "headache_tier",
        "maturity_decay",
        "rotation_risk",
        "condition",
        "cm_price_eur",
        "tcg_price_usd",
        "tcgplayer_url",
        "cardmarket_url",
        "audit_snapshot",
    ]
    for field in required_fields:
        assert field in signal, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_bundle_logic_disabled_passes_sds_1(generator, test_db):
    """When ENABLE_BUNDLE_LOGIC is False, SDS defaults to 1 (single-card) and signal is not suppressed."""
    from src.config import settings

    async with test_db() as session:
        price = MarketPrice(
            card_id="sv1-25",
            source="justtcg",
            price_usd=Decimal("100.00"),
            price_eur=Decimal("40.00"),
        )
        session.add(price)
        await session.commit()

    with patch.object(settings, "ENABLE_BUNDLE_LOGIC", False):
        signals = await generator.scan_for_signals()

    assert len(signals) > 0
    assert signals[0]["bundle_tier"] == "single_card"
    assert signals[0]["audit_snapshot"]["scores"]["bundle_sds"] == "1"


@pytest.mark.asyncio
async def test_12_audit_snapshot_complete(generator, test_db):
    """Test 12: Audit snapshot has complete fee/score breakdown."""
    # Setup with good pricing
    async with test_db() as session:
        price = MarketPrice(
            card_id="sv1-25",
            source="justtcg",
            price_usd=Decimal("100.00"),  # Good spread
            price_eur=Decimal("40.00"),
        )
        session.add(price)
        await session.commit()

    # Execute
    signals = await generator.scan_for_signals()

    # Assert
    assert len(signals) > 0
    audit = signals[0]["audit_snapshot"]
    assert "prices" in audit or "raw_prices" in audit
    assert "fees" in audit
    assert "scores" in audit
    assert audit["fees"]["revenue"] is not None
    assert audit["scores"]["velocity"] is not None
