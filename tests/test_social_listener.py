"""Tests for the Social Listener (Layer 3.5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from src.events.social_listener import SocialListener


class MockAdapter:
    """Synchronous mock adapter for testing."""

    def __init__(self, mentions: list[dict[str, Any]]) -> None:
        self._mentions = mentions

    async def fetch_mentions(self, keywords: list[str]) -> list[dict[str, Any]]:
        return self._mentions


class TestSocialListenerDisabled:
    @pytest.mark.asyncio
    async def test_social_listener_disabled(self) -> None:
        """When ENABLE_LAYER_35_SOCIAL=False, scan returns empty list."""
        from src.config import settings

        listener = SocialListener()
        adapter = MockAdapter([
            {"keyword": "charizard", "title": "Big spike!", "created_utc": 0, "subreddit": "PokemonTCG"},
        ])

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", False):
            result = await listener.scan_for_spikes(["charizard"], adapter=adapter)

        assert result == []


class TestRecordMentions:
    def test_record_mentions_increments_count(self) -> None:
        """Recording 3 mentions should produce a frequency of 3."""
        listener = SocialListener()
        listener.record_mentions("charizard", 3)
        assert listener.get_current_frequency("charizard") == 3

    def test_record_mentions_accumulates(self) -> None:
        """Multiple record calls accumulate correctly."""
        listener = SocialListener()
        listener.record_mentions("pikachu", 2)
        listener.record_mentions("pikachu", 3)
        assert listener.get_current_frequency("pikachu") == 5


class TestGetCurrentFrequency:
    def test_returns_correct_count(self) -> None:
        """Frequency returns the number of recorded mentions."""
        listener = SocialListener()
        listener.record_mentions("mewtwo", 7)
        assert listener.get_current_frequency("mewtwo") == 7

    def test_unknown_keyword_returns_zero(self) -> None:
        """Unknown keyword starts at zero."""
        listener = SocialListener()
        assert listener.get_current_frequency("not_a_real_card") == 0


class TestPruneOldMentions:
    def test_prune_old_mentions_removes_stale_entries(self) -> None:
        """Mentions older than the rolling window are pruned."""
        listener = SocialListener()

        # Inject old timestamps directly
        old_time = datetime.now(timezone.utc) - timedelta(minutes=31)
        listener._mention_history["charizard"] = [old_time, old_time]

        # Frequency should return 0 after pruning
        assert listener.get_current_frequency("charizard") == 0

    def test_prune_keeps_fresh_mentions(self) -> None:
        """Mentions within the window are retained."""
        listener = SocialListener()
        listener.record_mentions("charizard", 5)
        # Fresh mentions should still be present
        assert listener.get_current_frequency("charizard") == 5


class TestIsSpike:
    def test_is_spike_below_threshold(self) -> None:
        """Frequency at or below 5x baseline is NOT a spike."""
        listener = SocialListener(spike_multiplier=5.0)
        listener.update_baseline("charizard", 2.0)  # baseline = 2, threshold = 10
        listener.record_mentions("charizard", 5)     # current = 5 — not > 10
        assert listener.is_spike("charizard") is False

    def test_is_spike_above_threshold(self) -> None:
        """Frequency above 5x baseline IS a spike."""
        listener = SocialListener(spike_multiplier=5.0)
        listener.update_baseline("charizard", 2.0)  # baseline = 2, threshold = 10
        listener.record_mentions("charizard", 11)   # current = 11 — > 10
        assert listener.is_spike("charizard") is True

    def test_is_spike_default_baseline_is_one(self) -> None:
        """Default baseline is 1.0, so threshold is 5x=5. 6 mentions → spike."""
        listener = SocialListener(spike_multiplier=5.0)
        listener.record_mentions("pikachu", 6)
        assert listener.is_spike("pikachu") is True


class TestUpdateBaseline:
    def test_update_baseline_changes_threshold(self) -> None:
        """Higher baseline raises the spike threshold."""
        listener = SocialListener(spike_multiplier=5.0)
        listener.update_baseline("charizard", 10.0)  # threshold = 50
        listener.record_mentions("charizard", 20)    # current = 20 — not > 50
        assert listener.is_spike("charizard") is False

    def test_update_baseline_floors_at_one(self) -> None:
        """Baseline cannot be set below 1.0."""
        listener = SocialListener()
        listener.update_baseline("charizard", 0.0)
        assert listener._baselines["charizard"] == 1.0


class TestScanForSpikes:
    @pytest.mark.asyncio
    async def test_scan_for_spikes_with_mock_adapter(self) -> None:
        """Mock adapter returns 6 mentions → spike detected at 5x multiplier."""
        from src.config import settings

        listener = SocialListener(spike_multiplier=5.0)
        # Default baseline = 1.0 → threshold = 5 → need > 5 mentions
        # Provide 6 mention records for "charizard"
        mentions = [
            {"keyword": "charizard", "title": f"Post {i}", "created_utc": 0, "subreddit": "PokemonTCG"}
            for i in range(6)
        ]
        adapter = MockAdapter(mentions)

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            spiking = await listener.scan_for_spikes(["charizard"], adapter=adapter)

        assert "charizard" in spiking

    @pytest.mark.asyncio
    async def test_scan_for_spikes_no_spike_detected(self) -> None:
        """Adapter returns 3 mentions → below 5x baseline → no spike."""
        from src.config import settings

        listener = SocialListener(spike_multiplier=5.0)
        mentions = [
            {"keyword": "pikachu", "title": f"Post {i}", "created_utc": 0, "subreddit": "PokemonTCG"}
            for i in range(3)
        ]
        adapter = MockAdapter(mentions)

        with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            spiking = await listener.scan_for_spikes(["pikachu"], adapter=adapter)

        assert spiking == []
