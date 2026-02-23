"""
TCG Radar — JustTCG API Client (Layer 1)

Fetches cross-market card prices from the JustTCG API via RapidAPI.
Provides TCGPlayer (USD) and Cardmarket (EUR) prices in a single call.

The API is polled on a fixed cadence (6hr for free tier). This module
handles only fetching and storing — scheduling is in pipeline/scheduler.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import httpx
import structlog
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# RapidAPI Configuration
# ---------------------------------------------------------------------------
RAPIDAPI_HOST = "justtcg.p.rapidapi.com"
RAPIDAPI_BASE_URL = f"https://{RAPIDAPI_HOST}"

# ---------------------------------------------------------------------------
# Pydantic Response Models
# ---------------------------------------------------------------------------


class JustTCGPriceData(BaseModel):
    """Price data for a single card from JustTCG."""

    card_id: str = Field(..., description="Card identifier")
    name: str = Field(default="", description="Card name")
    set_name: str = Field(default="", description="Set name")
    price_usd: Decimal | None = Field(default=None, description="TCGPlayer price in USD")
    price_eur: Decimal | None = Field(default=None, description="Cardmarket price in EUR")
    condition: str | None = Field(default=None, description="Card condition if available")

    @field_validator("price_usd", "price_eur", mode="before")
    @classmethod
    def parse_decimal(cls, v: Any) -> Decimal | None:
        """Safely convert price values to Decimal. Never use float for money."""
        if v is None or v == "" or v == "N/A":
            return None
        try:
            return Decimal(str(v))
        except (InvalidOperation, ValueError):
            return None


class JustTCGSearchResponse(BaseModel):
    """Top-level response from JustTCG search endpoint."""

    results: list[JustTCGPriceData] = Field(default_factory=list)
    total: int = Field(default=0)


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------


class JustTCGClient:
    """
    Async client for the JustTCG API (via RapidAPI).

    Usage:
        async with JustTCGClient() as client:
            prices = await client.fetch_card_prices("Charizard ex")
            count = await client.store_prices(prices, db_session)
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ):
        self._api_key = api_key or settings.JUSTTCG_API_KEY
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> JustTCGClient:
        self._client = httpx.AsyncClient(
            base_url=RAPIDAPI_BASE_URL,
            headers={
                "X-RapidAPI-Key": self._api_key,
                "X-RapidAPI-Host": RAPIDAPI_HOST,
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make an API request with retry logic and exponential backoff.

        Handles 429 (rate limit) responses by backing off exponentially.
        """
        import asyncio

        assert self._client is not None, "Client not initialized. Use 'async with'."

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, params=params)

                if response.status_code == 429:
                    # Rate limited — back off
                    wait_time = self._base_backoff * (2 ** attempt)
                    logger.warning(
                        "justtcg_rate_limited",
                        attempt=attempt + 1,
                        wait_seconds=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.error(
                    "justtcg_http_error",
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                    path=path,
                )
                if e.response.status_code >= 500:
                    # Server error — retry with backoff
                    wait_time = self._base_backoff * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise

            except httpx.RequestError as e:
                last_error = e
                logger.error(
                    "justtcg_request_error",
                    error=str(e),
                    attempt=attempt + 1,
                    path=path,
                )
                wait_time = self._base_backoff * (2 ** attempt)
                await asyncio.sleep(wait_time)
                continue

        raise RuntimeError(
            f"JustTCG API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def fetch_card_prices(self, card_name: str) -> list[JustTCGPriceData]:
        """
        Search for a card by name and return price data.

        Args:
            card_name: Card name to search for (e.g., "Charizard ex").

        Returns:
            List of JustTCGPriceData with TCGPlayer USD and Cardmarket EUR prices.
        """
        logger.info("justtcg_fetch_card", card_name=card_name)

        data = await self._request("GET", "/search", params={"q": card_name})
        response = JustTCGSearchResponse.model_validate(data)

        logger.info(
            "justtcg_fetch_card_complete",
            card_name=card_name,
            results_count=len(response.results),
        )
        return response.results

    async def fetch_set_prices(self, set_code: str) -> list[JustTCGPriceData]:
        """
        Fetch all card prices for a given set.

        Args:
            set_code: Set code (e.g., "sv1" for Scarlet & Violet base).

        Returns:
            List of JustTCGPriceData for all cards in the set.
        """
        logger.info("justtcg_fetch_set", set_code=set_code)

        data = await self._request("GET", "/set", params={"code": set_code})
        response = JustTCGSearchResponse.model_validate(data)

        logger.info(
            "justtcg_fetch_set_complete",
            set_code=set_code,
            results_count=len(response.results),
        )
        return response.results

    async def store_prices(
        self,
        prices: list[JustTCGPriceData],
        session: AsyncSession,
    ) -> int:
        """
        Upsert price data into the market_prices table.

        Uses PostgreSQL ON CONFLICT for atomic upsert. Each price record is
        keyed by (card_id, source='justtcg').

        Args:
            prices: Price data to store.
            session: Async database session.

        Returns:
            Number of rows upserted.
        """
        if not prices:
            return 0

        count = 0
        for price in prices:
            if price.price_usd is None and price.price_eur is None:
                logger.debug(
                    "justtcg_skip_no_prices",
                    card_id=price.card_id,
                )
                continue

            stmt = text("""
                INSERT INTO market_prices (card_id, source, price_usd, price_eur, condition, last_updated)
                VALUES (:card_id, 'justtcg', :price_usd, :price_eur, :condition, :last_updated)
                ON CONFLICT (card_id, source) DO UPDATE SET
                    price_usd = EXCLUDED.price_usd,
                    price_eur = EXCLUDED.price_eur,
                    condition = EXCLUDED.condition,
                    last_updated = EXCLUDED.last_updated
            """)

            await session.execute(
                stmt,
                {
                    "card_id": price.card_id,
                    "price_usd": price.price_usd,
                    "price_eur": price.price_eur,
                    "condition": price.condition,
                    "last_updated": datetime.now(timezone.utc),
                },
            )

            # Append to price_history (append-only, no upsert)
            history_stmt = text("""
                INSERT INTO price_history (card_id, source, price_usd, price_eur, recorded_at)
                VALUES (:card_id, 'justtcg', :price_usd, :price_eur, :recorded_at)
            """)
            await session.execute(history_stmt, {
                "card_id": price.card_id,
                "price_usd": price.price_usd,
                "price_eur": price.price_eur,
                "recorded_at": datetime.now(timezone.utc),
            })

            count += 1

        await session.commit()

        logger.info(
            "justtcg_prices_stored",
            count=count,
            source="justtcg",
        )
        return count
