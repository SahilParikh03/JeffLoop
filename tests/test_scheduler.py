"""
Tests for the scheduler module.

Validates polling logic, cadence management, and social spike handling.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import settings
from src.pipeline.scheduler import Scheduler


@pytest.fixture
async def test_db_engine():
    """Create an in-memory SQLite async engine for testing."""
    # Use SQLite with proper async driver
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_db_engine):
    """Create a session factory for tests."""
    return async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
async def scheduler(test_db_engine, test_session_factory):
    """Create a Scheduler instance for testing."""
    return Scheduler(test_db_engine, test_session_factory)


@pytest.mark.asyncio
async def test_scheduler_init(scheduler):
    """Test scheduler initialization."""
    assert scheduler._shutdown_event is not None
    assert scheduler._justtcg_cadence_minutes == settings.JUSTTCG_POLL_INTERVAL_HOURS * 60
    assert scheduler._pokemontcg_cadence_minutes == settings.POKEMONTCG_REFRESH_INTERVAL_HOURS * 60
    assert len(scheduler._social_spikes) == 0


@pytest.mark.asyncio
async def test_increase_poll_cadence(scheduler):
    """Test social spike activation."""
    card_id = "sv1-25"
    scheduler.increase_poll_cadence(card_id)

    assert card_id in scheduler._social_spikes
    revert_time = scheduler._social_spikes[card_id]
    assert isinstance(revert_time, datetime)


@pytest.mark.asyncio
async def test_should_poll_justtcg_baseline(scheduler):
    """Test JustTCG poll check when cadence elapsed."""
    # Set last poll to far past
    scheduler._justtcg_last_poll = datetime.now(timezone.utc) - timedelta(hours=7)
    assert scheduler._should_poll_justtcg() is True

    # Set to recent
    scheduler._justtcg_last_poll = datetime.now(timezone.utc)
    assert scheduler._should_poll_justtcg() is False


@pytest.mark.asyncio
async def test_should_poll_justtcg_with_spike(scheduler):
    """Test JustTCG poll uses spike cadence when activated."""
    # Set baseline cadence not ready
    scheduler._justtcg_last_poll = datetime.now(timezone.utc) - timedelta(minutes=10)

    # Activate spike (30-minute cadence)
    card_id = "sv1-25"
    scheduler.increase_poll_cadence(card_id)

    # Should NOT poll (only 10 minutes elapsed, need 30)
    assert scheduler._should_poll_justtcg() is False

    # Advance time past spike cadence
    scheduler._justtcg_last_poll = datetime.now(timezone.utc) - timedelta(minutes=35)
    assert scheduler._should_poll_justtcg() is True


@pytest.mark.asyncio
async def test_should_poll_pokemontcg(scheduler):
    """Test pokemontcg.io poll check."""
    # Set last poll to far past
    scheduler._pokemontcg_last_poll = datetime.now(timezone.utc) - timedelta(hours=25)
    assert scheduler._should_poll_pokemontcg() is True

    # Set to recent
    scheduler._pokemontcg_last_poll = datetime.now(timezone.utc)
    assert scheduler._should_poll_pokemontcg() is False


@pytest.mark.asyncio
async def test_spike_auto_revert(scheduler):
    """Test that expired spikes are cleaned up."""
    card_id = "sv1-25"

    # Create a spike that's already expired
    expired_time = datetime.now(timezone.utc) - timedelta(seconds=1)
    scheduler._social_spikes[card_id] = expired_time

    # Check poll — should clean up expired spike
    scheduler._should_poll_justtcg()

    assert card_id not in scheduler._social_spikes


@pytest.mark.asyncio
async def test_scheduler_shutdown(scheduler):
    """Test scheduler shutdown signal."""
    assert not scheduler._shutdown_event.is_set()
    await scheduler.shutdown()
    assert scheduler._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_poll_justtcg_mock(scheduler):
    """Test JustTCG polling with mocked client."""
    mock_prices = [
        MagicMock(card_id="sv1-25", price_usd=10.00, price_eur=9.50),
    ]

    with patch("src.pipeline.scheduler.JustTCGClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.fetch_set_prices = AsyncMock(return_value=mock_prices)
        mock_client.store_prices = AsyncMock(return_value=1)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        rowcount = await scheduler._poll_justtcg()

        assert rowcount > 0
        assert scheduler._justtcg_last_poll > datetime.now(timezone.utc) - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_poll_pokemontcg_mock(scheduler):
    """Test pokemontcg polling with mocked client."""
    mock_cards = [
        MagicMock(id="sv1-25", name="Charizard ex"),
    ]

    with patch("src.pipeline.scheduler.PokemonTCGClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.fetch_set_cards = AsyncMock(return_value=mock_cards)
        mock_client.store_metadata = AsyncMock(return_value=1)
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        rowcount = await scheduler._poll_pokemontcg()

        assert rowcount > 0
        assert scheduler._pokemontcg_last_poll > datetime.now(timezone.utc) - timedelta(seconds=1)


# ---------------------------------------------------------------------------
# Stream E: Signal generator integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def scheduler_with_generator(test_db_engine, test_session_factory):
    """Create a Scheduler instance with a mocked SignalGenerator."""
    mock_generator = AsyncMock()
    mock_generator.run_and_notify = AsyncMock(return_value=5)
    sched = Scheduler(test_db_engine, test_session_factory, signal_generator=mock_generator)
    return sched


@pytest.mark.asyncio
async def test_should_scan_signals_none_generator(test_db_engine, test_session_factory):
    """When signal_generator is None, _should_scan_signals must return False."""
    sched = Scheduler(test_db_engine, test_session_factory, signal_generator=None)
    assert sched._should_scan_signals() is False


@pytest.mark.asyncio
async def test_should_scan_signals_not_elapsed(scheduler_with_generator):
    """When cadence has not elapsed, _should_scan_signals returns False."""
    # Set last scan to just now — well within the 30-minute cadence
    scheduler_with_generator._signal_last_scan = datetime.now(timezone.utc)
    assert scheduler_with_generator._should_scan_signals() is False


@pytest.mark.asyncio
async def test_should_scan_signals_elapsed(scheduler_with_generator):
    """When cadence has elapsed, _should_scan_signals returns True."""
    # Set last scan to 31 minutes ago — past the 30-minute cadence
    scheduler_with_generator._signal_last_scan = (
        datetime.now(timezone.utc) - timedelta(minutes=31)
    )
    assert scheduler_with_generator._should_scan_signals() is True


@pytest.mark.asyncio
async def test_scan_signals_runs_generator(scheduler_with_generator):
    """_scan_signals fetches user profiles and calls run_and_notify with them."""
    # Force the cadence to appear elapsed so the scan path is exercised
    scheduler_with_generator._signal_last_scan = (
        datetime.now(timezone.utc) - timedelta(minutes=31)
    )

    mock_user = MagicMock()
    mock_user.id = "user-1"

    # Build a mock session whose execute() returns a result with one user.
    # select and UserProfile are local imports inside _scan_signals, so we
    # patch at their origin modules to avoid AttributeError on the scheduler.
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_user]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.models.user_profile.UserProfile", new_callable=MagicMock), \
         patch("sqlalchemy.select", return_value=MagicMock()):
        with patch.object(scheduler_with_generator, "session_factory", mock_factory):
            delivered = await scheduler_with_generator._scan_signals()

    # run_and_notify must have been called exactly once with the user list
    scheduler_with_generator.signal_generator.run_and_notify.assert_called_once_with(
        [mock_user]
    )
    assert delivered == 5


@pytest.mark.asyncio
async def test_scan_signals_error_resilience(scheduler_with_generator):
    """If signal_generator.run_and_notify raises, scheduler logs and updates last_scan."""
    scheduler_with_generator.signal_generator.run_and_notify = AsyncMock(
        side_effect=RuntimeError("generator exploded")
    )

    before = datetime.now(timezone.utc) - timedelta(seconds=1)

    mock_user = MagicMock()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_user]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_session)

    with patch("src.models.user_profile.UserProfile", new_callable=MagicMock), \
         patch("sqlalchemy.select", return_value=MagicMock()):
        with patch.object(scheduler_with_generator, "session_factory", mock_factory):
            # Must not raise — error resilience is the contract
            delivered = await scheduler_with_generator._scan_signals()

    assert delivered == 0
    # last_scan must have been updated to prevent rapid retries
    assert scheduler_with_generator._signal_last_scan >= before


@pytest.mark.asyncio
async def test_scheduler_run_includes_signal_scan(test_db_engine, test_session_factory):
    """run() calls _scan_signals when the cadence is due."""
    mock_generator = AsyncMock()
    mock_generator.run_and_notify = AsyncMock(return_value=3)

    sched = Scheduler(test_db_engine, test_session_factory, signal_generator=mock_generator)

    # Make the signal scan immediately due
    sched._signal_last_scan = datetime.now(timezone.utc) - timedelta(minutes=31)

    # Prevent JustTCG and pokemontcg polls from running (not the focus here)
    sched._justtcg_last_poll = datetime.now(timezone.utc)
    sched._pokemontcg_last_poll = datetime.now(timezone.utc)

    scan_called = asyncio.Event()

    original_scan = sched._scan_signals

    async def _patched_scan() -> int:
        scan_called.set()
        await sched.shutdown()
        return 0

    sched._scan_signals = _patched_scan  # type: ignore[method-assign]

    # Run the scheduler; it will call _patched_scan which then shuts itself down
    await sched.run()

    assert scan_called.is_set(), "_scan_signals was never called by run()"
