"""
TCG Radar — Polling Scheduler (Layer 1 Orchestration)

Manages periodic polling of JustTCG and pokemontcg.io APIs on configurable cadences.
Supports Layer 3.5 social listening hooks to temporarily increase poll frequency.

Cadences:
- JustTCG: 6 hours (free tier) by default
- pokemontcg.io: 24 hours (data changes rarely)
- Social spike override: 30 minutes + auto-revert after 4 hours
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import settings
from src.pipeline.justtcg import JustTCGClient
from src.pipeline.pokemontcg import PokemonTCGClient

logger = structlog.get_logger(__name__)


class Scheduler:
    """
    Async scheduler for Layer 1 polling jobs.

    Maintains independent poll clocks for each data source. Supports temporary
    cadence increases for social listening triggers.
    """

    def __init__(
        self,
        db_engine: Any,
        session_factory: async_sessionmaker[AsyncSession],
    ):
        self.db_engine = db_engine
        self.session_factory = session_factory
        self._shutdown_event = asyncio.Event()

        # Track next poll times and cadences
        self._justtcg_last_poll: datetime = datetime.now(timezone.utc)
        self._justtcg_cadence_minutes = settings.JUSTTCG_POLL_INTERVAL_HOURS * 60

        self._pokemontcg_last_poll: datetime = datetime.now(timezone.utc)
        self._pokemontcg_cadence_minutes = settings.POKEMONTCG_REFRESH_INTERVAL_HOURS * 60

        # Social spike tracking: card_id -> (spike_start, spike_revert_time)
        self._social_spikes: dict[str, datetime] = {}

    async def shutdown(self) -> None:
        """Signal graceful shutdown to the scheduler loop."""
        logger.info("scheduler_shutdown_requested")
        self._shutdown_event.set()

    def increase_poll_cadence(self, card_id: str) -> None:
        """
        Layer 3.5 hook: Temporarily increase poll frequency for a specific card.

        Overrides normal 6-hour cadence to 30 minutes for SOCIAL_SPIKE_REVERT_HOURS
        (default 4 hours). Auto-reverts after the window expires.

        Args:
            card_id: Card to monitor at increased frequency.
        """
        revert_time = datetime.now(timezone.utc) + timedelta(
            hours=settings.SOCIAL_SPIKE_REVERT_HOURS
        )
        self._social_spikes[card_id] = revert_time

        logger.info(
            "scheduler_spike_activated",
            card_id=card_id,
            spike_duration_hours=settings.SOCIAL_SPIKE_REVERT_HOURS,
            revert_at=revert_time.isoformat(),
        )

    def _should_poll_justtcg(self) -> bool:
        """Check if JustTCG poll window has elapsed."""
        now = datetime.now(timezone.utc)
        # If any card has active social spike, use shorter cadence
        min_cadence = self._justtcg_cadence_minutes
        for card_id, revert_time in list(self._social_spikes.items()):
            if revert_time <= now:
                del self._social_spikes[card_id]
            else:
                min_cadence = min(min_cadence, settings.SOCIAL_SPIKE_POLL_INTERVAL_MINUTES)

        elapsed_minutes = (now - self._justtcg_last_poll).total_seconds() / 60
        return elapsed_minutes >= min_cadence

    def _should_poll_pokemontcg(self) -> bool:
        """Check if pokemontcg.io refresh window has elapsed."""
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - self._pokemontcg_last_poll).total_seconds() / 60
        return elapsed_minutes >= self._pokemontcg_cadence_minutes

    async def _poll_justtcg(self) -> int:
        """
        Fetch and store prices from JustTCG API.

        Returns:
            Number of price records upserted.
        """
        logger.info("scheduler_justtcg_poll_start")
        rowcount = 0

        async with self.session_factory() as session:
            async with JustTCGClient() as client:
                # Fetch a representative set of cards (MVP: fetch recent sets)
                # For Phase 1, we'll fetch a few popular sets to populate market_prices
                popular_sets = ["sv1", "sv1pt5", "sv2"]  # Scarlet & Violet era

                for set_code in popular_sets:
                    try:
                        prices = await client.fetch_set_prices(set_code)
                        stored = await client.store_prices(prices, session)
                        rowcount += stored
                    except Exception as e:
                        logger.error(
                            "scheduler_justtcg_set_fetch_failed",
                            set_code=set_code,
                            error=str(e),
                        )

        self._justtcg_last_poll = datetime.now(timezone.utc)

        logger.info(
            "scheduler_justtcg_poll_complete",
            rowcount=rowcount,
            next_poll_in_hours=settings.JUSTTCG_POLL_INTERVAL_HOURS,
        )
        return rowcount

    async def _poll_pokemontcg(self) -> int:
        """
        Fetch and store card metadata from pokemontcg.io.

        Returns:
            Number of card metadata records upserted.
        """
        logger.info("scheduler_pokemontcg_poll_start")
        rowcount = 0

        async with self.session_factory() as session:
            async with PokemonTCGClient() as client:
                # Fetch metadata for recent sets
                popular_sets = ["sv1", "sv1pt5", "sv2"]

                for set_code in popular_sets:
                    try:
                        cards = await client.fetch_set_cards(set_code)
                        stored = await client.store_metadata(cards, session)
                        rowcount += stored
                    except Exception as e:
                        logger.error(
                            "scheduler_pokemontcg_set_fetch_failed",
                            set_code=set_code,
                            error=str(e),
                        )

        self._pokemontcg_last_poll = datetime.now(timezone.utc)

        logger.info(
            "scheduler_pokemontcg_poll_complete",
            rowcount=rowcount,
            next_poll_in_hours=settings.POKEMONTCG_REFRESH_INTERVAL_HOURS,
        )
        return rowcount

    async def run(self) -> None:
        """
        Main scheduler loop. Runs indefinitely until shutdown is signaled.

        Periodically checks if poll windows have elapsed and executes jobs.
        Polls run independently; if one fails, others continue.
        """
        logger.info(
            "scheduler_started",
            justtcg_cadence_hours=settings.JUSTTCG_POLL_INTERVAL_HOURS,
            pokemontcg_cadence_hours=settings.POKEMONTCG_REFRESH_INTERVAL_HOURS,
        )

        # Run poll check loop every 5 seconds
        poll_check_interval = 5

        try:
            while not self._shutdown_event.is_set():
                try:
                    if self._should_poll_justtcg():
                        await self._poll_justtcg()

                    if self._should_poll_pokemontcg():
                        await self._poll_pokemontcg()

                    # Sleep before next check
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=poll_check_interval,
                    )
                except asyncio.TimeoutError:
                    # Expected: timeout means no shutdown signal, continue loop
                    continue
                except Exception as e:
                    logger.error(
                        "scheduler_unknown_error",
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    # Continue running despite errors
                    await asyncio.sleep(poll_check_interval)

        except asyncio.CancelledError:
            logger.info("scheduler_cancelled")
            raise
        finally:
            logger.info("scheduler_stopped")


async def run_scheduler(db_engine: Any, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """
    Initialize and run the scheduler with graceful shutdown handling.

    Registers SIGTERM/SIGINT handlers to trigger shutdown.

    Args:
        db_engine: SQLAlchemy async engine.
        session_factory: SQLAlchemy async session factory.
    """
    scheduler = Scheduler(db_engine, session_factory)

    # Register signal handlers for graceful shutdown
    def handle_signal(_signum: int, _frame: Any) -> None:
        """Called by SIGTERM/SIGINT."""
        logger.info("scheduler_signal_received")
        asyncio.create_task(scheduler.shutdown())

    loop = asyncio.get_event_loop()

    # Platform-dependent signal handling
    try:
        loop.add_signal_handler(signal.SIGTERM, handle_signal, signal.SIGTERM, None)
        loop.add_signal_handler(signal.SIGINT, handle_signal, signal.SIGINT, None)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler for all signals
        logger.warning("signal_handlers_not_supported_on_platform")

    try:
        await scheduler.run()
    except Exception as e:
        logger.error("scheduler_fatal_error", error=str(e), error_type=type(e).__name__)
        raise
