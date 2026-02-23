"""
TCG Radar — Limitless TCG Client (Section 11)

Fetches tournament results and decklists from Limitless TCG API.
Critical for event-driven signals and synergy detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

from src.config import settings

logger = structlog.get_logger(__name__)


class DecklistEntry(BaseModel):
    """A single card in a decklist."""

    card_name: str
    card_id: str | None = None
    count: int = 1


class TournamentResult(BaseModel):
    """A tournament placement with decklist."""

    tournament_id: str
    tournament_name: str
    player_name: str = ""
    placement: int
    deck_name: str = ""
    decklist: list[DecklistEntry] = Field(default_factory=list)
    date: str = ""


class LimitlessTCGClient:
    """
    Async client for Limitless TCG tournament data.

    Usage:
        async with LimitlessTCGClient() as client:
            results = await client.fetch_recent_results()
    """

    BASE_URL = "https://play.limitlesstcg.com/api"

    def __init__(
        self,
        base_url: str | None = None,
        max_retries: int = 3,
    ) -> None:
        self._base_url = base_url or self.BASE_URL
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> LimitlessTCGClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make a GET request with basic retry."""
        import asyncio

        assert self._client is not None, "Client not initialized. Use 'async with'."

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500:
                    await asyncio.sleep(1.0 * (2**attempt))
                    continue
                raise
            except httpx.RequestError as e:
                last_error = e
                await asyncio.sleep(1.0 * (2**attempt))
                continue

        raise RuntimeError(
            f"Limitless API request failed after {self._max_retries + 1} attempts"
        ) from last_error

    async def fetch_recent_tournaments(
        self, game: str = "pokemon", limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Fetch recent tournament listings.

        Args:
            game: Game type (default "pokemon")
            limit: Max tournaments to fetch

        Returns:
            List of tournament metadata dicts.
        """
        logger.info(
            "limitless_fetch_tournaments", game=game, limit=limit, source="limitless"
        )
        data = await self._request("/tournaments", params={"game": game, "limit": limit})
        tournaments = data.get("data", data) if isinstance(data, dict) else data

        if isinstance(tournaments, list):
            logger.info(
                "limitless_fetch_tournaments_complete",
                count=len(tournaments),
                source="limitless",
            )
            return tournaments
        return []

    async def fetch_tournament_results(
        self, tournament_id: str
    ) -> list[TournamentResult]:
        """
        Fetch results and decklists for a specific tournament.

        Args:
            tournament_id: Tournament identifier.

        Returns:
            List of TournamentResult with placements and decklists.
        """
        logger.info(
            "limitless_fetch_results",
            tournament_id=tournament_id,
            source="limitless",
        )

        data = await self._request(f"/tournaments/{tournament_id}/results")
        results_raw = data.get("data", data) if isinstance(data, dict) else data

        results: list[TournamentResult] = []
        if isinstance(results_raw, list):
            for entry in results_raw:
                try:
                    decklist_raw = entry.get("decklist", [])
                    decklist = []
                    if isinstance(decklist_raw, list):
                        for card in decklist_raw:
                            if isinstance(card, dict):
                                decklist.append(
                                    DecklistEntry(
                                        card_name=card.get("name", ""),
                                        card_id=card.get("id"),
                                        count=card.get("count", 1),
                                    )
                                )

                    results.append(
                        TournamentResult(
                            tournament_id=tournament_id,
                            tournament_name=entry.get("tournament_name", ""),
                            player_name=entry.get("player", ""),
                            placement=entry.get("placement", 0),
                            deck_name=entry.get("deck_name", ""),
                            decklist=decklist,
                            date=entry.get("date", ""),
                        )
                    )
                except Exception as e:
                    logger.warning(
                        "limitless_parse_error",
                        tournament_id=tournament_id,
                        error=str(e),
                        source="limitless",
                    )

        logger.info(
            "limitless_fetch_results_complete",
            tournament_id=tournament_id,
            count=len(results),
            source="limitless",
        )
        return results
