"""
TCG Radar — CSS Selector Fallback Scraper (Section 6 — BACKUP)

Uses deep CSS selectors with Playwright's >> combinator as a backup
when network interception fails. This is more fragile than API interception.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from src.scraper import ScraperResult

logger = structlog.get_logger(__name__)


async def scrape_via_css(
    page: Any,
    card_id: str,
    url: str,
) -> ScraperResult | None:
    """
    Fallback scraper using CSS selectors.

    Navigates to the page and extracts data using Playwright's
    deep CSS selectors. More fragile than network interception.

    Args:
        page: Playwright Page object.
        card_id: Card identifier.
        url: Cardmarket URL to navigate to.

    Returns:
        ScraperResult if data was extracted, None otherwise.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Extract price
        price_eur = await _extract_text(page, "[class*='price'] >> text=/\\d/")

        # Extract seller info
        seller_rating_text = await _extract_text(page, "[class*='seller-rating']")
        seller_sales_text = await _extract_text(page, "[class*='seller-sales'], [class*='sale-count']")
        seller_name = await _extract_text(page, "[class*='seller-name'] a")
        condition_text = await _extract_text(page, "[class*='condition'], [class*='product-condition']")
        shipping_text = await _extract_text(page, "[class*='shipping-cost'], [class*='delivery-cost']")

        if price_eur is None:
            logger.warning(
                "css_fallback_no_price",
                card_id=card_id,
                url=url,
                source="css_fallback",
            )
            return None

        return ScraperResult(
            card_id=card_id,
            price_eur=_parse_price(price_eur),
            seller_id=seller_name,
            seller_rating=_parse_decimal(seller_rating_text),
            seller_sales=_parse_int(seller_sales_text),
            condition=condition_text,
            shipping_eur=_parse_price(shipping_text),
            seller_other_cards=[],
            scrape_method="css_fallback",
            scraped_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        logger.error(
            "css_fallback_failed",
            card_id=card_id,
            url=url,
            error=str(e),
            source="css_fallback",
        )
        return None


async def _extract_text(page: Any, selector: str) -> str | None:
    """Safely extract text from a CSS selector."""
    try:
        element = await page.query_selector(selector)
        if element:
            return (await element.text_content() or "").strip()
    except Exception:
        pass
    return None


def _parse_price(text: str | None) -> Decimal | None:
    """Parse a price string like '€12.50' or '12,50 €' to Decimal."""
    if not text:
        return None
    try:
        # Remove currency symbols and whitespace
        cleaned = text.replace("€", "").replace("$", "").replace(",", ".").strip()
        # Extract first number-like substring
        match = re.search(r"[\d]+\.?\d*", cleaned)
        if match:
            return Decimal(match.group())
    except (InvalidOperation, ValueError):
        pass
    return None


def _parse_decimal(text: str | None) -> Decimal | None:
    """Parse a decimal from text."""
    if not text:
        return None
    try:
        match = re.search(r"[\d]+\.?\d*", text)
        if match:
            return Decimal(match.group())
    except (InvalidOperation, ValueError):
        pass
    return None


def _parse_int(text: str | None) -> int | None:
    """Parse an integer from text."""
    if not text:
        return None
    try:
        match = re.search(r"\d+", text.replace(",", "").replace(".", ""))
        if match:
            return int(match.group())
    except ValueError:
        pass
    return None
