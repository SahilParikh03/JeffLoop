"""
TCG Radar — Anti-Detection Layer (Section 6)

Manages random delays, fingerprint rotation, proxy configuration,
and hourly rate cap from settings.SCRAPE_MAX_PAGES_PER_HOUR.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class AntiDetect:
    """
    Anti-detection wrapper for Playwright scraping.

    Manages:
    - Random delays between scrape_delay_min and scrape_delay_max
    - Hourly page rate cap (SCRAPE_MAX_PAGES_PER_HOUR)
    - User-agent rotation
    - Proxy configuration
    """

    # Realistic user agents for rotation
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    ]

    def __init__(self) -> None:
        self._pages_this_hour: int = 0
        self._hour_start: datetime = datetime.now(timezone.utc)
        self._max_pages_per_hour: int = settings.SCRAPE_MAX_PAGES_PER_HOUR
        self._delay_min: int = settings.SCRAPE_DELAY_MIN_SECONDS
        self._delay_max: int = settings.SCRAPE_DELAY_MAX_SECONDS

    def _reset_hour_if_needed(self) -> None:
        """Reset page counter if a new hour has started."""
        now = datetime.now(timezone.utc)
        elapsed = (now - self._hour_start).total_seconds()
        if elapsed >= 3600:
            self._pages_this_hour = 0
            self._hour_start = now

    def can_scrape(self) -> bool:
        """Check if we're under the hourly rate cap."""
        self._reset_hour_if_needed()
        return self._pages_this_hour < self._max_pages_per_hour

    def record_page(self) -> None:
        """Record a page scrape for rate limiting."""
        self._reset_hour_if_needed()
        self._pages_this_hour += 1

    async def random_delay(self) -> None:
        """Sleep for a random duration between min and max delay."""
        delay = random.uniform(self._delay_min, self._delay_max)
        logger.debug("anti_detect_delay", delay_seconds=round(delay, 2), source="anti_detect")
        await asyncio.sleep(delay)

    def get_random_user_agent(self) -> str:
        """Return a random user agent string."""
        return random.choice(self.USER_AGENTS)

    def get_proxy_config(self) -> dict[str, str] | None:
        """Return proxy configuration if PROXY_URL is set."""
        if settings.PROXY_URL:
            return {"server": settings.PROXY_URL}
        return None

    async def configure_context(self, context: Any) -> None:
        """
        Apply anti-detection settings to a Playwright BrowserContext.

        Args:
            context: Playwright BrowserContext to configure.
        """
        # This is a no-op placeholder — actual context manipulation
        # happens at context creation time via the browser.new_context() params
        pass

    @property
    def pages_remaining(self) -> int:
        """Pages remaining in current hour window."""
        self._reset_hour_if_needed()
        return max(0, self._max_pages_per_hour - self._pages_this_hour)
