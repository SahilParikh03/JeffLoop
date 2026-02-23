"""
TCG Radar — Vision Fallback Scraper (Section 6 — EMERGENCY)

Takes a screenshot of the page and extracts structured data.
SECURITY: NEVER passes DOM content or seller descriptions to AI.
Only processes screenshots (image data). See CVE-2026-25253.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import anthropic
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

        logger.info(
            "vision_fallback_screenshot_captured",
            card_id=card_id,
            screenshot_size_bytes=len(screenshot_bytes),
            source="vision_fallback",
        )

        # Guard: no API key configured
        from src.config import settings
        if not settings.OPENROUTER_API_KEY:
            logger.warning(
                "vision_fallback_no_api_key",
                card_id=card_id,
                source="vision_fallback",
            )
            return None

        # Base64-encode the screenshot
        image_data = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

        # Call Claude Vision API
        # SECURITY: Only screenshot_bytes (image) sent — NO DOM text, NO seller descriptions
        client = anthropic.AsyncAnthropic(api_key=settings.OPENROUTER_API_KEY)
        response = await client.messages.create(
            model=settings.VISION_MODEL_ID,
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extract card listing data from this Cardmarket screenshot. "
                            "Return ONLY a JSON object: "
                            '{"price_eur": <number|null>, "seller_rating": <number|null>, '
                            '"seller_sales": <integer|null>, "condition": <"MT"|"NM"|"EXC"|"GD"|"LP"|"PL"|"PO"|null>, '
                            '"shipping_eur": <number|null>} '
                            "No other text."
                        ),
                    },
                ],
            }],
        )

        # Parse JSON response
        try:
            raw = response.content[0].text.strip()
            extracted = json.loads(raw)
        except (json.JSONDecodeError, IndexError, AttributeError) as parse_err:
            logger.warning(
                "vision_fallback_parse_error",
                card_id=card_id,
                error=str(parse_err),
                source="vision_fallback",
            )
            return None

        return ScraperResult(
            card_id=card_id,
            price_eur=Decimal(str(extracted["price_eur"])) if extracted.get("price_eur") is not None else None,
            seller_rating=Decimal(str(extracted["seller_rating"])) if extracted.get("seller_rating") is not None else None,
            seller_sales=extracted.get("seller_sales"),
            condition=extracted.get("condition"),
            shipping_eur=Decimal(str(extracted["shipping_eur"])) if extracted.get("shipping_eur") is not None else None,
            scrape_method="vision",
            scraped_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        logger.error(
            "vision_fallback_failed",
            card_id=card_id,
            url=url,
            error=str(e),
            source="vision_fallback",
        )
        return None
