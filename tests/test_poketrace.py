"""
Tests for PokeTrace API client (src/pipeline/poketrace.py).

Covers:
- Client initialization and configuration
- fetch_card_velocity: success, no data, HTTP errors
- fetch_set_velocity: success, empty list
- store_velocity: SQL upsert
- Pydantic model validation and defaults
- Retry logic: 429 rate-limiting, 500 server error
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.pipeline.poketrace import (
    PokeTraceCardResponse,
    PokeTraceClient,
    PokeTraceVelocityData,
)


# ---------------------------------------------------------------------------
# DB Fixture — minimal market_prices table in SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite DB with a minimal market_prices table."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.execute(
            text("""
                CREATE TABLE market_prices (
                    card_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    price_usd DECIMAL(10,2),
                    price_eur DECIMAL(10,2),
                    condition TEXT,
                    seller_id TEXT,
                    seller_rating DECIMAL(5,2),
                    seller_sales INTEGER,
                    sales_30d INTEGER,
                    active_listings INTEGER,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (card_id, source)
                )
            """)
        )

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 1: Client initializes with default settings
# ---------------------------------------------------------------------------


def test_poketrace_client_init() -> None:
    """Client uses settings defaults when no overrides are given."""
    client = PokeTraceClient()

    assert client._api_key == settings.POKETRACE_API_KEY
    assert client._base_url == settings.POKETRACE_BASE_URL
    assert client._max_retries == 3
    assert client._base_backoff == 1.0
    assert client._client is None  # Not yet opened


# ---------------------------------------------------------------------------
# Test 2: Client uses custom base_url when provided
# ---------------------------------------------------------------------------


def test_poketrace_client_custom_url() -> None:
    """Client uses the provided base_url over the default setting."""
    custom_url = "https://staging.poketrace.internal/v2"
    client = PokeTraceClient(api_key="test-key", base_url=custom_url)

    assert client._base_url == custom_url
    assert client._api_key == "test-key"


# ---------------------------------------------------------------------------
# Test 3: fetch_card_velocity — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_card_velocity_success() -> None:
    """fetch_card_velocity returns PokeTraceVelocityData on a valid response."""
    card_id = "sv1-25"
    mock_response = {
        "success": True,
        "data": {
            "card_id": card_id,
            "sales_30d": 150,
            "active_listings": 42,
        },
    }

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/cards/{card_id}/velocity").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with PokeTraceClient() as client:
            result = await client.fetch_card_velocity(card_id)

    assert isinstance(result, PokeTraceVelocityData)
    assert result.card_id == card_id
    assert result.sales_30d == 150
    assert result.active_listings == 42


# ---------------------------------------------------------------------------
# Test 4: fetch_card_velocity — null data returns zero defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_card_velocity_no_data() -> None:
    """When API returns data=null, client returns a zero-default record."""
    card_id = "sv1-999"
    mock_response = {"success": True, "data": None}

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/cards/{card_id}/velocity").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with PokeTraceClient() as client:
            result = await client.fetch_card_velocity(card_id)

    assert result.card_id == card_id
    assert result.sales_30d == 0
    assert result.active_listings == 0


# ---------------------------------------------------------------------------
# Test 5: fetch_card_velocity — 404 raises immediately (no retry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_card_velocity_http_error() -> None:
    """A 404 response raises httpx.HTTPStatusError without retrying."""
    card_id = "sv1-notfound"

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/cards/{card_id}/velocity").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            async with PokeTraceClient() as client:
                await client.fetch_card_velocity(card_id)

    assert exc_info.value.response.status_code == 404


# ---------------------------------------------------------------------------
# Test 6: fetch_set_velocity — success path with multiple cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_set_velocity_success() -> None:
    """fetch_set_velocity parses a list of cards from the set endpoint."""
    set_code = "sv1"
    mock_response = {
        "data": [
            {"card_id": "sv1-1", "sales_30d": 50, "active_listings": 10},
            {"card_id": "sv1-2", "sales_30d": 200, "active_listings": 60},
            {"card_id": "sv1-3", "sales_30d": 15, "active_listings": 5},
        ]
    }

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/sets/{set_code}/velocity").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with PokeTraceClient() as client:
            results = await client.fetch_set_velocity(set_code)

    assert len(results) == 3
    assert all(isinstance(r, PokeTraceVelocityData) for r in results)
    assert results[0].card_id == "sv1-1"
    assert results[1].sales_30d == 200
    assert results[2].active_listings == 5


# ---------------------------------------------------------------------------
# Test 7: fetch_set_velocity — empty data list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_set_velocity_empty() -> None:
    """An empty data array returns an empty list without errors."""
    set_code = "sv99"
    mock_response = {"data": []}

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/sets/{set_code}/velocity").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        async with PokeTraceClient() as client:
            results = await client.fetch_set_velocity(set_code)

    assert results == []


# ---------------------------------------------------------------------------
# Test 8: store_velocity — verifies the SQL upsert executes correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_velocity(db_session: AsyncSession) -> None:
    """store_velocity upserts velocity data into market_prices."""
    velocity_data = PokeTraceVelocityData(
        card_id="sv1-25",
        sales_30d=120,
        active_listings=35,
    )

    client = PokeTraceClient()
    result = await client.store_velocity(velocity_data, db_session)

    assert result is True

    # Verify the row was written
    row = await db_session.execute(
        text("SELECT card_id, source, sales_30d, active_listings FROM market_prices WHERE card_id='sv1-25'")
    )
    fetched = row.fetchone()
    assert fetched is not None
    assert fetched[0] == "sv1-25"
    assert fetched[1] == "poketrace"
    assert fetched[2] == 120
    assert fetched[3] == 35


@pytest.mark.asyncio
async def test_store_velocity_upsert_updates(db_session: AsyncSession) -> None:
    """store_velocity overwrites existing velocity row on conflict."""
    client = PokeTraceClient()
    card_id = "sv1-10"

    # Insert initial
    initial = PokeTraceVelocityData(card_id=card_id, sales_30d=50, active_listings=20)
    await client.store_velocity(initial, db_session)

    # Upsert with new values
    updated = PokeTraceVelocityData(card_id=card_id, sales_30d=99, active_listings=33)
    await client.store_velocity(updated, db_session)

    row = await db_session.execute(
        text(f"SELECT sales_30d, active_listings FROM market_prices WHERE card_id='{card_id}' AND source='poketrace'")
    )
    fetched = row.fetchone()
    assert fetched[0] == 99
    assert fetched[1] == 33


# ---------------------------------------------------------------------------
# Test 9: PokeTraceVelocityData model validation
# ---------------------------------------------------------------------------


def test_velocity_data_model_validation() -> None:
    """Pydantic model parses a valid dict and coerces types correctly."""
    raw = {"card_id": "sv2-150", "sales_30d": "75", "active_listings": "25"}
    model = PokeTraceVelocityData.model_validate(raw)

    assert model.card_id == "sv2-150"
    assert model.sales_30d == 75
    assert model.active_listings == 25


# ---------------------------------------------------------------------------
# Test 10: PokeTraceVelocityData default values
# ---------------------------------------------------------------------------


def test_velocity_data_defaults() -> None:
    """Missing optional fields fall back to zero defaults."""
    model = PokeTraceVelocityData(card_id="sv1-5")

    assert model.sales_30d == 0
    assert model.active_listings == 0


# ---------------------------------------------------------------------------
# Test 11: Retry on 429 rate limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_rate_limit() -> None:
    """Client retries after a 429 and succeeds on the second attempt."""
    card_id = "sv1-42"
    success_payload = {
        "success": True,
        "data": {"card_id": card_id, "sales_30d": 80, "active_listings": 30},
    }

    call_count = 0

    def rate_limit_then_success(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=success_payload)

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        mock.get(f"/cards/{card_id}/velocity").mock(side_effect=rate_limit_then_success)

        # Use zero backoff to keep the test fast
        async with PokeTraceClient(base_backoff=0.0) as client:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.fetch_card_velocity(card_id)

    assert result.card_id == card_id
    assert result.sales_30d == 80
    assert call_count == 2  # First attempt = 429, second = 200


# ---------------------------------------------------------------------------
# Test 12: Retry on 500 server error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_server_error() -> None:
    """Client retries on 5xx errors and raises RuntimeError when all attempts fail."""
    card_id = "sv1-error"

    with respx.mock(base_url=settings.POKETRACE_BASE_URL) as mock:
        # Always return 500
        mock.get(f"/cards/{card_id}/velocity").mock(
            return_value=httpx.Response(500, json={"error": "internal server error"})
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="PokeTrace API request failed"):
                # max_retries=1 → total 2 attempts
                async with PokeTraceClient(max_retries=1, base_backoff=0.0) as client:
                    await client.fetch_card_velocity(card_id)
