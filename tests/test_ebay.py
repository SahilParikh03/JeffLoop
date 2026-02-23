"""Tests for the eBay Browse API client (Phase 4 — Stream 3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import src.pipeline.ebay as ebay_module
from src.pipeline.ebay import eBayClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

MOCK_TOKEN_RESPONSE = {
    "access_token": "test-access-token-abc123",
    "expires_in": 7200,
    "token_type": "Application Access Token",
}

MOCK_SEARCH_RESPONSE = {
    "itemSummaries": [
        {
            "itemId": "v1|123|0",
            "title": "Charizard ex 199/165 151 PSA 10",
            "price": {"value": "45.99", "currency": "USD"},
            "condition": "Used",
            "itemWebUrl": "https://www.ebay.com/itm/123",
            "itemCreationDate": "2026-02-20T10:00:00.000Z",
        },
        {
            "itemId": "v1|124|0",
            "title": "Charizard ex 199/165 151 NM",
            "price": {"value": "38.00", "currency": "USD"},
            "condition": "Used",
            "itemWebUrl": "https://www.ebay.com/itm/124",
            "itemCreationDate": "2026-02-21T10:00:00.000Z",
        },
        {
            "itemId": "v1|125|0",
            "title": "Charizard ex 199/165 Raw NM",
            "price": {"value": "55.00", "currency": "USD"},
            "condition": "Used",
            "itemWebUrl": "https://www.ebay.com/itm/125",
            "itemCreationDate": "2026-02-22T10:00:00.000Z",
        },
    ],
    "total": 3,
}


def _reset_token_cache() -> None:
    """Reset module-level token cache between tests."""
    ebay_module._TOKEN_CACHE["access_token"] = None
    ebay_module._TOKEN_CACHE["expires_at"] = datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Token fetch tests
# ---------------------------------------------------------------------------


class TesteBayClientOAuth:
    def setup_method(self) -> None:
        _reset_token_cache()

    @pytest.mark.asyncio
    async def test_token_fetch_happy_path(self) -> None:
        """Successful token fetch returns access token string."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "test-app-id"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "test-cert-id"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                async with eBayClient() as client:
                    token = await client._get_access_token()

        assert token == "test-access-token-abc123"

    @pytest.mark.asyncio
    async def test_token_is_cached_second_call_skips_request(self) -> None:
        """Second call within TTL uses cached token without an HTTP request."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "test-app-id"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "test-cert-id"
        ):
            with respx.mock:
                route = respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                async with eBayClient() as client:
                    t1 = await client._get_access_token()
                    t2 = await client._get_access_token()

        assert t1 == t2 == "test-access-token-abc123"
        # Only one HTTP call (second was served from cache)
        assert route.call_count == 1

    @pytest.mark.asyncio
    async def test_expired_token_triggers_refresh(self) -> None:
        """An expired cached token triggers a new HTTP request."""
        # Pre-seed cache with an expired token
        ebay_module._TOKEN_CACHE["access_token"] = "old-token"
        ebay_module._TOKEN_CACHE["expires_at"] = datetime.now(timezone.utc) - timedelta(
            seconds=10
        )

        new_response = {**MOCK_TOKEN_RESPONSE, "access_token": "new-token-refreshed"}

        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "test-app-id"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "test-cert-id"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=new_response)
                )
                async with eBayClient() as client:
                    token = await client._get_access_token()

        assert token == "new-token-refreshed"

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_empty_string(self) -> None:
        """Empty EBAY_APP_ID or EBAY_CERT_ID returns '' without HTTP call."""
        with patch.object(ebay_module.settings, "EBAY_APP_ID", ""), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", ""
        ):
            async with eBayClient() as client:
                token = await client._get_access_token()

        assert token == ""


# ---------------------------------------------------------------------------
# Search sold listings tests
# ---------------------------------------------------------------------------


class TesteBaySearchSoldListings:
    def setup_method(self) -> None:
        _reset_token_cache()

    @pytest.mark.asyncio
    async def test_happy_path_returns_listings(self) -> None:
        """Happy path: search returns structured listing dicts."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
                )
                async with eBayClient() as client:
                    results = await client.search_sold_listings("Charizard ex")

        assert len(results) == 3
        assert results[0]["price_usd"] == Decimal("45.99")
        assert results[0]["listing_url"] == "https://www.ebay.com/itm/123"
        assert results[1]["price_usd"] == Decimal("38.00")

    @pytest.mark.asyncio
    async def test_empty_results_returns_empty_list(self) -> None:
        """Search with no items returns empty list."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json={"itemSummaries": [], "total": 0})
                )
                async with eBayClient() as client:
                    results = await client.search_sold_listings("NonExistentCard12345")

        assert results == []

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self) -> None:
        """HTTP 500 from eBay returns [] gracefully."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(500, text="Internal Server Error")
                )
                async with eBayClient() as client:
                    results = await client.search_sold_listings("Charizard ex")

        assert results == []


# ---------------------------------------------------------------------------
# get_market_price tests
# ---------------------------------------------------------------------------


class TesteBayGetMarketPrice:
    def setup_method(self) -> None:
        _reset_token_cache()

    @pytest.mark.asyncio
    async def test_median_calculation_odd_count(self) -> None:
        """Three prices → median is the middle value."""
        # Prices: 38.00, 45.99, 55.00 → sorted: 38, 45.99, 55 → median = 45.99
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_SEARCH_RESPONSE)
                )
                async with eBayClient() as client:
                    price = await client.get_market_price("sv1-199", "Charizard ex")

        assert price == Decimal("45.99")

    @pytest.mark.asyncio
    async def test_median_calculation_even_count(self) -> None:
        """Two prices → median is the average of the two."""
        mock_two = {
            "itemSummaries": [
                {"itemId": "a", "price": {"value": "40.00"}, "condition": "Used"},
                {"itemId": "b", "price": {"value": "60.00"}, "condition": "Used"},
            ]
        }
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json=mock_two)
                )
                async with eBayClient() as client:
                    price = await client.get_market_price("sv1-1", "test card")

        assert price == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_no_listings_returns_none(self) -> None:
        """No listings found → returns None."""
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json={"itemSummaries": []})
                )
                async with eBayClient() as client:
                    price = await client.get_market_price("sv1-1", "no results card")

        assert price is None

    @pytest.mark.asyncio
    async def test_listings_with_null_prices_ignored(self) -> None:
        """Listings with missing price are excluded from median."""
        mock_with_nulls = {
            "itemSummaries": [
                {"itemId": "a", "price": {"value": "100.00"}, "condition": "Used"},
                {"itemId": "b", "price": None, "condition": "Used"},  # no price
                {"itemId": "c", "condition": "Used"},  # missing price entirely
            ]
        }
        with patch.object(
            ebay_module.settings, "EBAY_APP_ID", "app"
        ), patch.object(
            ebay_module.settings, "EBAY_CERT_ID", "cert"
        ):
            with respx.mock:
                respx.post(OAUTH_URL).mock(
                    return_value=httpx.Response(200, json=MOCK_TOKEN_RESPONSE)
                )
                respx.get(BROWSE_URL).mock(
                    return_value=httpx.Response(200, json=mock_with_nulls)
                )
                async with eBayClient() as client:
                    price = await client.get_market_price("sv1-1", "test")

        # Only one valid price: 100.00
        assert price == Decimal("100.00")
