"""
TCG Radar — Telegram Notification Delivery (Layer 4)

Delivers formatted signal alerts to subscribers via the Telegram Bot API.
Supports single signals, rate-limited batch delivery, and daily digest summaries.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import structlog
import telegram
import telegram.error
from telegram import Bot

from src.config import settings

logger = structlog.get_logger(__name__)

# Telegram Bot API enforces 1 message/second per chat to avoid 429 flood errors.
_TELEGRAM_RATE_LIMIT_SECONDS: int = 1

# Daily digest caps at top N signals to keep the message scannable.
_DIGEST_MAX_SIGNALS: int = 5

# MarkdownV2 requires escaping these characters outside of formatting contexts.
_MDV2_SPECIAL_CHARS: re.Pattern[str] = re.compile(
    r"([_\*\[\]\(\)~`>#\+\-=\|\{\}\.!])"
)


def _escape_mdv2(value: str) -> str:
    """Escape a plain string for safe embedding in a MarkdownV2 message."""
    return _MDV2_SPECIAL_CHARS.sub(r"\\\1", value)


def _fmt_signal_body(signal: dict[str, Any]) -> str:
    """
    Format a single signal dict as a MarkdownV2 message body.

    Numeric fields are rounded for readability. URLs are passed through
    unescaped — they appear inside [text](url) Markdown syntax where
    special chars are allowed by the MarkdownV2 spec.
    """
    card_name = _escape_mdv2(str(signal.get("card_name", "Unknown")))
    net_profit = _escape_mdv2(f"{float(signal.get('net_profit', 0)):.2f}")
    margin_pct = _escape_mdv2(f"{float(signal.get('margin_pct', 0)):.1f}")
    cm_price = _escape_mdv2(f"{float(signal.get('cm_price_eur', 0)):.2f}")
    tcg_price = _escape_mdv2(f"{float(signal.get('tcg_price_usd', 0)):.2f}")
    condition = _escape_mdv2(str(signal.get("condition", "N/A")))
    velocity_tier = _escape_mdv2(str(signal.get("velocity_tier", "N/A")))
    headache_tier = _escape_mdv2(str(signal.get("headache_tier", "N/A")))
    tcgplayer_url = signal.get("tcgplayer_url", "")
    cardmarket_url = signal.get("cardmarket_url", "")

    return (
        "🎯 *TCG Radar Signal*\n"
        f"📦 {card_name}\n"
        f"💰 Net Profit: \\${net_profit} \\({margin_pct}%\\)\n"
        f"🏷️ CM: €{cm_price} → TCG: \\${tcg_price}\n"
        f"📊 Condition: {condition}\n"
        f"⚡ Velocity: Tier {velocity_tier} \\| 😤 Headache: Tier {headache_tier}\n"
        f"🔗 [TCGPlayer]({tcgplayer_url}) \\| [Cardmarket]({cardmarket_url})"
    )


def _fmt_digest_body(signals: list[dict[str, Any]]) -> str:
    """
    Format a daily digest message from the top N signals by net profit.

    Includes aggregate stats and a ranked list of best opportunities.
    """
    top = sorted(signals, key=lambda s: float(s.get("net_profit", 0)), reverse=True)[
        :_DIGEST_MAX_SIGNALS
    ]

    total = len(signals)
    avg_margin = (
        sum(float(s.get("margin_pct", 0)) for s in signals) / total if total else 0.0
    )
    best_profit = float(top[0].get("net_profit", 0)) if top else 0.0

    avg_margin_str = _escape_mdv2(f"{avg_margin:.1f}")
    best_profit_str = _escape_mdv2(f"{best_profit:.2f}")
    total_str = _escape_mdv2(str(total))
    date_str = _escape_mdv2(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    lines: list[str] = [
        f"📅 *TCG Radar Daily Digest — {date_str}*\n",
        f"📊 *Summary*",
        f"  • Signals found: {total_str}",
        f"  • Avg margin: {avg_margin_str}%",
        f"  • Best opportunity: \\${best_profit_str}\n",
        f"🏆 *Top {_escape_mdv2(str(len(top)))} Signals*",
    ]

    for rank, signal in enumerate(top, start=1):
        card_name = _escape_mdv2(str(signal.get("card_name", "Unknown")))
        net_profit = _escape_mdv2(f"{float(signal.get('net_profit', 0)):.2f}")
        margin_pct = _escape_mdv2(f"{float(signal.get('margin_pct', 0)):.1f}")
        tcgplayer_url = signal.get("tcgplayer_url", "")
        rank_str = _escape_mdv2(str(rank))
        lines.append(
            f"  {rank_str}\\. [{card_name}]({tcgplayer_url}) — "
            f"\\${net_profit} \\({margin_pct}%\\)"
        )

    return "\n".join(lines)


class TelegramNotifier:
    """
    Delivers TCG Radar signals to Telegram subscribers.

    Use as an async context manager to ensure the underlying Bot session
    is cleanly opened and closed:

        async with TelegramNotifier() as notifier:
            await notifier.send_signal(chat_id, signal)

    When bot_token is absent, all methods degrade gracefully and log a
    warning — no exceptions are raised and callers receive empty/zero returns.
    """

    def __init__(self, bot_token: str | None = None) -> None:
        token = bot_token or settings.TELEGRAM_BOT_TOKEN
        self._enabled = bool(token)
        self._bot: Bot | None = Bot(token=token) if self._enabled else None

        if not self._enabled:
            logger.warning(
                "telegram_notifier_disabled",
                reason="TELEGRAM_BOT_TOKEN is empty or not set",
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    async def __aenter__(self) -> TelegramNotifier:
        if self._bot is not None:
            await self._bot.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self._bot is not None:
            await self._bot.__aexit__(exc_type, exc_val, exc_tb)

    async def send_signal(self, chat_id: int, signal: dict[str, Any]) -> bool:
        """
        Send a single formatted signal alert to a Telegram chat.

        Args:
            chat_id: Telegram chat ID for the recipient.
            signal: Signal dict from SignalGenerator. Required keys:
                card_name, net_profit, margin_pct, headache_tier,
                velocity_tier, tcgplayer_url, cardmarket_url,
                condition, cm_price_eur, tcg_price_usd.

        Returns:
            True if the message was delivered, False otherwise.
        """
        if not self._enabled:
            return False

        card_id = signal.get("card_id", "unknown")
        try:
            text = _fmt_signal_body(signal)
            await self._bot.send_message(  # type: ignore[union-attr]
                chat_id=chat_id,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            logger.info(
                "signal_sent",
                card_id=card_id,
                chat_id=chat_id,
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return True

        except telegram.error.TelegramError as exc:
            logger.error(
                "signal_send_failed",
                card_id=card_id,
                chat_id=chat_id,
                error=str(exc),
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False

    async def send_batch_signals(
        self, chat_id: int, signals: list[dict[str, Any]]
    ) -> int:
        """
        Send multiple signal alerts with Telegram-compliant rate limiting.

        Sends one message per second to stay within Telegram's flood limits.
        Partial failures are logged and skipped; successful sends are counted.

        Args:
            chat_id: Telegram chat ID for the recipient.
            signals: List of signal dicts. See send_signal for required keys.

        Returns:
            Count of messages successfully delivered.
        """
        if not self._enabled:
            return 0

        delivered = 0
        for index, signal in enumerate(signals):
            success = await self.send_signal(chat_id, signal)
            if success:
                delivered += 1

            # Rate limit between messages; skip the sleep after the last one.
            if index < len(signals) - 1:
                await asyncio.sleep(_TELEGRAM_RATE_LIMIT_SECONDS)

        logger.info(
            "batch_signals_sent",
            chat_id=chat_id,
            total=len(signals),
            delivered=delivered,
            source="telegram",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return delivered

    async def send_daily_digest(
        self, chat_id: int, signals: list[dict[str, Any]]
    ) -> bool:
        """
        Send a consolidated daily summary of all signals as one message.

        Top 5 by net profit are listed in the body. Aggregate stats
        (total count, average margin, best single opportunity) appear
        at the top of the message.

        Args:
            chat_id: Telegram chat ID for the recipient.
            signals: Full list of signals for the day.

        Returns:
            True if the digest was delivered, False otherwise.
        """
        if not self._enabled:
            return False

        if not signals:
            logger.info(
                "digest_skipped_no_signals",
                chat_id=chat_id,
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False

        try:
            text = _fmt_digest_body(signals)
            await self._bot.send_message(  # type: ignore[union-attr]
                chat_id=chat_id,
                text=text,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            logger.info(
                "daily_digest_sent",
                chat_id=chat_id,
                total_signals=len(signals),
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return True

        except telegram.error.TelegramError as exc:
            logger.error(
                "daily_digest_failed",
                chat_id=chat_id,
                error=str(exc),
                source="telegram",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False
