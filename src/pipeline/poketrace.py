"""
TCG Radar — PokeTrace API Client (Layer 1)

Fetches card velocity data (Sales_30d, Active_Listings) from PokeTrace API.
Used to calculate Velocity Score (Section 4.2) and unwire the velocity stub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Response Models
# ---------------------------------------------------------------------------


class PokeTraceVelocityData(BaseModel):
    """Velocity data for a single card from PokeTrace."""

    card_id: str = Field(..., description="Card identifier")
    sales_30d: int = Field(default=0, description="Sales in last 30 days")
    active_listings: int = Field(default=0, description="Current active listings")


class PokeTraceCardResponse(BaseModel):
    """API response for a single card lookup."""

    data: PokeTraceVelocityData | None = None
    success: bool = True


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------


class PokeTraceClient:
    """
    Async client for the PokeTrace API.

    Usage:
        async with PokeTraceClient() as client:
            velocity = await client.fetch_card_velocity("sv1-25")
            await client.store_velocity(velocity, session)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ):
        self._api_key = api_key or settings.POKETRACE_API_KEY
        self._base_url = base_url or settings.POKETRACE_BASE_URL
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> PokeTraceClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
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
        """Make an API request with retry logic and exponential backoff."""
        import asyncio

        assert self._client is not None, "Client not initialized. Use 'async with'."

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, params=params)

                if response.status_code == 429:
                    wait_time = self._base_backoff * (2 ** attempt)
                    logger.warning(
                        "poketrace_rate_limited",
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
                    "poketrace_http_error",
                    status_code=e.response.status_code,
                    attempt=attempt + 1,
                    path=path,
                )
                if e.response.status_code >= 500:
                    wait_time = self._base_backoff * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise

            except httpx.RequestError as e:
                last_error = e
                logger.error(
                    "poketrace_request_error",
                    error=str(e),
                    attempt=attempt + 1,
                    path=path,
                )
                wait_time = self._base_backoff * (2 ** attempt)
                await asyncio.sleep(wait_time)
                continue

        raise RuntimeError(
            f"PokeTrace API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def fetch_card_velocity(self, card_id: str) -> PokeTraceVelocityData:
        """
        Fetch velocity data for a single card.

        Args:
            card_id: pokemontcg.io canonical ID (e.g., "sv1-25")

        Returns:
            PokeTraceVelocityData with sales_30d and active_listings.
        """
        logger.info("poketrace_fetch_velocity", card_id=card_id)

        data = await self._request("GET", f"/cards/{card_id}/velocity")
        response = PokeTraceCardResponse.model_validate(data)

        if response.data is None:
            logger.warning("poketrace_no_data", card_id=card_id)
            return PokeTraceVelocityData(card_id=card_id, sales_30d=0, active_listings=0)

        logger.info(
            "poketrace_fetch_velocity_complete",
            card_id=card_id,
            sales_30d=response.data.sales_30d,
            active_listings=response.data.active_listings,
        )
        return response.data

    async def fetch_set_velocity(self, set_code: str) -> list[PokeTraceVelocityData]:
        """
        Fetch velocity data for all cards in a set.

        Args:
            set_code: Set code (e.g., "sv1")

        Returns:
            List of PokeTraceVelocityData.
        """
        logger.info("poketrace_fetch_set", set_code=set_code)

        data = await self._request("GET", f"/sets/{set_code}/velocity")
        cards = data.get("data", [])

        results = []
        for card_data in cards:
            try:
                results.append(PokeTraceVelocityData.model_validate(card_data))
            except Exception as e:
                logger.warning(
                    "poketrace_parse_error",
                    error=str(e),
                    card_data=str(card_data)[:100],
                )

        logger.info(
            "poketrace_fetch_set_complete",
            set_code=set_code,
            results_count=len(results),
        )
        return results

    async def store_velocity(
        self,
        velocity_data: PokeTraceVelocityData,
        session: AsyncSession,
    ) -> bool:
        """
        Upsert velocity data into market_prices.

        Updates the sales_30d and active_listings columns for the given card.
        Uses source='poketrace' for the upsert.

        Args:
            velocity_data: Velocity data to store.
            session: Async database session.

        Returns:
            True if stored successfully.
        """
        stmt = text("""
            INSERT INTO market_prices (card_id, source, sales_30d, active_listings, last_updated)
            VALUES (:card_id, 'poketrace', :sales_30d, :active_listings, :last_updated)
            ON CONFLICT (card_id, source) DO UPDATE SET
                sales_30d = EXCLUDED.sales_30d,
                active_listings = EXCLUDED.active_listings,
                last_updated = EXCLUDED.last_updated
        """)

        await session.execute(
            stmt,
            {
                "card_id": velocity_data.card_id,
                "sales_30d": velocity_data.sales_30d,
                "active_listings": velocity_data.active_listings,
                "last_updated": datetime.now(timezone.utc),
            },
        )
        await session.commit()

        logger.info(
            "poketrace_velocity_stored",
            card_id=velocity_data.card_id,
            sales_30d=velocity_data.sales_30d,
            active_listings=velocity_data.active_listings,
            source="poketrace",
        )
        return True
