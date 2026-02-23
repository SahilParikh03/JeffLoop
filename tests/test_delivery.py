"""
Tests for the Discord delivery module.

Covers disabled state, send_signal, send_batch_signals, send_daily_digest,
network errors, and embed formatting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.signals.delivery import (
    DiscordNotifier,
    _fmt_digest_embed,
    _fmt_signal_embed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def discord_notifier() -> DiscordNotifier:
    """Return an enabled DiscordNotifier with a mocked httpx client."""
    notifier = DiscordNotifier(bot_token="test-token-123")
    notifier._client = AsyncMock()
    notifier._enabled = True
    return notifier


def _mock_ok_response() -> MagicMock:
    """Return a mock httpx response with status 200."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    return mock_response


def _sample_signal(index: int = 1) -> dict:
    return {
        "card_id": f"sv1-{index}",
        "card_name": f"Pikachu ex {index}",
        "net_profit": float(10 * index),
        "margin_pct": float(15 + index),
        "cm_price_eur": 20.00,
        "tcg_price_usd": 25.00,
        "condition": "NM",
        "velocity_tier": "1",
        "headache_tier": "2",
        "tcgplayer_url": f"https://tcgplayer.com/{index}",
        "cardmarket_url": f"https://cardmarket.com/{index}",
    }


# ---------------------------------------------------------------------------
# Test: disabled notifier
# ---------------------------------------------------------------------------

class TestDiscordNotifierDisabled:
    """Graceful degradation when no token is provided."""

    def test_discord_notifier_disabled_no_token(self) -> None:
        """No token → _enabled is False and _client stays None."""
        notifier = DiscordNotifier(bot_token=None)
        assert notifier._enabled is False
        assert notifier._client is None

    def test_discord_notifier_disabled_empty_string(self) -> None:
        """Empty string token → treated same as None."""
        notifier = DiscordNotifier(bot_token="")
        assert notifier._enabled is False

    @pytest.mark.asyncio
    async def test_send_signal_returns_false_when_disabled(self) -> None:
        """send_signal returns False without making any HTTP call."""
        notifier = DiscordNotifier(bot_token=None)
        result = await notifier.send_signal(123456789, _sample_signal())
        assert result is False

    @pytest.mark.asyncio
    async def test_send_batch_signals_returns_zero_when_disabled(self) -> None:
        """send_batch_signals returns 0 without making any HTTP calls."""
        notifier = DiscordNotifier(bot_token=None)
        result = await notifier.send_batch_signals(123456789, [_sample_signal()])
        assert result == 0

    @pytest.mark.asyncio
    async def test_send_daily_digest_returns_false_when_disabled(self) -> None:
        """send_daily_digest returns False without making any HTTP calls."""
        notifier = DiscordNotifier(bot_token=None)
        result = await notifier.send_daily_digest(123456789, [_sample_signal()])
        assert result is False


# ---------------------------------------------------------------------------
# Test: enabled notifier
# ---------------------------------------------------------------------------

class TestDiscordNotifierEnabled:
    """Verify enabled state is correctly set."""

    def test_discord_notifier_enabled_with_token(self) -> None:
        """A non-empty token → _enabled is True."""
        notifier = DiscordNotifier(bot_token="my-real-token")
        assert notifier._enabled is True


# ---------------------------------------------------------------------------
# Test: send_signal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendSignal:
    """Tests for send_signal method."""

    async def test_send_signal_success(self, discord_notifier: DiscordNotifier) -> None:
        """Returns True when Discord API responds 200."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())

        result = await discord_notifier.send_signal(987654321, _sample_signal())

        assert result is True
        discord_notifier._client.post.assert_awaited_once()

    async def test_send_signal_posts_to_correct_channel(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Sends to the correct Discord channel path."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())
        channel_id = 111222333

        await discord_notifier.send_signal(channel_id, _sample_signal())

        call_args = discord_notifier._client.post.call_args
        assert f"/channels/{channel_id}/messages" in call_args[0][0]

    async def test_send_signal_failure_on_http_error(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Returns False when Discord API returns HTTP 400."""
        bad_response = AsyncMock()
        bad_response.raise_for_status = MagicMock(side_effect=Exception("400 Bad Request"))
        discord_notifier._client.post = AsyncMock(return_value=bad_response)

        result = await discord_notifier.send_signal(987654321, _sample_signal())

        assert result is False

    async def test_send_signal_failure_on_network_error(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Returns False when a network-level exception is raised."""
        discord_notifier._client.post = AsyncMock(
            side_effect=ConnectionError("Network unreachable")
        )

        result = await discord_notifier.send_signal(987654321, _sample_signal())

        assert result is False


# ---------------------------------------------------------------------------
# Test: send_batch_signals
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendBatchSignals:
    """Tests for send_batch_signals method."""

    async def test_send_batch_signals_empty_list_returns_zero(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Empty signal list returns 0 immediately."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())

        result = await discord_notifier.send_batch_signals(123456789, [])

        assert result == 0
        discord_notifier._client.post.assert_not_awaited()

    async def test_send_batch_signals_all_succeed(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """All 3 signals succeed → returns 3."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())
        signals = [_sample_signal(i) for i in range(1, 4)]

        result = await discord_notifier.send_batch_signals(123456789, signals)

        assert result == 3
        assert discord_notifier._client.post.await_count == 3

    async def test_send_batch_signals_partial_failure(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """2 succeed, 1 fails → returns 2."""
        ok_response = _mock_ok_response()
        err_response = AsyncMock()
        err_response.raise_for_status = MagicMock(side_effect=Exception("403 Forbidden"))

        discord_notifier._client.post = AsyncMock(
            side_effect=[ok_response, err_response, ok_response]
        )
        signals = [_sample_signal(i) for i in range(1, 4)]

        result = await discord_notifier.send_batch_signals(123456789, signals)

        assert result == 2


# ---------------------------------------------------------------------------
# Test: send_daily_digest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSendDailyDigest:
    """Tests for send_daily_digest method."""

    async def test_send_daily_digest_success(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Returns True when digest is delivered successfully."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())
        signals = [_sample_signal(i) for i in range(1, 4)]

        result = await discord_notifier.send_daily_digest(123456789, signals)

        assert result is True
        discord_notifier._client.post.assert_awaited_once()

    async def test_send_daily_digest_empty_signals_returns_false(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Empty signal list returns False and skips HTTP call."""
        discord_notifier._client.post = AsyncMock(return_value=_mock_ok_response())

        result = await discord_notifier.send_daily_digest(123456789, [])

        assert result is False
        discord_notifier._client.post.assert_not_awaited()

    async def test_send_daily_digest_failure_on_http_error(
        self, discord_notifier: DiscordNotifier
    ) -> None:
        """Returns False when Discord API raises an exception."""
        bad_response = AsyncMock()
        bad_response.raise_for_status = MagicMock(side_effect=Exception("500 Server Error"))
        discord_notifier._client.post = AsyncMock(return_value=bad_response)
        signals = [_sample_signal()]

        result = await discord_notifier.send_daily_digest(123456789, signals)

        assert result is False


# ---------------------------------------------------------------------------
# Test: embed formatting helpers
# ---------------------------------------------------------------------------

class TestFmtSignalEmbed:
    """Tests for _fmt_signal_embed helper."""

    def test_fmt_signal_embed_structure(self) -> None:
        """Embed has all required top-level keys."""
        signal = _sample_signal(1)
        embed = _fmt_signal_embed(signal)

        assert "title" in embed
        assert "color" in embed
        assert "fields" in embed
        assert "description" in embed
        assert "timestamp" in embed

    def test_fmt_signal_embed_title_contains_card_name(self) -> None:
        """Title includes the card name."""
        signal = _sample_signal(1)
        embed = _fmt_signal_embed(signal)

        assert "Pikachu ex 1" in embed["title"]

    def test_fmt_signal_embed_has_six_fields(self) -> None:
        """Embed contains exactly six inline fields."""
        signal = _sample_signal(1)
        embed = _fmt_signal_embed(signal)

        assert len(embed["fields"]) == 6

    def test_fmt_signal_embed_field_names(self) -> None:
        """All expected field names are present."""
        signal = _sample_signal(1)
        embed = _fmt_signal_embed(signal)

        field_names = {f["name"] for f in embed["fields"]}
        assert "Net Profit" in field_names
        assert "CM Price" in field_names
        assert "TCG Price" in field_names
        assert "Condition" in field_names
        assert "Velocity" in field_names
        assert "Headache" in field_names

    def test_fmt_signal_embed_missing_fields_use_defaults(self) -> None:
        """Missing fields fall back to safe defaults without raising."""
        embed = _fmt_signal_embed({})

        assert "Unknown" in embed["title"]
        assert embed["color"] == 0x00FF00

    def test_fmt_signal_embed_description_contains_links(self) -> None:
        """Description contains both platform links."""
        signal = _sample_signal(1)
        embed = _fmt_signal_embed(signal)

        assert "TCGPlayer" in embed["description"]
        assert "Cardmarket" in embed["description"]


class TestFmtDigestEmbed:
    """Tests for _fmt_digest_embed helper."""

    def test_fmt_digest_embed_structure(self) -> None:
        """Embed has all required top-level keys."""
        signals = [_sample_signal(i) for i in range(1, 4)]
        embed = _fmt_digest_embed(signals)

        assert "title" in embed
        assert "color" in embed
        assert "fields" in embed
        assert "description" in embed
        assert "timestamp" in embed

    def test_fmt_digest_embed_has_three_summary_fields(self) -> None:
        """Summary embed contains exactly three aggregate fields."""
        signals = [_sample_signal(i) for i in range(1, 4)]
        embed = _fmt_digest_embed(signals)

        assert len(embed["fields"]) == 3

    def test_fmt_digest_embed_signals_found_count(self) -> None:
        """Signals Found field reflects the total count."""
        signals = [_sample_signal(i) for i in range(1, 8)]
        embed = _fmt_digest_embed(signals)

        found_field = next(f for f in embed["fields"] if f["name"] == "Signals Found")
        assert found_field["value"] == "7"

    def test_fmt_digest_embed_top5_ranking_in_description(self) -> None:
        """Description lists top 5 signals sorted by profit descending."""
        signals = [_sample_signal(i) for i in range(1, 11)]  # 10 signals
        embed = _fmt_digest_embed(signals)

        description = embed["description"]
        # Signal 10 has highest profit (100), signal 9 next (90), etc.
        pos_10 = description.find("Pikachu ex 10")
        pos_9 = description.find("Pikachu ex 9")
        pos_8 = description.find("Pikachu ex 8")

        assert pos_10 < pos_9 < pos_8, "Top signals should appear in descending profit order"

    def test_fmt_digest_embed_no_signals_description(self) -> None:
        """Empty signals list produces a sensible description."""
        embed = _fmt_digest_embed([])
        assert embed["description"] == "No signals today."

    def test_fmt_digest_embed_color_is_blue(self) -> None:
        """Digest embed uses blue color (0x3498DB)."""
        embed = _fmt_digest_embed([_sample_signal()])
        assert embed["color"] == 0x3498DB

    def test_fmt_digest_embed_caps_at_5_in_description(self) -> None:
        """Only 5 signals appear in the description even with more provided."""
        signals = [_sample_signal(i) for i in range(1, 11)]
        embed = _fmt_digest_embed(signals)

        # Count rank lines (lines starting with a digit followed by a dot)
        lines = embed["description"].split("\n")
        rank_lines = [l for l in lines if l and l[0].isdigit()]
        assert len(rank_lines) == 5
