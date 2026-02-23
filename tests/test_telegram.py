"""
Tests for the Telegram notification delivery module.

Covers signal formatting, rate limiting, batch delivery, daily digest,
graceful degradation, and error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import telegram.error

from src.signals.telegram import (
    TelegramNotifier,
    _escape_mdv2,
    _fmt_digest_body,
    _fmt_signal_body,
)


class TestMarkdownEscaping:
    """Test MarkdownV2 character escaping."""

    def test_escape_mdv2_basic_special_chars(self) -> None:
        """Verify all MarkdownV2 reserved chars are escaped."""
        input_str = "_*[]()~`>#+-=|{}.!"
        result = _escape_mdv2(input_str)
        assert result == "\\_\\*\\[\\]\\(\\)\\~\\`\\>\\#\\+\\-\\=\\|\\{\\}\\.\\!"

    def test_escape_mdv2_preserves_alphanumeric(self) -> None:
        """Verify alphanumeric and safe punctuation pass through."""
        input_str = "Pikachu ex 1234 USD"
        assert _escape_mdv2(input_str) == "Pikachu ex 1234 USD"

    def test_escape_mdv2_card_name_with_dashes(self) -> None:
        """Card names often have dashes; verify they are escaped."""
        result = _escape_mdv2("Charizard ex - Holo")
        assert result == "Charizard ex \\- Holo"


class TestSignalFormatting:
    """Test single signal message formatting."""

    def test_fmt_signal_body_required_fields(self) -> None:
        """Verify the message contains all required fields."""
        signal = {
            "card_name": "Charizard ex",
            "net_profit": 12.50,
            "margin_pct": 15.3,
            "cm_price_eur": 45.00,
            "tcg_price_usd": 62.99,
            "condition": "Excellent",
            "velocity_tier": "1",
            "headache_tier": "1",
            "tcgplayer_url": "https://tcgplayer.com/product/123",
            "cardmarket_url": "https://cardmarket.com/en/Products/Show/456",
        }
        text = _fmt_signal_body(signal)

        assert "🎯 *TCG Radar Signal*" in text
        assert "📦 Charizard ex" in text
        assert "💰 Net Profit: \\$12\\.50" in text
        assert "\\(15\\.3%\\)" in text
        assert "🏷️ CM: €45\\.00 → TCG: \\$62\\.99" in text
        assert "📊 Condition: Excellent" in text
        assert "⚡ Velocity: Tier 1" in text
        assert "😤 Headache: Tier 1" in text
        assert "TCGPlayer" in text
        assert "Cardmarket" in text

    def test_fmt_signal_body_missing_fields_use_defaults(self) -> None:
        """Verify missing signal fields use safe defaults instead of crashing."""
        signal: dict = {}
        text = _fmt_signal_body(signal)

        assert "🎯 *TCG Radar Signal*" in text
        assert "📦 Unknown" in text
        assert "💰 Net Profit: \\$0\\.00" in text
        assert "N/A" in text

    def test_fmt_signal_body_escapes_card_name(self) -> None:
        """Card names with special characters are escaped."""
        signal = {
            "card_name": "Card (Promo) [Holo]",
            "net_profit": 5.00,
            "margin_pct": 10.0,
            "cm_price_eur": 20.00,
            "tcg_price_usd": 25.00,
            "condition": "NM",
            "velocity_tier": "2",
            "headache_tier": "2",
            "tcgplayer_url": "https://tcgplayer.com/1",
            "cardmarket_url": "https://cardmarket.com/1",
        }
        text = _fmt_signal_body(signal)
        assert "Card \\(Promo\\) \\[Holo\\]" in text

    def test_fmt_signal_body_numeric_formatting(self) -> None:
        """Verify prices are formatted to correct decimal places."""
        signal = {
            "card_name": "Test Card",
            "net_profit": 12.456789,
            "margin_pct": 15.56789,
            "cm_price_eur": 45.99,
            "tcg_price_usd": 62.1,
            "condition": "LP",
            "velocity_tier": "1",
            "headache_tier": "2",
            "tcgplayer_url": "https://tcgplayer.com/1",
            "cardmarket_url": "https://cardmarket.com/1",
        }
        text = _fmt_signal_body(signal)

        assert "12\\.46" in text
        assert "15\\.6" in text
        assert "45\\.99" in text
        assert "62\\.10" in text


class TestDigestFormatting:
    """Test daily digest message formatting."""

    def test_fmt_digest_body_empty_list(self) -> None:
        """Empty signal list still produces a valid message structure."""
        signals: list[dict] = []
        text = _fmt_digest_body(signals)

        assert "📅 *TCG Radar Daily Digest" in text
        assert "Signals found: 0" in text
        assert "Avg margin: 0\\.0%" in text
        assert "Best opportunity: \\$0\\.00" in text

    def test_fmt_digest_body_single_signal(self) -> None:
        """Single signal is shown as rank 1."""
        signals = [
            {
                "card_name": "Pikachu",
                "net_profit": 10.00,
                "margin_pct": 20.0,
                "tcgplayer_url": "https://tcgplayer.com/1",
            }
        ]
        text = _fmt_digest_body(signals)

        assert "🏆 *Top 1 Signals*" in text
        assert "1\\. [Pikachu]" in text
        assert "\\$10\\.00 \\(20\\.0%\\)" in text

    def test_fmt_digest_body_sorts_by_profit(self) -> None:
        """Signals are sorted by net_profit descending (highest first)."""
        signals = [
            {"card_name": "Low", "net_profit": 5.00, "margin_pct": 10.0, "tcgplayer_url": "1"},
            {"card_name": "High", "net_profit": 50.00, "margin_pct": 30.0, "tcgplayer_url": "2"},
            {"card_name": "Mid", "net_profit": 25.00, "margin_pct": 20.0, "tcgplayer_url": "3"},
        ]
        text = _fmt_digest_body(signals)

        high_pos = text.find("High")
        mid_pos = text.find("Mid")
        low_pos = text.find("Low")

        assert high_pos < mid_pos < low_pos, "Signals should be ranked High → Mid → Low"

    def test_fmt_digest_body_caps_at_5_signals(self) -> None:
        """Only top 5 signals are shown even if more are provided."""
        signals = [
            {"card_name": f"Card{i}", "net_profit": float(100 - i), "margin_pct": 15.0, "tcgplayer_url": "x"}
            for i in range(10)
        ]
        text = _fmt_digest_body(signals)

        assert "Signals found: 10" in text
        assert "🏆 *Top 5 Signals*" in text

        for i in range(5):
            assert f"Card{i}" in text

        assert "Card5" not in text, "Card6+ should not appear"

    def test_fmt_digest_body_average_margin_calculation(self) -> None:
        """Average margin is correctly computed and displayed."""
        signals = [
            {"card_name": "A", "net_profit": 10.0, "margin_pct": 10.0, "tcgplayer_url": "1"},
            {"card_name": "B", "net_profit": 20.0, "margin_pct": 20.0, "tcgplayer_url": "2"},
            {"card_name": "C", "net_profit": 30.0, "margin_pct": 30.0, "tcgplayer_url": "3"},
        ]
        text = _fmt_digest_body(signals)

        assert "Avg margin: 20\\.0%" in text

    def test_fmt_digest_body_best_opportunity_is_highest_profit(self) -> None:
        """Best opportunity stat shows the highest net_profit signal."""
        signals = [
            {"card_name": "A", "net_profit": 10.0, "margin_pct": 10.0, "tcgplayer_url": "1"},
            {"card_name": "B", "net_profit": 50.0, "margin_pct": 25.0, "tcgplayer_url": "2"},
        ]
        text = _fmt_digest_body(signals)

        assert "Best opportunity: \\$50\\.00" in text


@pytest.mark.asyncio
class TestTelegramNotifier:
    """Test the TelegramNotifier class."""

    @patch("src.signals.telegram.Bot")
    async def test_init_enabled_with_token(self, mock_bot_class: MagicMock) -> None:
        """Constructor properly initializes when token is provided."""
        notifier = TelegramNotifier(bot_token="test_token_123")

        assert notifier._enabled is True
        assert notifier._bot is not None
        mock_bot_class.assert_called_once_with(token="test_token_123")

    @patch("src.signals.telegram.Bot")
    async def test_init_disabled_without_token(self, mock_bot_class: MagicMock) -> None:
        """Constructor gracefully disables when no token provided."""
        notifier = TelegramNotifier(bot_token=None)

        assert notifier._enabled is False
        assert notifier._bot is None
        mock_bot_class.assert_not_called()

    @patch("src.signals.telegram.Bot")
    async def test_init_disabled_with_empty_string(self, mock_bot_class: MagicMock) -> None:
        """Constructor treats empty string same as None (graceful degradation)."""
        notifier = TelegramNotifier(bot_token="")

        assert notifier._enabled is False
        assert notifier._bot is None

    @patch("src.signals.telegram.Bot")
    async def test_context_manager_enter_exit(self, mock_bot_class: MagicMock) -> None:
        """Context manager properly enters and exits."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        async with TelegramNotifier(bot_token="test") as notifier:
            assert notifier._enabled is True

        mock_bot.__aenter__.assert_called_once()
        mock_bot.__aexit__.assert_called_once()

    @patch("src.signals.telegram.Bot")
    async def test_context_manager_disabled_bot(self, mock_bot_class: MagicMock) -> None:
        """Context manager handles disabled bot gracefully."""
        async with TelegramNotifier(bot_token=None) as notifier:
            assert notifier._enabled is False

        mock_bot_class.assert_not_called()

    @patch("src.signals.telegram.Bot")
    async def test_send_signal_success(self, mock_bot_class: MagicMock) -> None:
        """send_signal returns True on successful delivery."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signal = {
            "card_id": "sv1-25",
            "card_name": "Pikachu",
            "net_profit": 10.0,
            "margin_pct": 15.0,
            "cm_price_eur": 20.0,
            "tcg_price_usd": 25.0,
            "condition": "NM",
            "velocity_tier": "1",
            "headache_tier": "1",
            "tcgplayer_url": "https://tcgplayer.com/1",
            "cardmarket_url": "https://cardmarket.com/1",
        }

        result = await notifier.send_signal(12345, signal)

        assert result is True
        mock_bot.send_message.assert_called_once()

    @patch("src.signals.telegram.Bot")
    async def test_send_signal_disabled(self, mock_bot_class: MagicMock) -> None:
        """send_signal returns False when notifier is disabled."""
        notifier = TelegramNotifier(bot_token=None)
        signal = {"card_id": "sv1-25", "card_name": "Test"}

        result = await notifier.send_signal(12345, signal)

        assert result is False

    @patch("src.signals.telegram.Bot")
    async def test_send_signal_telegram_error(self, mock_bot_class: MagicMock) -> None:
        """send_signal returns False and logs on Telegram API error."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = telegram.error.TelegramError("API Error")
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signal = {
            "card_id": "sv1-25",
            "card_name": "Pikachu",
            "net_profit": 10.0,
            "margin_pct": 15.0,
            "cm_price_eur": 20.0,
            "tcg_price_usd": 25.0,
            "condition": "NM",
            "velocity_tier": "1",
            "headache_tier": "1",
            "tcgplayer_url": "https://tcgplayer.com/1",
            "cardmarket_url": "https://cardmarket.com/1",
        }

        result = await notifier.send_signal(12345, signal)

        assert result is False

    @patch("src.signals.telegram.Bot")
    async def test_send_batch_signals_success(self, mock_bot_class: MagicMock) -> None:
        """send_batch_signals returns count of successful sends."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signals = [
            {
                "card_id": f"sv1-{i}",
                "card_name": f"Card{i}",
                "net_profit": float(i * 10),
                "margin_pct": 15.0,
                "cm_price_eur": 20.0,
                "tcg_price_usd": 25.0,
                "condition": "NM",
                "velocity_tier": "1",
                "headache_tier": "1",
                "tcgplayer_url": f"https://tcgplayer.com/{i}",
                "cardmarket_url": f"https://cardmarket.com/{i}",
            }
            for i in range(3)
        ]

        result = await notifier.send_batch_signals(12345, signals)

        assert result == 3
        assert mock_bot.send_message.call_count == 3

    @patch("src.signals.telegram.Bot")
    async def test_send_batch_signals_rate_limiting(self, mock_bot_class: MagicMock) -> None:
        """send_batch_signals respects rate limiting between messages."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signals = [{
            "card_id": "sv1-1",
            "card_name": "Card1",
            "net_profit": 10.0,
            "margin_pct": 15.0,
            "cm_price_eur": 20.0,
            "tcg_price_usd": 25.0,
            "condition": "NM",
            "velocity_tier": "1",
            "headache_tier": "1",
            "tcgplayer_url": "https://tcgplayer.com/1",
            "cardmarket_url": "https://cardmarket.com/1",
        } for _ in range(2)]

        import time
        start = time.time()
        await notifier.send_batch_signals(12345, signals)
        elapsed = time.time() - start

        assert elapsed >= 1.0, "Should have rate-limited for at least 1 second between 2 messages"

    @patch("src.signals.telegram.Bot")
    async def test_send_batch_signals_disabled(self, mock_bot_class: MagicMock) -> None:
        """send_batch_signals returns 0 when notifier is disabled."""
        notifier = TelegramNotifier(bot_token=None)
        signals = [{"card_id": "sv1-1", "card_name": "Test"}]

        result = await notifier.send_batch_signals(12345, signals)

        assert result == 0

    @patch("src.signals.telegram.Bot")
    async def test_send_daily_digest_success(self, mock_bot_class: MagicMock) -> None:
        """send_daily_digest returns True on successful delivery."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signals = [
            {
                "card_id": f"sv1-{i}",
                "card_name": f"Card{i}",
                "net_profit": float(i * 10),
                "margin_pct": 15.0 + i,
                "tcgplayer_url": f"https://tcgplayer.com/{i}",
            }
            for i in range(3)
        ]

        result = await notifier.send_daily_digest(12345, signals)

        assert result is True
        mock_bot.send_message.assert_called_once()

    @patch("src.signals.telegram.Bot")
    async def test_send_daily_digest_empty_list(self, mock_bot_class: MagicMock) -> None:
        """send_daily_digest returns False for empty signal list."""
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")

        result = await notifier.send_daily_digest(12345, [])

        assert result is False
        mock_bot.send_message.assert_not_called()

    @patch("src.signals.telegram.Bot")
    async def test_send_daily_digest_disabled(self, mock_bot_class: MagicMock) -> None:
        """send_daily_digest returns False when notifier is disabled."""
        notifier = TelegramNotifier(bot_token=None)
        signals = [{"card_id": "sv1-1", "card_name": "Test", "net_profit": 10.0, "margin_pct": 15.0, "tcgplayer_url": "x"}]

        result = await notifier.send_daily_digest(12345, signals)

        assert result is False

    @patch("src.signals.telegram.Bot")
    async def test_send_daily_digest_telegram_error(self, mock_bot_class: MagicMock) -> None:
        """send_daily_digest returns False and logs on Telegram API error."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = telegram.error.TelegramError("API Error")
        mock_bot_class.return_value = mock_bot

        notifier = TelegramNotifier(bot_token="test")
        signals = [
            {
                "card_id": "sv1-1",
                "card_name": "Card1",
                "net_profit": 10.0,
                "margin_pct": 15.0,
                "tcgplayer_url": "https://tcgplayer.com/1",
            }
        ]

        result = await notifier.send_daily_digest(12345, signals)

        assert result is False
