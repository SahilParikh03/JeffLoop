"""
TCG Radar — eBay Browse API Client (Section 5)

Fetches US sold listing prices from the eBay Browse API.
Used as a supplementary US price discovery source alongside JustTCG.
Writes to market_prices with source="ebay".

Pattern: Mirrors justtcg.py / poketrace.py.
Authentication: OAuth2 Client Credentials flow, token cached with expiry.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level token cache (mirrors forex.py 15-min cache pattern)
# ---------------------------------------------------------------------------
_TOKEN_CACHE: dict[str, Any] = {
    "access_token": None,
    "expires_at": datetime.min.replace(tzinfo=timezone.utc),
}


class eBayClient:
    """
    eBay Browse API client for US sold listing price discovery.

    OAuth2 Client Credentials flow using EBAY_APP_ID + EBAY_CERT_ID.
    Token is cached in module-level dict until expiry (typically 2 hours).

    Usage:
        async with eBayClient() as client:
            price = await client.get_market_price("sv1-1", "Charizard ex")
    """

    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "eBayClient":
        self._client = httpx.AsyncClient(timeout=15.0)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _get_access_token(self) -> str:
        """
        OAuth2 Client Credentials flow using EBAY_APP_ID + EBAY_CERT_ID.

        Caches token until expiry (with 60-second safety margin) to avoid
        hammering the auth endpoint. Returns empty string if credentials
        are not configured.
        """
        if not settings.EBAY_APP_ID or not settings.EBAY_CERT_ID:
            return ""

        now = datetime.now(timezone.utc)
        if _TOKEN_CACHE["access_token"] and now < _TOKEN_CACHE["expires_at"]:
            return str(_TOKEN_CACHE["access_token"])

        if not self._client:
            return ""

        # Basic auth: base64(APP_ID:CERT_ID)
        credentials = f"{settings.EBAY_APP_ID}:{settings.EBAY_CERT_ID}"
        encoded = base64.b64encode(credentials.encode()).decode()

        try:
            response = await self._client.post(
                settings.EBAY_OAUTH_URL,
                headers={
                    "Authorization": f"Basic {encoded}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
            )
            response.raise_for_status()
            data = response.json()

            token = data.get("access_token", "")
            expires_in = int(data.get("expires_in", 7200))

            # Cache with 60-second safety margin before real expiry
            _TOKEN_CACHE["access_token"] = token
            _TOKEN_CACHE["expires_at"] = now + timedelta(seconds=expires_in - 60)

            logger.info(
                "ebay_token_refreshed",
                expires_in=expires_in,
                source="ebay",
            )
            return token

        except Exception as e:
            logger.error(
                "ebay_token_fetch_failed",
                error=str(e),
                source="ebay",
            )
            return ""

    async def search_sold_listings(
        self, card_name: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Search recently sold eBay listings for a card name.

        GET /buy/browse/v1/item_summary/search
            ?q={card_name}&filter=buyingOptions:{FIXED_PRICE}&limit={limit}

        Returns list of dicts:
            {card_id, price_usd, condition, sold_date, listing_url}

        Returns [] on any error or missing credentials.
        """
        if not self._client:
            return []

        token = await self._get_access_token()
        if not token:
            logger.warning(
                "ebay_search_skipped_no_token",
                card_name=card_name,
                source="ebay",
            )
            return []

        try:
            response = await self._client.get(
                f"{settings.EBAY_BROWSE_URL}/item_summary/search",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "q": card_name,
                    "filter": "buyingOptions:{FIXED_PRICE}",
                    "limit": str(limit),
                },
            )
            response.raise_for_status()
            data = response.json()

            items = data.get("itemSummaries", [])
            results: list[dict[str, Any]] = []

            for item in items:
                price_value = (item.get("price") or {}).get("value")
                try:
                    price_usd = Decimal(str(price_value)) if price_value is not None else None
                except (InvalidOperation, TypeError):
                    price_usd = None

                results.append({
                    "card_id": item.get("itemId", ""),
                    "price_usd": price_usd,
                    "condition": item.get("condition"),
                    "sold_date": item.get("itemCreationDate"),
                    "listing_url": item.get("itemWebUrl", ""),
                })

            logger.info(
                "ebay_search_complete",
                card_name=card_name,
                result_count=len(results),
                source="ebay",
            )
            return results

        except Exception as e:
            logger.error(
                "ebay_search_failed",
                card_name=card_name,
                error=str(e),
                source="ebay",
            )
            return []

    async def get_market_price(
        self, card_id: str, card_name: str
    ) -> Decimal | None:
        """
        Returns median price from recent sold listings.

        Calls search_sold_listings(), extracts USD prices, returns median.
        Returns None if no listings found.

        Args:
            card_id: Card identifier (used for logging / DB writes).
            card_name: Search query for eBay Browse API.
        """
        listings = await self.search_sold_listings(card_name)
        prices = [
            listing["price_usd"]
            for listing in listings
            if listing.get("price_usd") is not None
        ]

        if not prices:
            logger.debug(
                "ebay_no_prices_found",
                card_id=card_id,
                card_name=card_name,
                source="ebay",
            )
            return None

        # Compute median over Decimal values via float conversion
        median_price = Decimal(str(median([float(p) for p in prices]))).quantize(
            Decimal("0.01")
        )
        logger.info(
            "ebay_market_price_calculated",
            card_id=card_id,
            median_price=str(median_price),
            sample_size=len(prices),
            source="ebay",
        )
        return median_price

    async def store_price(
        self,
        card_id: str,
        price_usd: Decimal,
        session: AsyncSession,
    ) -> None:
        """
        Upsert a single eBay market price into market_prices.

        Uses INSERT ... ON CONFLICT (card_id, source) DO UPDATE.
        source is always 'ebay'.

        Args:
            card_id: Card identifier.
            price_usd: Median price in USD.
            session: Async DB session.
        """
        await session.execute(
            text("""
                INSERT INTO market_prices (card_id, source, price_usd, last_updated)
                VALUES (:card_id, 'ebay', :price_usd, now())
                ON CONFLICT (card_id, source)
                DO UPDATE SET price_usd = EXCLUDED.price_usd,
                              last_updated = now()
            """),
            {"card_id": card_id, "price_usd": str(price_usd)},
        )
        await session.commit()

        logger.debug(
            "ebay_price_stored",
            card_id=card_id,
            price_usd=str(price_usd),
            source="ebay",
        )
