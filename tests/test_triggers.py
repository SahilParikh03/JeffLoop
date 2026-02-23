"""Tests for event trigger wiring module (Section 11)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.events.limitless import DecklistEntry, TournamentResult
from src.events.synergy import SynergyTarget
from src.events.triggers import EventTrigger
from src.scraper import ScraperResult


# ---------------------------------------------------------------------------
# Mock Adapters
# ---------------------------------------------------------------------------


class MockAdapter:
    """Mock social platform adapter that returns pre-defined mentions."""

    def __init__(self, mentions: list[dict]) -> None:
        self._mentions = mentions

    async def fetch_mentions(self, keywords: list[str]) -> list[dict]:
        return self._mentions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_scheduler() -> MagicMock:
    scheduler = MagicMock()
    scheduler.increase_poll_cadence = MagicMock()
    return scheduler


@pytest.fixture
def mock_scraper_runner() -> AsyncMock:
    runner = AsyncMock()
    return runner


@pytest.fixture
def trigger(mock_scheduler: MagicMock, mock_scraper_runner: AsyncMock) -> EventTrigger:
    return EventTrigger(scheduler=mock_scheduler, scraper_runner=mock_scraper_runner)


@pytest.fixture
def trigger_no_deps() -> EventTrigger:
    return EventTrigger(scheduler=None, scraper_runner=None)


# ---------------------------------------------------------------------------
# Test: process_social_spikes
# ---------------------------------------------------------------------------


class TestProcessSocialSpikes:
    @pytest.mark.asyncio
    async def test_process_social_spikes_triggers_cadence_increase(
        self, trigger: EventTrigger, mock_scheduler: MagicMock
    ) -> None:
        """
        6 mentions for 'charizard ex' with default baseline of 1.0
        (threshold = 5x * 1.0 = 5) triggers a spike → scheduler called.
        """
        from src.config import settings

        mentions = [
            {
                "keyword": "charizard ex",
                "title": f"Post {i}",
                "created_utc": 0,
                "subreddit": "PokemonTCG",
            }
            for i in range(6)
        ]
        adapter = MockAdapter(mentions)

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            triggered = await trigger.process_social_spikes(["charizard ex"], adapter=adapter)

        assert "charizard ex" in triggered
        mock_scheduler.increase_poll_cadence.assert_called_with("charizard ex")

    @pytest.mark.asyncio
    async def test_process_social_spikes_no_spike(
        self, trigger: EventTrigger, mock_scheduler: MagicMock
    ) -> None:
        """
        3 mentions is below the 5x baseline threshold → no spike detected,
        scheduler.increase_poll_cadence is never called.
        """
        from src.config import settings

        mentions = [
            {
                "keyword": "pikachu",
                "title": f"Post {i}",
                "created_utc": 0,
                "subreddit": "PokemonTCG",
            }
            for i in range(3)
        ]
        adapter = MockAdapter(mentions)

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            triggered = await trigger.process_social_spikes(["pikachu"], adapter=adapter)

        assert triggered == []
        mock_scheduler.increase_poll_cadence.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_social_spikes_no_scheduler(
        self, trigger_no_deps: EventTrigger
    ) -> None:
        """
        When scheduler is None, process_social_spikes should not crash and
        still return the list of spiking keywords.
        """
        from src.config import settings

        mentions = [
            {
                "keyword": "mewtwo",
                "title": f"Post {i}",
                "created_utc": 0,
                "subreddit": "PokemonTCG",
            }
            for i in range(6)
        ]
        adapter = MockAdapter(mentions)

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            triggered = await trigger_no_deps.process_social_spikes(["mewtwo"], adapter=adapter)

        # Should still return the spiking keyword despite no scheduler
        assert "mewtwo" in triggered


# ---------------------------------------------------------------------------
# Test: process_tournament
# ---------------------------------------------------------------------------


class TestProcessTournament:
    @pytest.mark.asyncio
    @patch("src.events.triggers.LimitlessTCGClient")
    async def test_process_tournament_builds_synergy(
        self, MockClient: MagicMock, trigger: EventTrigger
    ) -> None:
        """
        A tournament with 3 cards in the winning decklist produces
        synergy targets (the co-occurrence partners of each card).
        """
        mock_client = AsyncMock()
        mock_client.fetch_tournament_results = AsyncMock(
            return_value=[
                TournamentResult(
                    tournament_id="t1",
                    tournament_name="Test Cup",
                    placement=1,
                    decklist=[
                        DecklistEntry(card_name="Charizard ex", count=2),
                        DecklistEntry(card_name="Rare Candy", count=4),
                        DecklistEntry(card_name="Arcanine", count=2),
                    ],
                ),
            ]
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        targets = await trigger.process_tournament("t1")

        assert len(targets) > 0
        target_names = [t.card_name for t in targets]
        # Synergy partners of any top-8 card should appear in targets
        assert any(
            name in target_names
            for name in ["Charizard ex", "Rare Candy", "Arcanine"]
        )

    @pytest.mark.asyncio
    @patch("src.events.triggers.LimitlessTCGClient")
    async def test_process_tournament_no_results(
        self, MockClient: MagicMock, trigger: EventTrigger
    ) -> None:
        """An empty tournament response returns an empty list without crashing."""
        mock_client = AsyncMock()
        mock_client.fetch_tournament_results = AsyncMock(return_value=[])
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        targets = await trigger.process_tournament("t_empty")

        assert targets == []

    @pytest.mark.asyncio
    @patch("src.events.triggers.LimitlessTCGClient")
    async def test_process_tournament_increases_cadence(
        self,
        MockClient: MagicMock,
        trigger: EventTrigger,
        mock_scheduler: MagicMock,
    ) -> None:
        """
        After processing a tournament, scheduler.increase_poll_cadence is called
        for the top synergy target cards.
        """
        mock_client = AsyncMock()
        mock_client.fetch_tournament_results = AsyncMock(
            return_value=[
                TournamentResult(
                    tournament_id="t2",
                    tournament_name="Nationals",
                    placement=1,
                    decklist=[
                        DecklistEntry(card_name="Charizard ex", count=3),
                        DecklistEntry(card_name="Rare Candy", count=4),
                        DecklistEntry(card_name="Arven", count=4),
                    ],
                ),
            ]
        )
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=None)

        targets = await trigger.process_tournament("t2")

        # At least one synergy target should have triggered a cadence increase
        assert mock_scheduler.increase_poll_cadence.call_count >= 1
        called_args = [
            call.args[0]
            for call in mock_scheduler.increase_poll_cadence.call_args_list
        ]
        # The called card names must correspond to the synergy targets returned
        assert len(called_args) <= min(10, len(targets))


# ---------------------------------------------------------------------------
# Test: queue_scrape
# ---------------------------------------------------------------------------


class TestQueueScrape:
    @pytest.mark.asyncio
    async def test_queue_scrape_success(
        self, trigger: EventTrigger, mock_scraper_runner: AsyncMock
    ) -> None:
        """
        When scraper_runner.scrape_card returns a ScraperResult,
        queue_scrape returns True.
        """
        mock_scraper_runner.scrape_card = AsyncMock(
            return_value=ScraperResult(
                card_id="sv1-25",
                price_eur=Decimal("12.50"),
                scrape_method="network_intercept",
                scraped_at=datetime.now(timezone.utc),
            )
        )

        result = await trigger.queue_scrape(
            "sv1-25", "https://example.com", AsyncMock()
        )

        assert result is True
        mock_scraper_runner.scrape_card.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_scrape_no_runner(
        self, trigger_no_deps: EventTrigger
    ) -> None:
        """
        When scraper_runner is None, queue_scrape returns False without crashing.
        """
        result = await trigger_no_deps.queue_scrape(
            "sv1-25", "https://example.com", AsyncMock()
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_queue_scrape_runner_returns_none(
        self, trigger: EventTrigger, mock_scraper_runner: AsyncMock
    ) -> None:
        """
        When scrape_card returns None (all methods failed), queue_scrape returns False.
        """
        mock_scraper_runner.scrape_card = AsyncMock(return_value=None)

        result = await trigger.queue_scrape(
            "sv1-99", "https://example.com", AsyncMock()
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_queue_scrape_exception_returns_false(
        self, trigger: EventTrigger, mock_scraper_runner: AsyncMock
    ) -> None:
        """
        When scrape_card raises an exception, queue_scrape returns False without
        propagating the error.
        """
        mock_scraper_runner.scrape_card = AsyncMock(
            side_effect=RuntimeError("Playwright timeout")
        )

        result = await trigger.queue_scrape(
            "sv1-99", "https://example.com", AsyncMock()
        )

        assert result is False
