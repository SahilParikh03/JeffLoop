"""
TCG Radar — Event Trigger Wiring (Section 11)

Connects event intelligence sources (social spikes, tournament results,
synergy detection) to concrete actions:
- Increase poll cadence for trending cards
- Queue scrape jobs for cards needing seller data
- Build synergy targets from tournament decklists

This module is the glue between the events layer and the pipeline/scraper.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.events.limitless import LimitlessTCGClient, DecklistEntry
from src.events.social_listener import SocialListener
from src.events.synergy import (
    build_cooccurrence_matrix,
    get_synergy_targets,
    store_cooccurrence_matrix,
    SynergyTarget,
)

logger = structlog.get_logger(__name__)


class EventTrigger:
    """
    Orchestrates event-driven actions.

    Connects social listening spikes and tournament data to:
    1. Scheduler poll cadence increases
    2. Scraper job queuing
    3. Synergy matrix updates

    Usage:
        trigger = EventTrigger(scheduler=scheduler)
        await trigger.process_social_spikes(keywords)
        await trigger.process_tournament(tournament_id, session)
    """

    def __init__(
        self,
        scheduler: Any | None = None,  # Scheduler instance
        scraper_runner: Any | None = None,  # ScraperRunner instance
    ) -> None:
        self.scheduler = scheduler
        self.scraper_runner = scraper_runner
        self.social_listener = SocialListener()

    async def process_social_spikes(
        self,
        keywords: list[str],
        adapter: Any | None = None,
    ) -> list[str]:
        """
        Scan for social media spikes and trigger actions.

        For each spiking keyword:
        1. Increase poll cadence via scheduler
        2. Get synergy targets and increase their cadence too

        Args:
            keywords: Card names/keywords to monitor.
            adapter: Optional platform adapter (for testing).

        Returns:
            List of keywords that triggered actions.
        """
        triggered: list[str] = []

        try:
            spiking = await self.social_listener.scan_for_spikes(keywords, adapter=adapter)

            for keyword in spiking:
                # Action 1: Increase poll cadence for the spiking card
                if self.scheduler is not None:
                    self.scheduler.increase_poll_cadence(keyword)
                    logger.info(
                        "trigger_poll_increase",
                        keyword=keyword,
                        source="triggers",
                    )

                triggered.append(keyword)

            logger.info(
                "trigger_social_spikes_processed",
                total_spiking=len(spiking),
                total_triggered=len(triggered),
                source="triggers",
            )

        except Exception as e:
            logger.error(
                "trigger_social_spikes_failed",
                error=str(e),
                source="triggers",
            )

        return triggered

    async def process_tournament(
        self,
        tournament_id: str,
        session: AsyncSession | None = None,
    ) -> list[SynergyTarget]:
        """
        Process tournament results and update synergy matrix.

        1. Fetch tournament results from Limitless
        2. Build co-occurrence matrix from decklists
        3. Store matrix in DB (if session provided)
        4. Return top synergy targets from winning decks

        Args:
            tournament_id: Limitless tournament ID.
            session: Optional DB session for persistence.

        Returns:
            List of synergy targets from top placements.
        """
        all_targets: list[SynergyTarget] = []

        try:
            async with LimitlessTCGClient() as client:
                results = await client.fetch_tournament_results(tournament_id)

            if not results:
                logger.info(
                    "trigger_tournament_no_results",
                    tournament_id=tournament_id,
                    source="triggers",
                )
                return []

            # Build co-occurrence matrix from all decklists
            decklists = [r.decklist for r in results if r.decklist]
            matrix = build_cooccurrence_matrix(decklists)

            # Store in DB if session available
            if session is not None and matrix:
                await store_cooccurrence_matrix(matrix, session)

            # Get synergy targets for top-placing cards
            # Focus on cards from top 8 placements
            top_results = [r for r in results if r.placement <= 8]
            seen_cards: set[str] = set()

            for result in top_results:
                for card in result.decklist:
                    if card.card_name not in seen_cards:
                        targets = get_synergy_targets(card.card_name, matrix, top_n=5)
                        all_targets.extend(targets)
                        seen_cards.add(card.card_name)

            # Deduplicate targets by card name, keeping highest cooccurrence
            unique_targets: dict[str, SynergyTarget] = {}
            for target in all_targets:
                if (
                    target.card_name not in unique_targets
                    or target.cooccurrence_count > unique_targets[target.card_name].cooccurrence_count
                ):
                    unique_targets[target.card_name] = target

            all_targets = sorted(
                unique_targets.values(),
                key=lambda t: t.cooccurrence_count,
                reverse=True,
            )[:50]  # Cap at 50 targets

            # Increase poll cadence for top synergy targets
            if self.scheduler is not None:
                for target in all_targets[:10]:  # Top 10 get priority
                    self.scheduler.increase_poll_cadence(target.card_name)

            logger.info(
                "trigger_tournament_processed",
                tournament_id=tournament_id,
                results_count=len(results),
                synergy_targets=len(all_targets),
                source="triggers",
            )

        except Exception as e:
            logger.error(
                "trigger_tournament_failed",
                tournament_id=tournament_id,
                error=str(e),
                source="triggers",
            )

        return all_targets

    async def queue_scrape(
        self,
        card_id: str,
        url: str,
        page: Any,
        session: AsyncSession | None = None,
    ) -> bool:
        """
        Queue a scrape job for a specific card.

        Args:
            card_id: Card to scrape.
            url: URL to scrape.
            page: Playwright Page object.
            session: Optional DB session for storing results.

        Returns:
            True if scrape succeeded, False otherwise.
        """
        if self.scraper_runner is None:
            logger.warning(
                "trigger_scrape_no_runner",
                card_id=card_id,
                source="triggers",
            )
            return False

        try:
            result = await self.scraper_runner.scrape_card(card_id, url, page, session)

            if result is not None:
                logger.info(
                    "trigger_scrape_success",
                    card_id=card_id,
                    method=result.scrape_method,
                    source="triggers",
                )
                return True
            else:
                logger.warning(
                    "trigger_scrape_failed",
                    card_id=card_id,
                    source="triggers",
                )
                return False

        except Exception as e:
            logger.error(
                "trigger_scrape_error",
                card_id=card_id,
                error=str(e),
                source="triggers",
            )
            return False
