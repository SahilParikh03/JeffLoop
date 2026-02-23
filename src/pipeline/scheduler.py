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
from src.pipeline.ebay import eBayClient
from src.pipeline.justtcg import JustTCGClient
from src.pipeline.pokemontcg import PokemonTCGClient
from src.pipeline.poketrace import PokeTraceClient

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
        signal_generator: Any | None = None,  # SignalGenerator instance, optional
    ):
        self.db_engine = db_engine
        self.session_factory = session_factory
        self._shutdown_event = asyncio.Event()

        # Track next poll times and cadences
        self._justtcg_last_poll: datetime = datetime.now(timezone.utc)
        self._justtcg_cadence_minutes = settings.JUSTTCG_POLL_INTERVAL_HOURS * 60

        self._pokemontcg_last_poll: datetime = datetime.now(timezone.utc)
        self._pokemontcg_cadence_minutes = settings.POKEMONTCG_REFRESH_INTERVAL_HOURS * 60

        self._poketrace_last_poll: datetime = datetime.now(timezone.utc)
        self._poketrace_cadence_minutes = settings.POKETRACE_POLL_INTERVAL_HOURS * 60

        # eBay polling (optional — only active when EBAY_APP_ID is set)
        self._ebay_last_poll: datetime = datetime.now(timezone.utc)
        self._ebay_cadence_minutes = settings.EBAY_POLL_INTERVAL_HOURS * 60

        # Social spike tracking: card_id -> (spike_start, spike_revert_time)
        self._social_spikes: dict[str, datetime] = {}

        # Signal generator wiring
        self.signal_generator = signal_generator
        self._signal_last_scan: datetime = datetime.min.replace(tzinfo=timezone.utc)
        self._signal_cadence_minutes = settings.SIGNAL_SCAN_INTERVAL_MINUTES

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

    def _should_poll_poketrace(self) -> bool:
        """Check if PokeTrace poll window has elapsed."""
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - self._poketrace_last_poll).total_seconds() / 60
        return elapsed_minutes >= self._poketrace_cadence_minutes

    async def _poll_poketrace(self) -> int:
        """
        Fetch and store velocity data from PokeTrace API.

        Returns:
            Number of velocity records stored.
        """
        logger.info("scheduler_poketrace_poll_start")
        rowcount = 0

        async with self.session_factory() as session:
            async with PokeTraceClient() as client:
                popular_sets = ["sv1", "sv1pt5", "sv2"]

                for set_code in popular_sets:
                    try:
                        velocities = await client.fetch_set_velocity(set_code)
                        for vel_data in velocities:
                            try:
                                await client.store_velocity(vel_data, session)
                                rowcount += 1
                            except Exception as e:
                                logger.error(
                                    "scheduler_poketrace_store_failed",
                                    card_id=vel_data.card_id,
                                    error=str(e),
                                )
                    except Exception as e:
                        logger.error(
                            "scheduler_poketrace_set_fetch_failed",
                            set_code=set_code,
                            error=str(e),
                        )

        self._poketrace_last_poll = datetime.now(timezone.utc)

        logger.info(
            "scheduler_poketrace_poll_complete",
            rowcount=rowcount,
            next_poll_in_hours=settings.POKETRACE_POLL_INTERVAL_HOURS,
        )
        return rowcount

    def _should_poll_ebay(self) -> bool:
        """Check if eBay poll window has elapsed. Only active when credentials set."""
        if not settings.EBAY_APP_ID:
            return False
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - self._ebay_last_poll).total_seconds() / 60
        return elapsed_minutes >= self._ebay_cadence_minutes

    async def _poll_ebay(self) -> int:
        """
        Fetch and store market prices from eBay Browse API.

        Queries the DB for cards with recent JustTCG prices and supplements
        them with eBay median prices. Only runs when EBAY_APP_ID is configured.

        Returns:
            Number of eBay price records upserted.
        """
        logger.info("scheduler_ebay_poll_start")
        rowcount = 0

        async with self.session_factory() as session:
            async with eBayClient(self.session_factory) as client:
                # Fetch eBay prices for popular sets (same set list as JustTCG)
                from sqlalchemy import text as sa_text

                try:
                    # Query DB for distinct card names from market_prices (source=justtcg)
                    result = await session.execute(
                        sa_text(
                            "SELECT card_id FROM market_prices "
                            "WHERE source = 'justtcg' "
                            "ORDER BY last_updated DESC LIMIT 50"
                        )
                    )
                    card_ids = [row[0] for row in result.fetchall()]
                except Exception as e:
                    logger.error(
                        "scheduler_ebay_card_query_failed",
                        error=str(e),
                    )
                    card_ids = []

                for card_id in card_ids:
                    try:
                        # Use card_id as search term (pokemontcg.io format: sv1-1)
                        price = await client.get_market_price(card_id, card_id)
                        if price is not None:
                            await client.store_price(card_id, price, session)
                            rowcount += 1
                    except Exception as e:
                        logger.error(
                            "scheduler_ebay_card_failed",
                            card_id=card_id,
                            error=str(e),
                        )

        self._ebay_last_poll = datetime.now(timezone.utc)

        logger.info(
            "scheduler_ebay_poll_complete",
            rowcount=rowcount,
            next_poll_in_hours=settings.EBAY_POLL_INTERVAL_HOURS,
        )
        return rowcount

    def _should_scan_signals(self) -> bool:
        """Check if signal scan window has elapsed."""
        if self.signal_generator is None:
            return False
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - self._signal_last_scan).total_seconds() / 60
        return elapsed_minutes >= self._signal_cadence_minutes

    async def _scan_signals(self) -> int:
        """
        Run the signal generator scan-and-notify pipeline.

        Fetches all user profiles and runs the full Layer 2->4 pipeline.
        Returns: Number of signals delivered.
        """
        logger.info("scheduler_signal_scan_start")
        delivered = 0

        try:
            async with self.session_factory() as session:
                from src.models.user_profile import UserProfile
                from sqlalchemy import select

                result = await session.execute(select(UserProfile))
                users = result.scalars().all()

            if users:
                delivered = await self.signal_generator.run_and_notify(users)

            self._signal_last_scan = datetime.now(timezone.utc)

            logger.info(
                "scheduler_signal_scan_complete",
                delivered=delivered,
                user_count=len(users) if users else 0,
            )
        except Exception as e:
            logger.error(
                "scheduler_signal_scan_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Update last scan time even on failure to prevent rapid retries
            self._signal_last_scan = datetime.now(timezone.utc)

        return delivered

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

                    if self._should_poll_poketrace():
                        await self._poll_poketrace()

                    if self._should_poll_ebay():
                        await self._poll_ebay()

                    if self._should_scan_signals():
                        await self._scan_signals()

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


async def run_scheduler(
    db_engine: Any,
    session_factory: async_sessionmaker[AsyncSession],
    signal_generator: Any | None = None,
) -> None:
    """
    Initialize and run the scheduler with graceful shutdown handling.

    Registers SIGTERM/SIGINT handlers to trigger shutdown.

    Args:
        db_engine: SQLAlchemy async engine.
        session_factory: SQLAlchemy async session factory.
        signal_generator: Optional SignalGenerator instance for Layer 2->4 pipeline.
    """
    scheduler = Scheduler(db_engine, session_factory, signal_generator=signal_generator)

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
