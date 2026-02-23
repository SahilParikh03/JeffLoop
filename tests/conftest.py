"""
TCG Radar — Shared pytest Fixtures & Configuration

Provides common fixtures for all test modules:
- Mock HTTP client (respx)
- Mock database session
- Mock API response data
- Async test support via pytest-asyncio
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.models.base import Base


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio backend for anyio tests."""
    return "asyncio"


# ---------------------------------------------------------------------------
# Mock Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Mock async database session using aiosqlite in-memory.

    Creates a fresh database for each test, ensuring isolation.
    """
    # Use in-memory SQLite with asyncpg async driver
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session factory
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

    # Cleanup
    await engine.dispose()


@pytest.fixture
def mock_http_client() -> httpx.Client:
    """
    Mock HTTP client with respx interceptor.

    All HTTP requests are intercepted and must be explicitly mocked.
    Prevents accidental calls to live APIs in tests.
    """
    with respx.mock:
        yield httpx.Client()


@pytest.fixture
async def mock_async_http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Mock async HTTP client with respx interceptor.

    For async I/O operations (API calls, Playwright interactions).
    """
    with respx.mock:
        async with httpx.AsyncClient() as client:
            yield client


# ---------------------------------------------------------------------------
# Fixture Loaders
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def load_mock_justtcg() -> dict:
    """Load mock JustTCG API response from fixtures/mock_justtcg.json."""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_justtcg.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def load_mock_pokemontcg() -> dict:
    """Load mock pokemontcg.io API response from fixtures/mock_pokemontcg.json."""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_pokemontcg.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def load_mock_cardmarket() -> dict:
    """Load mock Cardmarket scrape response from fixtures/mock_cardmarket_response.json."""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_cardmarket_response.json"
    with open(fixture_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Utility Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    """Current timestamp for tests."""
    return datetime.utcnow()
