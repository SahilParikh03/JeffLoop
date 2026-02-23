"""
TCG Radar — Scraper Runner (Section 6 Orchestrator)

Orchestrates the three-method fallback chain:
1. Network Interception (PRIMARY)
2. CSS Selectors (BACKUP)
3. Vision/Screenshot (EMERGENCY)

Updates market_prices with seller data when scraping succeeds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.scraper import ScraperResult
from src.scraper.anti_detect import AntiDetect
from src.scraper.css_fallback import scrape_via_css
from src.scraper.network_intercept import scrape_via_network_intercept
from src.scraper.vision_fallback import scrape_via_vision

logger = structlog.get_logger(__name__)


class ScraperRunner:
    """
    Runs the scraper fallback chain for a given card.

    Usage:
        runner = ScraperRunner()
        result = await runner.scrape_card(card_id, url, page, session)
    """

    def __init__(self) -> None:
        self.anti_detect = AntiDetect()

    async def scrape_card(
        self,
        card_id: str,
        url: str,
        page: Any,
        session: AsyncSession | None = None,
    ) -> ScraperResult | None:
        """
        Scrape a card listing using the 3-method fallback chain.

        Args:
            card_id: Card identifier.
            url: URL to scrape.
            page: Playwright Page object.
            session: Optional DB session for storing results.

        Returns:
            ScraperResult if any method succeeds, None if all fail.
        """
        if not self.anti_detect.can_scrape():
            logger.warning(
                "scraper_rate_limited",
                card_id=card_id,
                pages_remaining=self.anti_detect.pages_remaining,
                source="scraper_runner",
            )
            return None

        # Apply random delay before scraping
        await self.anti_detect.random_delay()

        result: ScraperResult | None = None

        # Method 1: Network Interception (PRIMARY)
        logger.info("scraper_trying_network_intercept", card_id=card_id, source="scraper_runner")
        result = await scrape_via_network_intercept(page, card_id, url)

        # Method 2: CSS Fallback (BACKUP)
        if result is None:
            logger.info("scraper_trying_css_fallback", card_id=card_id, source="scraper_runner")
            result = await scrape_via_css(page, card_id, url)

        # Method 3: Vision Fallback (EMERGENCY)
        if result is None:
            logger.info("scraper_trying_vision_fallback", card_id=card_id, source="scraper_runner")
            result = await scrape_via_vision(page, card_id, url)

        # Record the page access for rate limiting
        self.anti_detect.record_page()

        if result is not None:
            logger.info(
                "scraper_success",
                card_id=card_id,
                method=result.scrape_method,
                source="scraper_runner",
            )

            # Store result in market_prices if session provided
            if session is not None:
                await _store_scraper_result(result, session)
        else:
            logger.warning(
                "scraper_all_methods_failed",
                card_id=card_id,
                url=url,
                source="scraper_runner",
            )

        return result


async def _store_scraper_result(result: ScraperResult, session: AsyncSession) -> None:
    """
    Update market_prices with scraped seller data.

    Updates the seller_id, seller_rating, seller_sales columns
    for the given card. Uses source='cardmarket_scrape'.
    """
    try:
        stmt = text("""
            INSERT INTO market_prices (
                card_id, source, price_eur, seller_id, seller_rating,
                seller_sales, condition, last_updated
            )
            VALUES (
                :card_id, 'cardmarket_scrape', :price_eur, :seller_id,
                :seller_rating, :seller_sales, :condition, :last_updated
            )
            ON CONFLICT (card_id, source) DO UPDATE SET
                price_eur = EXCLUDED.price_eur,
                seller_id = EXCLUDED.seller_id,
                seller_rating = EXCLUDED.seller_rating,
                seller_sales = EXCLUDED.seller_sales,
                condition = EXCLUDED.condition,
                last_updated = EXCLUDED.last_updated
        """)

        await session.execute(
            stmt,
            {
                "card_id": result.card_id,
                "price_eur": result.price_eur,
                "seller_id": result.seller_id,
                "seller_rating": result.seller_rating,
                "seller_sales": result.seller_sales,
                "condition": result.condition,
                "last_updated": datetime.now(timezone.utc),
            },
        )
        await session.commit()

        logger.info(
            "scraper_result_stored",
            card_id=result.card_id,
            method=result.scrape_method,
            source="scraper_runner",
        )
    except Exception as e:
        logger.error(
            "scraper_result_store_failed",
            card_id=result.card_id,
            error=str(e),
            source="scraper_runner",
        )
