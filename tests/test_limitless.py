"""Tests for the Limitless TCG API client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from src.events.limitless import DecklistEntry, LimitlessTCGClient, TournamentResult


MOCK_TOURNAMENTS_RESPONSE = {
    "data": [
        {"id": "t001", "name": "Regional Championship 2026", "game": "pokemon", "date": "2026-02-15"},
        {"id": "t002", "name": "City League 2026", "game": "pokemon", "date": "2026-02-10"},
    ]
}

MOCK_RESULTS_RESPONSE = {
    "data": [
        {
            "tournament_name": "Regional Championship 2026",
            "player": "Ash Ketchum",
            "placement": 1,
            "deck_name": "Charizard ex",
            "date": "2026-02-15",
            "decklist": [
                {"name": "Charizard ex", "id": "OBF-125", "count": 3},
                {"name": "Rare Candy", "id": "SVI-191", "count": 4},
                {"name": "Professor's Research", "id": "SVI-189", "count": 4},
            ],
        },
        {
            "tournament_name": "Regional Championship 2026",
            "player": "Misty",
            "placement": 2,
            "deck_name": "Gardevoir ex",
            "date": "2026-02-15",
            "decklist": [
                {"name": "Gardevoir ex", "id": "SIT-61", "count": 3},
                {"name": "Kirlia", "id": "SIT-60", "count": 4},
            ],
        },
    ]
}


class TestClientInit:
    def test_client_init_default_url(self) -> None:
        """Client uses default BASE_URL when none provided."""
        client = LimitlessTCGClient()
        assert client._base_url == LimitlessTCGClient.BASE_URL
        assert "limitlesstcg.com" in client._base_url

    def test_client_init_custom_url(self) -> None:
        """Client accepts a custom base URL."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        assert client._base_url == "https://mock.example.com/api"

    def test_client_init_max_retries(self) -> None:
        """Default max_retries is 3."""
        client = LimitlessTCGClient()
        assert client._max_retries == 3


class TestFetchRecentTournaments:
    @pytest.mark.asyncio
    async def test_fetch_recent_tournaments_returns_list(self) -> None:
        """Mock response returns a list of tournament dicts."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        client._client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=MOCK_TOURNAMENTS_RESPONSE)
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.fetch_recent_tournaments(game="pokemon", limit=2)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "t001"

    @pytest.mark.asyncio
    async def test_fetch_recent_tournaments_empty_data(self) -> None:
        """Empty data field returns empty list."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        client._client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"data": []})
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.fetch_recent_tournaments()
        assert result == []


class TestFetchTournamentResults:
    @pytest.mark.asyncio
    async def test_fetch_tournament_results_parses_correctly(self) -> None:
        """Mock response → list of TournamentResult with decklists."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        client._client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=MOCK_RESULTS_RESPONSE)
        client._client.get = AsyncMock(return_value=mock_response)

        results = await client.fetch_tournament_results("t001")

        assert isinstance(results, list)
        assert len(results) == 2

        first = results[0]
        assert isinstance(first, TournamentResult)
        assert first.placement == 1
        assert first.player_name == "Ash Ketchum"
        assert first.deck_name == "Charizard ex"
        assert len(first.decklist) == 3
        assert first.decklist[0].card_name == "Charizard ex"
        assert first.decklist[0].count == 3

    @pytest.mark.asyncio
    async def test_fetch_tournament_results_empty(self) -> None:
        """Empty response returns empty list."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        client._client = AsyncMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"data": []})
        client._client.get = AsyncMock(return_value=mock_response)

        results = await client.fetch_tournament_results("t_empty")
        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_tournament_results_skips_bad_entries(self) -> None:
        """Malformed entries are skipped gracefully."""
        client = LimitlessTCGClient(base_url="https://mock.example.com/api")
        client._client = AsyncMock()

        bad_response = {
            "data": [
                # Valid entry
                {
                    "tournament_name": "Test",
                    "player": "Player1",
                    "placement": 1,
                    "deck_name": "Deck",
                    "date": "2026-02-15",
                    "decklist": [],
                },
                # Invalid: placement is not an int — will fail TournamentResult validation
                {
                    "tournament_name": "Test",
                    "player": "Player2",
                    "placement": "not-an-int",
                    "deck_name": "Deck",
                    "date": "2026-02-15",
                    "decklist": [],
                },
            ]
        }

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=bad_response)
        client._client.get = AsyncMock(return_value=mock_response)

        results = await client.fetch_tournament_results("t_mixed")
        # Only the valid entry should survive
        assert len(results) == 1
        assert results[0].placement == 1


class TestDecklistEntryModel:
    def test_decklist_entry_model_validation(self) -> None:
        """DecklistEntry validates required fields."""
        entry = DecklistEntry(card_name="Charizard ex", card_id="OBF-125", count=3)
        assert entry.card_name == "Charizard ex"
        assert entry.card_id == "OBF-125"
        assert entry.count == 3

    def test_decklist_entry_defaults(self) -> None:
        """DecklistEntry has sensible defaults."""
        entry = DecklistEntry(card_name="Pikachu")
        assert entry.card_id is None
        assert entry.count == 1


class TestTournamentResultModel:
    def test_tournament_result_model_validation(self) -> None:
        """TournamentResult validates required and optional fields."""
        result = TournamentResult(
            tournament_id="t001",
            tournament_name="Regional",
            player_name="Ash",
            placement=1,
            deck_name="Charizard ex",
            date="2026-02-15",
        )
        assert result.tournament_id == "t001"
        assert result.placement == 1
        assert result.decklist == []

    def test_tournament_result_with_decklist(self) -> None:
        """TournamentResult accepts a populated decklist."""
        entries = [
            DecklistEntry(card_name="Charizard ex", count=3),
            DecklistEntry(card_name="Rare Candy", count=4),
        ]
        result = TournamentResult(
            tournament_id="t002",
            tournament_name="City",
            placement=2,
            decklist=entries,
        )
        assert len(result.decklist) == 2
        assert result.decklist[0].card_name == "Charizard ex"
