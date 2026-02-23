"""TCG Radar — Scraper Layer (Section 6)"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ScraperResult(BaseModel):
    """Structured result from any scraping method."""
    card_id: str
    price_eur: Decimal | None = None
    seller_id: str | None = None
    seller_rating: Decimal | None = None
    seller_sales: int | None = None
    condition: str | None = None
    shipping_eur: Decimal | None = None
    seller_other_cards: list[str] = Field(default_factory=list)
    scrape_method: str  # "network_intercept" | "css_fallback" | "vision"
    scraped_at: datetime
