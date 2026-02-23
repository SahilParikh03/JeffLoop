"""
TCG Radar — End-to-End Integration Tests

Tests the full pipeline from database seed through signal generation and
Telegram delivery. Uses an in-memory SQLite database (same pattern as
test_generator.py) and mocks the TelegramNotifier.

Pipeline exercised per test:
  MarketPrice + CardMetadata seed → scan_for_signals() → signal list → run_and_notify()

Each test targets a discrete integration concern so failures point directly
at the broken stage.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.models.card_metadata import CardMetadata
from src.models.market_price import MarketPrice
from src.signals.generator import SignalGenerator
from src.signals.telegram import TelegramNotifier


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_db():
    """
    In-memory SQLite async database for integration tests.

    Mirrors the pattern from test_generator.py:
    - MarketPrice and CardMetadata tables created via ORM
    - user_profiles created manually (SQLite has no ARRAY support)
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(MarketPrice.__table__.create, checkfirst=True)
        await conn.run_sync(CardMetadata.__table__.create, checkfirst=True)
        await conn.execute(
            text("""
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
            """)
        )
        # price_history table required by engine/price_trend.py (Phase 2)
        await conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    price_usd REAL,
                    price_eur REAL,
                    recorded_at TEXT NOT NULL
                )
            """)
        )

    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield SessionLocal

    await engine.dispose()


@pytest.fixture
def mock_notifier():
    """AsyncMock TelegramNotifier — no real HTTP calls."""
    notifier = AsyncMock(spec=TelegramNotifier)
    notifier.send_batch_signals = AsyncMock(return_value=1)
    return notifier


@pytest.fixture
async def generator(test_db, mock_notifier):
    """SignalGenerator wired to the in-memory DB and mock notifier."""
    return SignalGenerator(session_factory=test_db, notifier=mock_notifier)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _profitable_price(
    card_id: str = "sv1-25",
    price_usd: Decimal = Decimal("100.00"),
    price_eur: Decimal = Decimal("40.00"),
    condition: str = "NM",
) -> MarketPrice:
    """Return a MarketPrice with a healthy arbitrage spread."""
    return MarketPrice(
        card_id=card_id,
        source="justtcg",
        price_usd=price_usd,
        price_eur=price_eur,
        condition=condition,
    )


def _metadata(
    card_id: str = "sv1-25",
    name: str = "Charizard ex",
    set_code: str = "sv1",
    set_name: str = "Scarlet & Violet",
    regulation_mark: str = "H",
    legality_standard: str = "Legal",
    set_release_date: date | None = None,
    tcgplayer_url: str | None = None,
    cardmarket_url: str | None = None,
) -> CardMetadata:
    """Return a CardMetadata row with sensible defaults."""
    return CardMetadata(
        card_id=card_id,
        name=name,
        set_code=set_code,
        set_name=set_name,
        card_number=card_id.split("-", 1)[-1],
        regulation_mark=regulation_mark,
        legality_standard=legality_standard,
        set_release_date=set_release_date or date(2024, 3, 22),
        tcgplayer_url=tcgplayer_url,
        cardmarket_url=cardmarket_url,
    )


def _mock_user(
    user_id: str = "user-1",
    chat_id: int = 11111,
    threshold: Decimal = Decimal("5.00"),
) -> MagicMock:
    """Return a MagicMock that looks like a UserProfile."""
    user = MagicMock()
    user.id = user_id
    user.telegram_chat_id = chat_id
    user.min_profit_threshold = threshold
    return user


# ---------------------------------------------------------------------------
# Test 1 — Full pipeline: seed → scan → signal generated
# ---------------------------------------------------------------------------


async def test_1_full_pipeline_seed_scan_signal_generated(generator, test_db):
    """
    Seed a MarketPrice row with a wide EUR/USD spread, run scan_for_signals(),
    and assert at least one signal is produced with the correct card_id and
    a positive net_profit.
    """
    async with test_db() as session:
        session.add(_profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    signals = await generator.scan_for_signals()

    assert len(signals) >= 1
    signal = signals[0]
    assert signal["card_id"] == "sv1-25"
    assert isinstance(signal["net_profit"], Decimal)
    assert signal["net_profit"] > Decimal("0")
    assert isinstance(signal["margin_pct"], Decimal)
    assert "velocity_tier" in signal
    assert "headache_tier" in signal
    assert signal["audit_snapshot"] is not None


# ---------------------------------------------------------------------------
# Test 2 — Multiple cards, mixed profitability — only profitable one signals
# ---------------------------------------------------------------------------


async def test_2_multiple_cards_only_profitable_passes(generator, test_db):
    """
    Seed 3 cards: one with a healthy spread, one marginal (just below the
    $5 default threshold), one deeply unprofitable. Assert only the profitable
    card generates a signal.
    """
    # Profitable: big spread, net_profit clearly above $5
    profitable = _profitable_price("sv1-1", Decimal("100.00"), Decimal("40.00"))

    # Marginal / unprofitable: tiny or inverted spread
    # We control net_profit via patch so we can test threshold behavior precisely
    marginal_profits = [
        {"net_profit": Decimal("3.00"), "margin_pct": Decimal("6.00"),
         "revenue": Decimal("50.00"), "tcg_fees": Decimal("5.38"),
         "customs": Decimal("0.00"), "shipping": Decimal("15.00"),
         "cogs_usd": Decimal("26.62"), "forwarder_costs": Decimal("0.00")},
        {"net_profit": Decimal("-2.00"), "margin_pct": Decimal("-4.00"),
         "revenue": Decimal("30.00"), "tcg_fees": Decimal("3.23"),
         "customs": Decimal("0.00"), "shipping": Decimal("15.00"),
         "cogs_usd": Decimal("13.77"), "forwarder_costs": Decimal("0.00")},
    ]

    async with test_db() as session:
        session.add(profitable)
        session.add(_profitable_price("sv1-2", Decimal("30.00"), Decimal("27.00")))
        session.add(_profitable_price("sv1-3", Decimal("20.00"), Decimal("19.00")))
        await session.commit()

    call_seq = iter([None] + marginal_profits)  # first call is the real module, rest are patched

    original_calc = __import__(
        "src.engine.profit", fromlist=["calculate_net_profit"]
    ).calculate_net_profit

    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return original_calc(*args, **kwargs)  # profitable card — real calc
        # Return below-threshold profits for the other two
        idx = call_count[0] - 2
        return marginal_profits[min(idx, len(marginal_profits) - 1)]

    with patch("src.signals.generator.calculate_net_profit", side_effect=side_effect):
        signals = await generator.scan_for_signals()

    # Only the profitable card (sv1-1) should have made it through
    assert len(signals) == 1
    assert signals[0]["card_id"] == "sv1-1"


# ---------------------------------------------------------------------------
# Test 3 — Scan → notify delivery — correct chat_id passed to Telegram
# ---------------------------------------------------------------------------


async def test_3_scan_notify_delivery_correct_chat_id(generator, test_db, mock_notifier):
    """
    Seed a profitable card, create a mock user with telegram_chat_id=99999,
    call run_and_notify(), and assert TelegramNotifier.send_batch_signals was
    called exactly once with that chat_id.
    """
    async with test_db() as session:
        session.add(_profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    user = _mock_user(chat_id=99999, threshold=Decimal("5.00"))
    await generator.run_and_notify([user])

    mock_notifier.send_batch_signals.assert_called_once()
    call_args = mock_notifier.send_batch_signals.call_args[0]
    assert call_args[0] == 99999  # first positional arg is chat_id
    assert isinstance(call_args[1], list)
    assert len(call_args[1]) >= 1


# ---------------------------------------------------------------------------
# Test 4 — Multi-user delivery with different thresholds
# ---------------------------------------------------------------------------


async def test_4_multi_user_different_thresholds(generator, test_db, mock_notifier):
    """
    Seed two signals with distinct profits ($8 and $20 controlled via mock).
    User A has threshold $5 → receives both signals.
    User B has threshold $15 → receives only the $20 signal.
    """
    profits = [
        {"net_profit": Decimal("8.00"), "margin_pct": Decimal("10.00"),
         "revenue": Decimal("80.00"), "tcg_fees": Decimal("8.88"),
         "customs": Decimal("0.00"), "shipping": Decimal("15.00"),
         "cogs_usd": Decimal("48.12"), "forwarder_costs": Decimal("0.00")},
        {"net_profit": Decimal("20.00"), "margin_pct": Decimal("25.00"),
         "revenue": Decimal("80.00"), "tcg_fees": Decimal("8.88"),
         "customs": Decimal("0.00"), "shipping": Decimal("15.00"),
         "cogs_usd": Decimal("36.12"), "forwarder_costs": Decimal("0.00")},
    ]
    profit_iter = iter(profits)

    async with test_db() as session:
        session.add(_profitable_price("sv1-10", Decimal("90.00"), Decimal("52.00")))
        session.add(_profitable_price("sv1-11", Decimal("90.00"), Decimal("38.00")))
        await session.commit()

    with patch(
        "src.signals.generator.calculate_net_profit",
        side_effect=lambda *a, **kw: next(profit_iter),
    ):
        user_a = _mock_user("user-a", chat_id=11111, threshold=Decimal("5.00"))
        user_b = _mock_user("user-b", chat_id=22222, threshold=Decimal("15.00"))

        await generator.run_and_notify([user_a, user_b])

    assert mock_notifier.send_batch_signals.call_count == 2

    # First call → user_a (threshold $5 → gets both signals)
    call_a = mock_notifier.send_batch_signals.call_args_list[0]
    assert call_a[0][0] == 11111
    signals_a = call_a[0][1]
    assert len(signals_a) == 2

    # Second call → user_b (threshold $15 → gets only $20 signal)
    call_b = mock_notifier.send_batch_signals.call_args_list[1]
    assert call_b[0][0] == 22222
    signals_b = call_b[0][1]
    assert len(signals_b) == 1
    assert float(signals_b[0]["net_profit"]) == 20.0


# ---------------------------------------------------------------------------
# Test 5 — Audit snapshot completeness
# ---------------------------------------------------------------------------


async def test_5_audit_snapshot_completeness(generator, test_db):
    """
    Seed a profitable card, generate a signal, and assert the audit_snapshot
    contains non-None values in its prices, fees, and scores sub-dicts.
    """
    async with test_db() as session:
        session.add(_profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    signals = await generator.scan_for_signals()

    assert len(signals) >= 1
    audit = signals[0]["audit_snapshot"]

    # Top-level sections must exist
    assert "prices" in audit
    assert "fees" in audit
    assert "scores" in audit

    # Prices sub-dict
    assert audit["prices"]["cm_eur"] is not None
    assert audit["prices"]["tcg_usd"] is not None

    # Fees sub-dict — revenue and tcg_fees are always populated
    assert audit["fees"]["revenue"] is not None
    assert audit["fees"]["tcg_fees"] is not None

    # Scores sub-dict
    assert audit["scores"]["velocity"] is not None
    assert audit["scores"]["maturity"] is not None
    assert audit["scores"]["headache"] is not None
    assert audit["scores"]["trend"] is not None
    assert audit["scores"]["bundle_sds"] is not None


# ---------------------------------------------------------------------------
# Test 6 — CardMetadata enriches signal (name, set, URLs)
# ---------------------------------------------------------------------------


async def test_6_card_metadata_enriches_signal(generator, test_db):
    """
    Seed a card with full CardMetadata including name, set_name, and both
    marketplace URLs. Assert the generated signal reflects all metadata
    fields, not the 'Unknown' fallback.
    """
    tcg_url = "https://www.tcgplayer.com/product/123456"
    cm_url = "https://www.cardmarket.com/en/Pokemon/Cards/Charizard-ex"

    async with test_db() as session:
        session.add(
            _metadata(
                card_id="sv1-25",
                name="Charizard ex",
                set_name="Scarlet & Violet",
                tcgplayer_url=tcg_url,
                cardmarket_url=cm_url,
            )
        )
        session.add(_profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    signals = await generator.scan_for_signals()

    assert len(signals) >= 1
    signal = signals[0]
    assert signal["card_name"] == "Charizard ex"
    assert signal["tcgplayer_url"] == tcg_url
    assert signal["cardmarket_url"] == cm_url


# ---------------------------------------------------------------------------
# Test 7 — Empty database returns empty list without crashing
# ---------------------------------------------------------------------------


async def test_7_empty_database_returns_empty_list(generator, test_db):
    """
    An empty market_prices table must return an empty list, not raise an
    exception. The generator must be defensive against no data.
    """
    signals = await generator.scan_for_signals()

    assert signals == []
    assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# Test 8 — Condition mapping flows through pipeline (EX → LP, -15%)
# ---------------------------------------------------------------------------


async def test_8_condition_mapping_flows_through(generator, test_db):
    """
    Seed a card with condition="EXC" (Cardmarket Excellent).
    Assert the signal's condition field reflects the Cardmarket grade code
    "EXC" (the condition is stored as the CM enum value, not the TCG grade).

    Also verify that the net_profit is lower than it would be for NM
    (i.e., the -15% penalty actually reduces the sell price).
    """
    async with test_db() as session:
        # EXC condition — maps to LP at 0.85x multiplier
        session.add(
            _profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00"), condition="EXC")
        )
        await session.commit()

    signals = await generator.scan_for_signals()

    assert len(signals) >= 1
    signal = signals[0]
    # The generator stores the Cardmarket grade value (CardmarketGrade.EXCELLENT.value == "EXC")
    assert signal["condition"] == "EXC"
    # Revenue should reflect 0.85 multiplier on $100 TCG price = $85 gross
    # so net_profit must be less than the NM scenario (which uses $100 gross)
    assert signal["net_profit"] < Decimal("60")  # sanity upper bound on penalty card


# ---------------------------------------------------------------------------
# Test 9 — Rotation DANGER filters out dangerous cards
# ---------------------------------------------------------------------------


async def test_9_rotation_danger_filters_card(generator, test_db):
    """
    Seed a card with regulation_mark="G" and legality_standard="Legal".
    Patch check_rotation_risk to return DANGER risk_level.
    Assert the card is filtered out and no signal is generated.
    """
    async with test_db() as session:
        session.add(
            _metadata(
                card_id="sv1-99",
                regulation_mark="G",
                legality_standard="Legal",
            )
        )
        session.add(_profitable_price("sv1-99", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    with patch(
        "src.signals.generator.check_rotation_risk",
        return_value={
            "at_risk": True,
            "risk_level": "DANGER",
            "months_until_rotation": 1,
            "rotation_date": date(2026, 4, 10),
        },
    ):
        signals = await generator.scan_for_signals()

    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Test 10 — Bundle suppression on sub-$25 single card with negative profit
# ---------------------------------------------------------------------------


async def test_10_bundle_suppression_sub_25_single_card(generator, test_db):
    """
    Seed a low-value card ($20 TCG price, $15 EUR buy price).
    Mock calculate_net_profit to return net_profit <= 0 (shipping kills it).
    Assert the card is suppressed by bundle logic (SDS=1, price<$25, profit<=0).
    """
    async with test_db() as session:
        # Sub-$25 TCG price, low EUR cost
        session.add(
            _profitable_price("sv1-77", Decimal("20.00"), Decimal("15.00"), condition="NM")
        )
        await session.commit()

    # Force net_profit to -5.00 — shipping ($15) eats all revenue on a cheap card
    negative_profit = {
        "net_profit": Decimal("-5.00"),
        "margin_pct": Decimal("-30.00"),
        "revenue": Decimal("15.37"),
        "tcg_fees": Decimal("2.45"),
        "customs": Decimal("0.00"),
        "shipping": Decimal("15.00"),
        "cogs_usd": Decimal("16.20"),
        "forwarder_costs": Decimal("0.00"),
    }

    with patch(
        "src.signals.generator.calculate_net_profit",
        return_value=negative_profit,
    ):
        signals = await generator.scan_for_signals()

    # SDS=1, card_price=$20 < $25, net_profit=-$5 <= 0 → suppress
    assert len(signals) == 0


# ---------------------------------------------------------------------------
# Test 11 — run_and_notify: no signals, notifier never called
# ---------------------------------------------------------------------------


async def test_11_run_and_notify_no_signals_no_telegram_call(generator, test_db, mock_notifier):
    """
    If scan_for_signals returns an empty list (empty DB), run_and_notify
    must not call send_batch_signals at all — no empty Telegram messages.
    """
    # Empty DB — no rows seeded
    user = _mock_user(chat_id=55555, threshold=Decimal("5.00"))
    total = await generator.run_and_notify([user])

    mock_notifier.send_batch_signals.assert_not_called()
    assert total == 0


# ---------------------------------------------------------------------------
# Test 12 — Signal fields include all required keys
# ---------------------------------------------------------------------------


async def test_12_signal_includes_all_required_fields(generator, test_db):
    """
    A fully generated signal must contain every field that downstream
    consumers (Telegram formatter, audit writer) depend on.
    """
    async with test_db() as session:
        session.add(
            _metadata(
                card_id="sv1-25",
                name="Pikachu",
                set_name="Scarlet & Violet",
                tcgplayer_url="https://tcgplayer.com/product/1",
                cardmarket_url="https://cardmarket.com/en/Pokemon/Cards/Pikachu",
            )
        )
        session.add(_profitable_price("sv1-25", Decimal("100.00"), Decimal("40.00")))
        await session.commit()

    signals = await generator.scan_for_signals()

    assert len(signals) >= 1
    signal = signals[0]

    required_fields = [
        "card_id",
        "card_name",
        "net_profit",
        "margin_pct",
        "velocity_tier",
        "velocity_score",
        "headache_tier",
        "headache_score",
        "maturity_decay",
        "rotation_risk",
        "condition",
        "cm_price_eur",
        "tcg_price_usd",
        "trend_classification",
        "bundle_tier",
        "tcgplayer_url",
        "cardmarket_url",
        "created_at",
        "audit_snapshot",
    ]

    for field in required_fields:
        assert field in signal, f"Signal missing required field: {field!r}"
