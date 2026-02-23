"""
TCG Radar — Social Listening (Layer 3.5)

Monitors keyword frequency on social platforms for spike detection.
A spike is >5x baseline frequency in a 30-minute rolling window.

MVP: Reddit JSON API only (no OAuth needed).
Twitter/Discord monitoring stubbed behind a platform adapter for Phase 3.

Gated by ENABLE_LAYER_35_SOCIAL feature flag.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

# Rolling window for frequency counting
_WINDOW_MINUTES: int = 30


class PlatformAdapter(Protocol):
    """Protocol for social platform adapters (Phase 3 extensibility)."""

    async def fetch_mentions(self, keywords: list[str]) -> list[dict[str, Any]]:
        ...


class RedditAdapter:
    """
    Reddit JSON API adapter (no OAuth required).

    Fetches recent posts from specified subreddits and counts keyword matches.
    """

    SUBREDDITS = ["PokemonTCG", "PkmnTCGDeals", "pokemoncardvalue"]
    USER_AGENT = "TCGRadar/0.1 (Social Listener)"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RedditAdapter:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.USER_AGENT},
            timeout=15.0,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch_mentions(self, keywords: list[str]) -> list[dict[str, Any]]:
        """
        Fetch recent Reddit posts mentioning any of the keywords.

        Returns list of dicts with: keyword, title, created_utc, subreddit
        """
        if not self._client:
            return []

        mentions: list[dict[str, Any]] = []
        keywords_lower = [k.lower() for k in keywords]

        for subreddit in self.SUBREDDITS:
            try:
                url = f"https://www.reddit.com/r/{subreddit}/new.json?limit=25"
                response = await self._client.get(url)
                response.raise_for_status()
                data = response.json()

                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    post_data = post.get("data", {})
                    title = (post_data.get("title") or "").lower()
                    selftext = (post_data.get("selftext") or "").lower()
                    combined = f"{title} {selftext}"

                    for kw in keywords_lower:
                        if kw in combined:
                            mentions.append({
                                "keyword": kw,
                                "title": post_data.get("title", ""),
                                "created_utc": post_data.get("created_utc", 0),
                                "subreddit": subreddit,
                            })

            except Exception as e:
                logger.error(
                    "reddit_fetch_error",
                    subreddit=subreddit,
                    error=str(e),
                    source="social_listener",
                )

        return mentions


class SocialListener:
    """
    Monitors social platforms for keyword frequency spikes.

    A spike is detected when keyword frequency exceeds SOCIAL_SPIKE_MULTIPLIER
    (default 5x) times the baseline in a rolling window.

    Gated by ENABLE_LAYER_35_SOCIAL feature flag.
    """

    def __init__(
        self,
        spike_multiplier: float | None = None,
    ) -> None:
        self._spike_multiplier = spike_multiplier or float(
            getattr(settings, "SOCIAL_SPIKE_MULTIPLIER", 5.0)
        )
        # keyword -> list of timestamps
        self._mention_history: dict[str, list[datetime]] = defaultdict(list)
        # keyword -> baseline count per window (rolling average)
        self._baselines: dict[str, float] = defaultdict(lambda: 1.0)

    def _prune_old_mentions(self, keyword: str) -> None:
        """Remove mentions outside the rolling window."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_WINDOW_MINUTES)
        self._mention_history[keyword] = [
            ts for ts in self._mention_history[keyword] if ts > cutoff
        ]

    def record_mentions(self, keyword: str, count: int) -> None:
        """Record new mentions for a keyword."""
        now = datetime.now(timezone.utc)
        for _ in range(count):
            self._mention_history[keyword].append(now)

    def get_current_frequency(self, keyword: str) -> int:
        """Get mention count in the current rolling window."""
        self._prune_old_mentions(keyword)
        return len(self._mention_history[keyword])

    def update_baseline(self, keyword: str, historical_avg: float) -> None:
        """Update the baseline frequency for a keyword."""
        self._baselines[keyword] = max(historical_avg, 1.0)  # Floor at 1 to avoid div/0

    def is_spike(self, keyword: str) -> bool:
        """
        Check if current frequency is a spike (>5x baseline).

        Returns True if current_frequency > spike_multiplier * baseline.
        """
        current = self.get_current_frequency(keyword)
        baseline = self._baselines[keyword]
        return current > self._spike_multiplier * baseline

    async def scan_for_spikes(
        self,
        keywords: list[str],
        adapter: PlatformAdapter | None = None,
    ) -> list[str]:
        """
        Scan social platforms for keyword spikes.

        Args:
            keywords: Card names or keywords to monitor.
            adapter: Platform adapter to use. Defaults to RedditAdapter.

        Returns:
            List of keywords that are currently spiking.
        """
        if not settings.ENABLE_LAYER_35_SOCIAL:
            logger.debug(
                "social_listener_disabled",
                source="social_listener",
            )
            return []

        spiking: list[str] = []

        try:
            if adapter is None:
                async with RedditAdapter() as reddit:
                    mentions = await reddit.fetch_mentions(keywords)
            else:
                mentions = await adapter.fetch_mentions(keywords)

            # Count mentions per keyword
            keyword_counts: dict[str, int] = defaultdict(int)
            for mention in mentions:
                keyword_counts[mention["keyword"]] += 1

            # Record and check for spikes
            for keyword, count in keyword_counts.items():
                self.record_mentions(keyword, count)
                if self.is_spike(keyword):
                    spiking.append(keyword)
                    logger.info(
                        "social_spike_detected",
                        keyword=keyword,
                        current_frequency=self.get_current_frequency(keyword),
                        baseline=self._baselines[keyword],
                        source="social_listener",
                    )

        except Exception as e:
            logger.error(
                "social_scan_failed",
                error=str(e),
                source="social_listener",
            )

        return spiking
