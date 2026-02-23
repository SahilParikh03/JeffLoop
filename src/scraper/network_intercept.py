"""
TCG Radar — Network Interception Scraper (Section 6 — PRIMARY)

Intercepts API/XHR responses from Cardmarket pages via page.route().
This is the primary scraping method — CSS and vision are fallbacks only.

SECURITY: Never passes DOM content or seller descriptions to AI (CVE-2026-25253).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from src.scraper import ScraperResult

logger = structlog.get_logger(__name__)


async def scrape_via_network_intercept(
    page: Any,
    card_id: str,
    url: str,
) -> ScraperResult | None:
    """
    Intercept API responses from a Cardmarket product page.

    Uses page.route() to capture XHR/fetch responses containing
    price and seller data. This avoids fragile CSS selectors.

    Args:
        page: Playwright Page object.
        card_id: Card identifier.
        url: Cardmarket URL to navigate to.

    Returns:
        ScraperResult if data was successfully intercepted, None otherwise.
    """
    intercepted_data: dict[str, Any] = {}

    async def handle_route(route: Any) -> None:
        """Intercept and capture API responses, then continue."""
        response = await route.fetch()
        body = await response.text()

        # Look for JSON API responses containing price data
        if response.headers.get("content-type", "").startswith("application/json"):
            try:
                data = json.loads(body)
                if isinstance(data, dict):
                    # Check for seller/price data patterns
                    if "price" in str(data).lower() or "seller" in str(data).lower():
                        intercepted_data.update(data)
            except (json.JSONDecodeError, ValueError):
                pass

        await route.fulfill(response=response)

    try:
        # Intercept API calls
        await page.route("**/api/**", handle_route)
        await page.route("**/ajax/**", handle_route)

        # Navigate to the page
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # Parse intercepted data
        if not intercepted_data:
            logger.warning(
                "network_intercept_no_data",
                card_id=card_id,
                url=url,
                source="network_intercept",
            )
            return None

        return _parse_intercepted_data(card_id, intercepted_data)

    except Exception as e:
        logger.error(
            "network_intercept_failed",
            card_id=card_id,
            url=url,
            error=str(e),
            source="network_intercept",
        )
        return None


def _parse_intercepted_data(
    card_id: str,
    data: dict[str, Any],
) -> ScraperResult | None:
    """Parse intercepted API data into a ScraperResult."""
    try:
        price_eur = _safe_decimal(data.get("price") or data.get("priceEUR"))
        seller_rating = _safe_decimal(data.get("sellerRating") or data.get("seller_rating"))
        seller_sales = data.get("sellerSales") or data.get("seller_sales")
        seller_id = data.get("sellerId") or data.get("seller_id")
        condition = data.get("condition")
        shipping_eur = _safe_decimal(data.get("shippingPrice") or data.get("shipping"))

        # Seller's other cards (for SDS calculation)
        other_cards = data.get("sellerOtherCards", []) or data.get("otherCards", [])
        if isinstance(other_cards, list):
            seller_other_cards = [str(c) for c in other_cards[:50]]  # Cap at 50
        else:
            seller_other_cards = []

        return ScraperResult(
            card_id=card_id,
            price_eur=price_eur,
            seller_id=str(seller_id) if seller_id else None,
            seller_rating=seller_rating,
            seller_sales=int(seller_sales) if seller_sales is not None else None,
            condition=str(condition) if condition else None,
            shipping_eur=shipping_eur,
            seller_other_cards=seller_other_cards,
            scrape_method="network_intercept",
            scraped_at=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(
            "network_intercept_parse_failed",
            card_id=card_id,
            error=str(e),
            source="network_intercept",
        )
        return None


def _safe_decimal(value: Any) -> Decimal | None:
    """Safely convert a value to Decimal."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
