"""
TCG Radar — Vision Fallback Scraper (Section 6 — EMERGENCY)

Takes a screenshot of the page and extracts structured data.
SECURITY: NEVER passes DOM content or seller descriptions to AI.
Only processes screenshots (image data). See CVE-2026-25253.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from src.scraper import ScraperResult

logger = structlog.get_logger(__name__)


async def scrape_via_vision(
    page: Any,
    card_id: str,
    url: str,
) -> ScraperResult | None:
    """
    Emergency scraper using screenshot analysis.

    Takes a screenshot and extracts structured data from the image.
    SECURITY: Only image bytes are processed — NO DOM text, NO seller
    descriptions, NO free-text content is passed to any AI/LLM call.

    This is the last resort when both network interception and CSS fail.

    Args:
        page: Playwright Page object.
        card_id: Card identifier.
        url: URL to screenshot.

    Returns:
        ScraperResult with extracted data, or None if extraction fails.
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Take screenshot — this is the ONLY data we process
        screenshot_bytes = await page.screenshot(full_page=False)

        if not screenshot_bytes:
            logger.warning(
                "vision_fallback_no_screenshot",
                card_id=card_id,
                url=url,
                source="vision_fallback",
            )
            return None

        # Phase 2: Screenshot → structured data extraction
        # This would call a vision model with ONLY the screenshot bytes
        # For now, log and return None — vision extraction is Phase 3
        logger.info(
            "vision_fallback_screenshot_captured",
            card_id=card_id,
            screenshot_size_bytes=len(screenshot_bytes),
            source="vision_fallback",
        )

        # TODO: Phase 3 — Implement vision model extraction
        # SECURITY: Only pass screenshot_bytes (image), never DOM text
        return None

    except Exception as e:
        logger.error(
            "vision_fallback_failed",
            card_id=card_id,
            url=url,
            error=str(e),
            source="vision_fallback",
        )
        return None
