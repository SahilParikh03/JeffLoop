"""Tests for the Social Listener (Layer 3.5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

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


class TestTwitterAdapterFetchMentions:
    """Tests for TwitterAdapter (Phase 3 — Twitter/X API v2)."""

    @pytest.mark.asyncio
    async def test_happy_path_keyword_found(self) -> None:
        """Keyword found in tweet text returns correctly structured mention."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        mock_response = {
            "data": [
                {
                    "id": "123",
                    "text": "Charizard ex is mooning right now!",
                    "created_at": "2026-02-22T10:00:00Z",
                }
            ]
        }

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with respx.mock:
                respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
                    return_value=httpx.Response(200, json=mock_response)
                )
                async with TwitterAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["charizard"])

        assert len(mentions) == 1
        assert mentions[0]["keyword"] == "charizard"
        assert mentions[0]["subreddit"] == "twitter"
        assert mentions[0]["title"] == "Charizard ex is mooning right now!"
        assert isinstance(mentions[0]["created_utc"], int)

    @pytest.mark.asyncio
    async def test_multiple_keywords(self) -> None:
        """Multiple keywords each get their own API call."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        mock_response = {"data": [{"id": "1", "text": "test tweet", "created_at": "2026-02-22T10:00:00Z"}]}

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with respx.mock:
                respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
                    return_value=httpx.Response(200, json=mock_response)
                )
                async with TwitterAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["charizard", "pikachu"])

        # Two keywords = two mentions
        assert len(mentions) == 2
        keywords_returned = {m["keyword"] for m in mentions}
        assert "charizard" in keywords_returned
        assert "pikachu" in keywords_returned

    @pytest.mark.asyncio
    async def test_empty_bearer_token_returns_empty_list(self) -> None:
        """Empty TWITTER_BEARER_TOKEN returns [] without making API call."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        with patch.object(settings, "TWITTER_BEARER_TOKEN", ""):
            async with TwitterAdapter() as adapter:
                mentions = await adapter.fetch_mentions(["charizard"])

        assert mentions == []

    @pytest.mark.asyncio
    async def test_api_error_returns_partial_results(self) -> None:
        """On HTTP error for one keyword, returns [] for that keyword, keeps others."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        mock_ok = {"data": [{"id": "1", "text": "pikachu spiking!", "created_at": "2026-02-22T10:00:00Z"}]}

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with respx.mock:
                # First keyword fails
                respx.get(
                    "https://api.twitter.com/2/tweets/search/recent",
                    params__contains={"query": "charizard"},
                ).mock(side_effect=httpx.ConnectError("timeout"))
                # Second keyword succeeds
                respx.get(
                    "https://api.twitter.com/2/tweets/search/recent",
                    params__contains={"query": "pikachu"},
                ).mock(return_value=httpx.Response(200, json=mock_ok))
                async with TwitterAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["charizard", "pikachu"])

        # Only pikachu mention returned (charizard failed gracefully)
        assert len(mentions) == 1
        assert mentions[0]["keyword"] == "pikachu"

    @pytest.mark.asyncio
    async def test_empty_response_no_data_field(self) -> None:
        """Response with no 'data' field returns empty list for that keyword."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with respx.mock:
                respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
                    return_value=httpx.Response(200, json={})
                )
                async with TwitterAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["charizard"])

        assert mentions == []

    @pytest.mark.asyncio
    async def test_integration_twitter_feeds_social_listener_spike(self) -> None:
        """TwitterAdapter feeds into SocialListener.scan_for_spikes() spike detection."""
        from src.events.social_listener import TwitterAdapter, SocialListener
        from src.config import settings

        # 6 tweets about charizard = spike at 5x multiplier (baseline=1, threshold=5)
        mock_response = {
            "data": [
                {"id": str(i), "text": f"charizard tweet {i}", "created_at": "2026-02-22T10:00:00Z"}
                for i in range(6)
            ]
        }

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
                with respx.mock:
                    respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
                        return_value=httpx.Response(200, json=mock_response)
                    )
                    async with TwitterAdapter() as adapter:
                        listener = SocialListener(spike_multiplier=5.0)
                        spiking = await listener.scan_for_spikes(["charizard"], adapter=adapter)

        assert "charizard" in spiking

    @pytest.mark.asyncio
    async def test_created_utc_is_unix_timestamp_int(self) -> None:
        """created_utc field is an integer Unix timestamp."""
        from src.events.social_listener import TwitterAdapter
        from src.config import settings

        mock_response = {
            "data": [
                {"id": "1", "text": "test", "created_at": "2026-02-22T10:00:00Z"}
            ]
        }

        with patch.object(settings, "TWITTER_BEARER_TOKEN", "test-token"):
            with respx.mock:
                respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
                    return_value=httpx.Response(200, json=mock_response)
                )
                async with TwitterAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["test"])

        assert len(mentions) == 1
        assert isinstance(mentions[0]["created_utc"], int)
        assert mentions[0]["created_utc"] > 0


class TestDiscordAdapterFetchMentions:
    """Tests for DiscordAdapter (Phase 4 — Layer 3.5 Discord source)."""

    CHANNEL_URL = "https://discord.com/api/v10/channels/123456789/messages"

    def _make_message(self, msg_id: str, content: str) -> dict:
        return {"id": msg_id, "content": content, "author": {"username": "trainer"}}

    @pytest.mark.asyncio
    async def test_happy_path_keyword_in_message(self) -> None:
        """Keyword found in channel message returns correctly structured mention."""
        from src.events.social_listener import DiscordAdapter
        from src.config import settings

        messages = [self._make_message("1297253141046468628", "Charizard ex is spiking!")]

        with patch.object(settings, "DISCORD_BOT_TOKEN", "Bot test-token"), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", "123456789"
        ):
            with respx.mock:
                respx.get(self.CHANNEL_URL).mock(
                    return_value=httpx.Response(200, json=messages)
                )
                async with DiscordAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["charizard"])

        assert len(mentions) == 1
        assert mentions[0]["keyword"] == "charizard"
        assert mentions[0]["subreddit"] == "discord"
        assert "Charizard ex is spiking!" in mentions[0]["title"]
        assert isinstance(mentions[0]["created_utc"], int)

    @pytest.mark.asyncio
    async def test_multiple_channels(self) -> None:
        """Monitors multiple channel IDs from comma-separated config."""
        from src.events.social_listener import DiscordAdapter
        from src.config import settings

        messages = [self._make_message("1297253141046468628", "pikachu vstar")]

        with patch.object(settings, "DISCORD_BOT_TOKEN", "Bot test-token"), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", "123456789,987654321"
        ):
            with respx.mock:
                respx.get("https://discord.com/api/v10/channels/123456789/messages").mock(
                    return_value=httpx.Response(200, json=messages)
                )
                respx.get("https://discord.com/api/v10/channels/987654321/messages").mock(
                    return_value=httpx.Response(200, json=messages)
                )
                async with DiscordAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["pikachu"])

        # Two channels × one match each = 2 mentions
        assert len(mentions) == 2
        assert all(m["keyword"] == "pikachu" for m in mentions)

    @pytest.mark.asyncio
    async def test_missing_bot_token_returns_empty(self) -> None:
        """Empty DISCORD_BOT_TOKEN → returns [] without making any HTTP call."""
        from src.events.social_listener import DiscordAdapter
        from src.config import settings

        with patch.object(settings, "DISCORD_BOT_TOKEN", ""), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", "123456789"
        ):
            async with DiscordAdapter() as adapter:
                mentions = await adapter.fetch_mentions(["charizard"])

        assert mentions == []

    @pytest.mark.asyncio
    async def test_missing_channel_ids_returns_empty(self) -> None:
        """Empty DISCORD_MONITOR_CHANNEL_IDS → returns [] without HTTP call."""
        from src.events.social_listener import DiscordAdapter
        from src.config import settings

        with patch.object(settings, "DISCORD_BOT_TOKEN", "Bot test-token"), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", ""
        ):
            async with DiscordAdapter() as adapter:
                mentions = await adapter.fetch_mentions(["charizard"])

        assert mentions == []

    @pytest.mark.asyncio
    async def test_api_error_returns_partial_results(self) -> None:
        """HTTP error on one channel is swallowed; other channels still processed."""
        from src.events.social_listener import DiscordAdapter
        from src.config import settings

        good_messages = [self._make_message("1297253141046468628", "mewtwo price drop")]

        with patch.object(settings, "DISCORD_BOT_TOKEN", "Bot test-token"), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", "111111111,222222222"
        ):
            with respx.mock:
                # First channel errors
                respx.get(
                    "https://discord.com/api/v10/channels/111111111/messages"
                ).mock(side_effect=httpx.ConnectError("connection refused"))
                # Second channel succeeds
                respx.get(
                    "https://discord.com/api/v10/channels/222222222/messages"
                ).mock(return_value=httpx.Response(200, json=good_messages))
                async with DiscordAdapter() as adapter:
                    mentions = await adapter.fetch_mentions(["mewtwo"])

        # Only second channel's result returned
        assert len(mentions) == 1
        assert mentions[0]["keyword"] == "mewtwo"

    def test_snowflake_timestamp_conversion(self) -> None:
        """Discord snowflake ID converts to a reasonable Unix timestamp."""
        from src.events.social_listener import _discord_snowflake_to_utc

        # Snowflake for a known Discord message (Feb 2026 approximate)
        # 1297253141046468628 >> 22 + discord_epoch → should be around 2024
        ts = _discord_snowflake_to_utc("1297253141046468628")
        assert isinstance(ts, int)
        assert ts > 1_600_000_000  # After Sept 2020 (sanity floor)

    def test_snowflake_invalid_input_returns_zero(self) -> None:
        """Non-numeric / empty snowflake returns 0 gracefully."""
        from src.events.social_listener import _discord_snowflake_to_utc

        assert _discord_snowflake_to_utc("not-a-number") == 0
        assert _discord_snowflake_to_utc("") == 0
        # "0" is the Discord epoch start (Jan 1 2015), which is a valid timestamp
        assert _discord_snowflake_to_utc("0") == 1420070400

    @pytest.mark.asyncio
    async def test_integration_discord_feeds_social_listener(self) -> None:
        """DiscordAdapter feeds into SocialListener.scan_for_spikes() spike detection."""
        from src.events.social_listener import DiscordAdapter, SocialListener
        from src.config import settings

        # Send 6 messages all mentioning "charizard" → spike at 5x multiplier
        messages = [
            self._make_message(str(i), f"charizard ex tweet {i}") for i in range(6)
        ]

        with patch.object(settings, "DISCORD_BOT_TOKEN", "Bot test-token"), patch.object(
            settings, "DISCORD_MONITOR_CHANNEL_IDS", "123456789"
        ), patch.object(settings, "ENABLE_LAYER_35_SOCIAL", True):
            with respx.mock:
                respx.get(self.CHANNEL_URL).mock(
                    return_value=httpx.Response(200, json=messages)
                )
                async with DiscordAdapter() as adapter:
                    listener = SocialListener(spike_multiplier=5.0)
                    spiking = await listener.scan_for_spikes(
                        ["charizard"], adapter=adapter
                    )

        assert "charizard" in spiking
