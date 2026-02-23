"""
TCG Radar — Discord Notification Delivery (Layer 4)

Delivers formatted signal alerts via Discord webhook/bot embeds.
Mirrors the TelegramNotifier interface for consistent delivery across channels.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

# Rate limit: Discord allows 5 messages per 5 seconds per channel
_DISCORD_RATE_LIMIT_SECONDS: float = 1.0
_DIGEST_MAX_SIGNALS: int = 5


def _fmt_signal_embed(signal: dict[str, Any]) -> dict[str, Any]:
    """Format a signal as a Discord embed dict."""
    card_name = str(signal.get("card_name", "Unknown"))
    net_profit = f"{float(signal.get('net_profit', 0)):.2f}"
    margin_pct = f"{float(signal.get('margin_pct', 0)):.1f}"
    cm_price = f"{float(signal.get('cm_price_eur', 0)):.2f}"
    tcg_price = f"{float(signal.get('tcg_price_usd', 0)):.2f}"
    condition = str(signal.get("condition", "N/A"))
    velocity_tier = str(signal.get("velocity_tier", "N/A"))
    headache_tier = str(signal.get("headache_tier", "N/A"))
    tcgplayer_url = signal.get("tcgplayer_url", "")
    cardmarket_url = signal.get("cardmarket_url", "")

    return {
        "title": f"TCG Radar Signal: {card_name}",
        "color": 0x00FF00,  # green
        "fields": [
            {"name": "Net Profit", "value": f"${net_profit} ({margin_pct}%)", "inline": True},
            {"name": "CM Price", "value": f"\u20ac{cm_price}", "inline": True},
            {"name": "TCG Price", "value": f"${tcg_price}", "inline": True},
            {"name": "Condition", "value": condition, "inline": True},
            {"name": "Velocity", "value": f"Tier {velocity_tier}", "inline": True},
            {"name": "Headache", "value": f"Tier {headache_tier}", "inline": True},
        ],
        "description": f"[TCGPlayer]({tcgplayer_url}) | [Cardmarket]({cardmarket_url})",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _fmt_digest_embed(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Format a daily digest as a Discord embed dict."""
    top = sorted(signals, key=lambda s: float(s.get("net_profit", 0)), reverse=True)[:_DIGEST_MAX_SIGNALS]
    total = len(signals)
    avg_margin = sum(float(s.get("margin_pct", 0)) for s in signals) / total if total else 0.0
    best_profit = float(top[0].get("net_profit", 0)) if top else 0.0
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = []
    for rank, sig in enumerate(top, start=1):
        name = sig.get("card_name", "Unknown")
        profit = f"{float(sig.get('net_profit', 0)):.2f}"
        margin = f"{float(sig.get('margin_pct', 0)):.1f}"
        lines.append(f"{rank}. **{name}** — ${profit} ({margin}%)")

    return {
        "title": f"TCG Radar Daily Digest — {date_str}",
        "color": 0x3498DB,  # blue
        "fields": [
            {"name": "Signals Found", "value": str(total), "inline": True},
            {"name": "Avg Margin", "value": f"{avg_margin:.1f}%", "inline": True},
            {"name": "Best Opportunity", "value": f"${best_profit:.2f}", "inline": True},
        ],
        "description": "\n".join(lines) if lines else "No signals today.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


class DiscordNotifier:
    """
    Delivers TCG Radar signals to Discord channels via httpx.

    Uses the Discord Bot HTTP API directly (no discord.py dependency needed).
    Mirrors TelegramNotifier interface.

    Usage:
        async with DiscordNotifier() as notifier:
            await notifier.send_signal(channel_id, signal)
    """

    DISCORD_API_BASE = "https://discord.com/api/v10"

    def __init__(self, bot_token: str | None = None) -> None:
        self._token = bot_token or settings.DISCORD_BOT_TOKEN
        self._enabled = bool(self._token)
        self._client: Any = None  # httpx.AsyncClient, set in __aenter__

        if not self._enabled:
            logger.warning(
                "discord_notifier_disabled",
                reason="DISCORD_BOT_TOKEN is empty or not set",
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    async def __aenter__(self) -> DiscordNotifier:
        if self._enabled:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.DISCORD_API_BASE,
                headers={
                    "Authorization": f"Bot {self._token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def send_signal(self, channel_id: int, signal: dict[str, Any]) -> bool:
        """
        Send a single signal as a Discord embed.

        Args:
            channel_id: Discord channel ID to post to.
            signal: Signal dict from SignalGenerator. Required keys:
                card_name, net_profit, margin_pct, headache_tier,
                velocity_tier, tcgplayer_url, cardmarket_url,
                condition, cm_price_eur, tcg_price_usd.

        Returns:
            True if the message was delivered, False otherwise.
        """
        if not self._enabled or self._client is None:
            return False

        card_id = signal.get("card_id", "unknown")
        try:
            embed = _fmt_signal_embed(signal)
            response = await self._client.post(
                f"/channels/{channel_id}/messages",
                json={"embeds": [embed]},
            )
            response.raise_for_status()
            logger.info(
                "discord_signal_sent",
                card_id=card_id,
                channel_id=channel_id,
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return True
        except Exception as exc:
            logger.error(
                "discord_signal_send_failed",
                card_id=card_id,
                channel_id=channel_id,
                error=str(exc),
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False

    async def send_batch_signals(self, channel_id: int, signals: list[dict[str, Any]]) -> int:
        """
        Send multiple signals with rate limiting.

        Sends one message per second to stay within Discord's rate limits.
        Partial failures are logged and skipped; successful sends are counted.

        Args:
            channel_id: Discord channel ID to post to.
            signals: List of signal dicts. See send_signal for required keys.

        Returns:
            Count of messages successfully delivered.
        """
        if not self._enabled:
            return 0

        delivered = 0
        for index, signal in enumerate(signals):
            success = await self.send_signal(channel_id, signal)
            if success:
                delivered += 1
            if index < len(signals) - 1:
                await asyncio.sleep(_DISCORD_RATE_LIMIT_SECONDS)

        logger.info(
            "discord_batch_sent",
            channel_id=channel_id,
            total=len(signals),
            delivered=delivered,
            source="discord",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return delivered

    async def send_daily_digest(self, channel_id: int, signals: list[dict[str, Any]]) -> bool:
        """
        Send daily digest as a single embed.

        Top 5 signals by net profit are listed in the body. Aggregate stats
        (total count, average margin, best single opportunity) appear as fields.

        Args:
            channel_id: Discord channel ID to post to.
            signals: Full list of signals for the day.

        Returns:
            True if the digest was delivered, False otherwise.
        """
        if not self._enabled or self._client is None:
            return False

        if not signals:
            logger.info(
                "discord_digest_skipped",
                channel_id=channel_id,
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False

        try:
            embed = _fmt_digest_embed(signals)
            response = await self._client.post(
                f"/channels/{channel_id}/messages",
                json={"embeds": [embed]},
            )
            response.raise_for_status()
            logger.info(
                "discord_digest_sent",
                channel_id=channel_id,
                total_signals=len(signals),
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return True
        except Exception as exc:
            logger.error(
                "discord_digest_failed",
                channel_id=channel_id,
                error=str(exc),
                source="discord",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return False
