"""
TCG Radar — pokemontcg.io API Client (Layer 1)

Fetches card metadata from the pokemontcg.io v2 API. Critical data:
- Regulation marks → Rotation Calendar (Section 7)
- Set release dates → Maturity Decay (Section 4.2.2)
- Card IDs → Variant ID Validation (Section 4.7)
- TCGPlayer/Cardmarket URLs → Deep Links

Base URL: https://api.pokemontcg.io/v2/
Pagination: page + pageSize (max 250 per page)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

import httpx
import structlog
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# API Configuration
# ---------------------------------------------------------------------------
BASE_URL = "https://api.pokemontcg.io/v2"
MAX_PAGE_SIZE = 250

# ---------------------------------------------------------------------------
# Pydantic Response Models
# ---------------------------------------------------------------------------


class Legality(BaseModel):
    """Format legality status."""
    standard: str | None = None
    expanded: str | None = None


class TCGPlayerData(BaseModel):
    """TCGPlayer-specific data from pokemontcg.io."""
    url: str | None = None


class CardmarketData(BaseModel):
    """Cardmarket-specific data from pokemontcg.io."""
    url: str | None = None


class SetInfo(BaseModel):
    """Set metadata from pokemontcg.io."""
    id: str = Field(..., description="Set code (e.g., 'sv1')")
    name: str = Field(..., description="Set name (e.g., 'Scarlet & Violet')")
    releaseDate: str | None = Field(default=None, description="Release date YYYY/MM/DD")
    regulationMark: str | None = Field(default=None, description="Default regulation mark for set")

    @field_validator("releaseDate", mode="before")
    @classmethod
    def parse_date_string(cls, v: Any) -> str | None:
        """Normalize date format."""
        if v is None or v == "":
            return None
        return str(v)

    def get_release_date(self) -> date | None:
        """Parse release date string to date object."""
        if not self.releaseDate:
            return None
        try:
            # pokemontcg.io uses YYYY/MM/DD format
            return date.fromisoformat(self.releaseDate.replace("/", "-"))
        except ValueError:
            logger.warning(
                "pokemontcg_invalid_release_date",
                set_id=self.id,
                raw_date=self.releaseDate,
            )
            return None


class CardData(BaseModel):
    """
    Card metadata from pokemontcg.io.

    The card ID is in canonical format: "{set_code}-{card_number}"
    This is the source of truth for Variant ID Validation (Section 4.7).
    """
    id: str = Field(..., description="Canonical card ID: {set_code}-{card_number}")
    name: str = Field(..., description="Card name")
    number: str = Field(..., description="Card number within set")
    set: SetInfo = Field(..., description="Set metadata")
    regulationMark: str | None = Field(default=None, description="Regulation mark (G, H, etc.)")
    legalities: Legality | None = Field(default=None, description="Format legalities")
    tcgplayer: TCGPlayerData | None = Field(default=None)
    cardmarket: CardmarketData | None = Field(default=None)
    images: dict[str, str] | None = Field(default=None, description="Card images")

    @property
    def image_url(self) -> str | None:
        """Get the best available image URL."""
        if self.images:
            return self.images.get("large") or self.images.get("small")
        return None


class CardListResponse(BaseModel):
    """Paginated response from pokemontcg.io cards endpoint."""
    data: list[CardData] = Field(default_factory=list)
    page: int = Field(default=1)
    pageSize: int = Field(default=250)
    count: int = Field(default=0)
    totalCount: int = Field(default=0)


class SetResponse(BaseModel):
    """Response from pokemontcg.io sets endpoint."""
    data: SetInfo


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------


class PokemonTCGClient:
    """
    Async client for the pokemontcg.io v2 API.

    Handles pagination automatically for large result sets (max 250 per page).

    Usage:
        async with PokemonTCGClient() as client:
            card = await client.fetch_card("sv1-25")
            cards = await client.fetch_set_cards("sv1")
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ):
        self._api_key = api_key or settings.POKEMONTCG_API_KEY
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> PokemonTCGClient:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-Api-Key"] = self._api_key
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=headers,
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a GET request with retry logic and exponential backoff."""
        import asyncio

        assert self._client is not None, "Client not initialized. Use 'async with'."

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(path, params=params)

                if response.status_code == 429:
                    wait_time = self._base_backoff * (2 ** attempt)
                    logger.warning(
                        "pokemontcg_rate_limited",
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
                    "pokemontcg_http_error",
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
                    "pokemontcg_request_error",
                    error=str(e),
                    attempt=attempt + 1,
                    path=path,
                )
                wait_time = self._base_backoff * (2 ** attempt)
                await asyncio.sleep(wait_time)
                continue

        raise RuntimeError(
            f"pokemontcg.io API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def fetch_card(self, card_id: str) -> CardData:
        """
        Fetch metadata for a single card by its pokemontcg.io ID.

        Args:
            card_id: Canonical ID in format "{set_code}-{card_number}" (e.g., "sv1-25").

        Returns:
            CardData with metadata, regulation mark, URLs.
        """
        logger.info("pokemontcg_fetch_card", card_id=card_id)

        data = await self._request(f"/cards/{card_id}")
        card = CardData.model_validate(data.get("data", data))

        logger.info(
            "pokemontcg_fetch_card_complete",
            card_id=card.id,
            card_name=card.name,
            regulation_mark=card.regulationMark,
        )
        return card

    async def fetch_set_cards(self, set_code: str) -> list[CardData]:
        """
        Fetch all cards in a set, handling pagination automatically.

        Args:
            set_code: Set code (e.g., "sv1").

        Returns:
            List of all CardData in the set.
        """
        logger.info("pokemontcg_fetch_set", set_code=set_code)

        all_cards: list[CardData] = []
        page = 1

        while True:
            data = await self._request(
                "/cards",
                params={
                    "q": f"set.id:{set_code}",
                    "page": page,
                    "pageSize": MAX_PAGE_SIZE,
                },
            )

            response = CardListResponse.model_validate(data)
            all_cards.extend(response.data)

            logger.debug(
                "pokemontcg_fetch_set_page",
                set_code=set_code,
                page=page,
                page_count=response.count,
                total=response.totalCount,
                fetched_so_far=len(all_cards),
            )

            # Check if we've fetched all cards
            if len(all_cards) >= response.totalCount:
                break
            page += 1

        logger.info(
            "pokemontcg_fetch_set_complete",
            set_code=set_code,
            total_cards=len(all_cards),
        )
        return all_cards

    async def fetch_set_info(self, set_code: str) -> SetInfo:
        """
        Fetch set metadata including release date.

        The release date is critical for Maturity Decay calculation (Section 4.2.2):
        set_age = today - set.releaseDate

        Args:
            set_code: Set code (e.g., "sv1").

        Returns:
            SetInfo with release date, regulation mark, etc.
        """
        logger.info("pokemontcg_fetch_set_info", set_code=set_code)

        data = await self._request(f"/sets/{set_code}")
        response = SetResponse.model_validate(data)

        logger.info(
            "pokemontcg_fetch_set_info_complete",
            set_code=set_code,
            set_name=response.data.name,
            release_date=response.data.releaseDate,
        )
        return response.data

    async def store_metadata(
        self,
        cards: list[CardData],
        session: AsyncSession,
    ) -> int:
        """
        Upsert card metadata into the card_metadata table.

        Uses PostgreSQL ON CONFLICT for atomic upsert keyed by card_id.

        Args:
            cards: Card data to store.
            session: Async database session.

        Returns:
            Number of rows upserted.
        """
        if not cards:
            return 0

        count = 0
        for card in cards:
            stmt = text("""
                INSERT INTO card_metadata (
                    card_id, name, set_code, set_name, card_number,
                    regulation_mark, set_release_date,
                    legality_standard, legality_expanded,
                    tcgplayer_url, cardmarket_url, image_url,
                    last_updated
                ) VALUES (
                    :card_id, :name, :set_code, :set_name, :card_number,
                    :regulation_mark, :set_release_date,
                    :legality_standard, :legality_expanded,
                    :tcgplayer_url, :cardmarket_url, :image_url,
                    :last_updated
                )
                ON CONFLICT (card_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    set_code = EXCLUDED.set_code,
                    set_name = EXCLUDED.set_name,
                    card_number = EXCLUDED.card_number,
                    regulation_mark = EXCLUDED.regulation_mark,
                    set_release_date = EXCLUDED.set_release_date,
                    legality_standard = EXCLUDED.legality_standard,
                    legality_expanded = EXCLUDED.legality_expanded,
                    tcgplayer_url = EXCLUDED.tcgplayer_url,
                    cardmarket_url = EXCLUDED.cardmarket_url,
                    image_url = EXCLUDED.image_url,
                    last_updated = EXCLUDED.last_updated
            """)

            release_date = card.set.get_release_date() if card.set else None

            await session.execute(
                stmt,
                {
                    "card_id": card.id,
                    "name": card.name,
                    "set_code": card.set.id,
                    "set_name": card.set.name,
                    "card_number": card.number,
                    "regulation_mark": card.regulationMark,
                    "set_release_date": release_date,
                    "legality_standard": card.legalities.standard if card.legalities else None,
                    "legality_expanded": card.legalities.expanded if card.legalities else None,
                    "tcgplayer_url": card.tcgplayer.url if card.tcgplayer else None,
                    "cardmarket_url": card.cardmarket.url if card.cardmarket else None,
                    "image_url": card.image_url,
                    "last_updated": datetime.now(timezone.utc),
                },
            )
            count += 1

        await session.commit()

        logger.info(
            "pokemontcg_metadata_stored",
            count=count,
            source="pokemontcg",
        )
        return count
