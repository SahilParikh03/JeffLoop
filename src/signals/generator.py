"""
TCG Radar — Signal Generator (Layer 4 Orchestrator)

Executes Layer 2 Rules Engine pipeline in strict order per CLAUDE.md:
1. Variant Check — validate card identity (Section 4.7)
2. Seller Quality — rating ≥97%, sales ≥100 (Section 5)
3. Condition Mapping — pessimistic Cardmarket→TCGPlayer (Section 4.6)
4. Net Profit — calculate and threshold (Section 4.1)
5. Velocity Score — sales liquidity tier (Section 4.2)
6. Trend Classification — falling knife filter (Section 4.3)
7. Maturity Decay — set age hype decay (Section 4.2.2)
8. Rotation Risk — calendar overlay (Section 7)
9. Headache Score — labor-to-loot ratio (Section 4.4)
10. Bundle Logic — seller density score (Section 4.5)

Calls REAL engine modules, not stubs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import settings
from src.engine.bundle import calculate_seller_density_score
from src.engine.headache import calculate_headache_score
from src.engine.maturity import calculate_maturity_decay
from src.engine.profit import calculate_net_profit
from src.engine.rotation import check_rotation_risk
from src.engine.seller_quality import check_seller_quality
from src.engine.trend import classify_trend
from src.engine.variant_check import validate_variant
from src.engine.velocity import calculate_velocity_score
from src.models.card_metadata import CardMetadata
from src.models.market_price import MarketPrice
from src.models.user_profile import UserProfile
from src.signals.deep_link import build_signal_urls
from src.signals.telegram import TelegramNotifier
from src.utils.condition_map import CardmarketGrade, map_condition
from src.utils.forex import get_current_forex_rate

logger = structlog.get_logger(__name__)


class SignalGenerator:
    """Orchestrates Layer 2 rules engine and Layer 4 signal generation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notifier: TelegramNotifier,
    ):
        self.session_factory = session_factory
        self.notifier = notifier

    async def scan_for_signals(self) -> list[dict[str, Any]]:
        """
        Scan market prices and execute Layer 2 → Layer 4 pipeline.

        Returns signals sorted by net_profit descending.
        """
        signals: list[dict[str, Any]] = []
        filter_counts = {
            "initial": 0, "variant": 0, "seller": 0, "condition": 0,
            "profit": 0, "velocity": 0, "trend": 0, "maturity": 0,
            "rotation": 0, "headache": 0, "bundle": 0,
        }

        try:
            async with self.session_factory() as session:
                result = await session.execute(
                    select(MarketPrice).where(
                        MarketPrice.price_usd.isnot(None),
                        MarketPrice.price_eur.isnot(None),
                    )
                )
                prices = result.scalars().all()
                filter_counts["initial"] = len(prices)

                logger.info("scan_started", total_cards=len(prices), source="generator")

                for price in prices:
                    try:
                        # Load metadata once per card
                        meta_res = await session.execute(
                            select(CardMetadata).where(CardMetadata.card_id == price.card_id)
                        )
                        metadata = meta_res.scalar()

                        # 1. VARIANT CHECK (Section 4.7)
                        # Compare price source card_id against metadata canonical ID
                        canonical_id = metadata.card_id if metadata else price.card_id
                        if validate_variant(price.card_id, canonical_id) != "MATCH":
                            continue
                        filter_counts["variant"] += 1

                        # 2. SELLER QUALITY (Section 5)
                        # PHASE_2_STUB: Hardcoded seller rating/sales — JustTCG API doesn't return seller-level data. Needs Layer 3 scraping.
                        if not check_seller_quality(Decimal("98.5"), 100):
                            continue
                        filter_counts["seller"] += 1

                        # 3. CONDITION MAPPING (Section 4.6)
                        # Use actual condition from listing when available
                        condition_str = price.condition or CardmarketGrade.NEAR_MINT.value
                        try:
                            condition_grade = CardmarketGrade(condition_str.strip().upper()) if price.condition else CardmarketGrade.NEAR_MINT
                            mapping = map_condition(condition_grade)
                        except ValueError:
                            continue
                        filter_counts["condition"] += 1

                        # 4. NET PROFIT (Section 4.1)
                        profit = calculate_net_profit(
                            cm_price_eur=price.price_eur,
                            tcg_price_usd=price.price_usd,
                            forex_rate=get_current_forex_rate(),
                            condition=condition_grade.value,
                            customs_regime=settings.CUSTOMS_REGIME.value,
                        )
                        if profit["net_profit"] < settings.DEFAULT_MIN_PROFIT_THRESHOLD:
                            continue
                        filter_counts["profit"] += 1

                        # 5. VELOCITY SCORE (Section 4.2)
                        # PHASE_2_STUB: Hardcoded velocity — needs Sales_30d and Active_Listings from PokeTrace API.
                        vel_score, vel_tier = calculate_velocity_score(Decimal("1.0"))
                        filter_counts["velocity"] += 1

                        # 6. TREND CLASSIFICATION (Section 4.3)
                        # PHASE_2_STUB: Hardcoded price_trend=0 — needs 7-day price history from multiple poll cycles.
                        trend_cls, trend_suppress = classify_trend(
                            vel_score, Decimal("0.00")
                        )
                        if trend_suppress:
                            continue
                        filter_counts["trend"] += 1

                        # 7. MATURITY DECAY (Section 4.2.2)
                        if metadata and metadata.set_release_date:
                            decay = calculate_maturity_decay(metadata.set_release_date)
                        else:
                            decay = Decimal("1.0")
                        filter_counts["maturity"] += 1

                        # 8. ROTATION RISK (Section 7)
                        reg_mark = metadata.regulation_mark if metadata else None
                        legality = metadata.legality_standard if metadata else None
                        rotation = check_rotation_risk(reg_mark, legality)
                        if rotation["risk_level"] in ("DANGER", "ROTATED"):
                            continue
                        filter_counts["rotation"] += 1

                        # 9. HEADACHE SCORE (Section 4.4)
                        headache, h_tier = calculate_headache_score(profit["net_profit"], 1)
                        filter_counts["headache"] += 1

                        # 10. BUNDLE LOGIC (Section 4.5)
                        # PHASE_2_STUB: Hardcoded seller_card_count=1 — needs seller stock queries via Layer 3 scraping.
                        bundle_result = calculate_seller_density_score(
                            seller_card_count=1,
                            card_price_usd=price.price_usd,
                            net_profit=profit["net_profit"],
                        )
                        if bundle_result.suppress:
                            continue
                        filter_counts["bundle"] += 1

                        # Build deep links
                        urls = build_signal_urls(
                            card_name=metadata.name if metadata else "Unknown",
                            set_name=metadata.set_name if metadata else None,
                            tcgplayer_url=metadata.tcgplayer_url if metadata else None,
                            cardmarket_url=metadata.cardmarket_url if metadata else None,
                        )

                        # Build signal with real data
                        signals.append({
                            "card_id": price.card_id,
                            "card_name": metadata.name if metadata else "Unknown",
                            "net_profit": profit["net_profit"],
                            "margin_pct": profit["margin_pct"],
                            "velocity_tier": f"tier_{vel_tier}",
                            "velocity_score": vel_score,
                            "maturity_decay": decay,
                            "headache_tier": h_tier,
                            "headache_score": headache,
                            "condition": condition_grade.value,
                            "cm_price_eur": price.price_eur,
                            "tcg_price_usd": price.price_usd,
                            "rotation_risk": rotation,
                            "trend_classification": trend_cls.value,
                            "bundle_tier": bundle_result.tier.value,
                            "tcgplayer_url": urls["tcgplayer_url"],
                            "cardmarket_url": urls["cardmarket_url"],
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "audit_snapshot": {
                                "prices": {
                                    "cm_eur": str(price.price_eur),
                                    "tcg_usd": str(price.price_usd),
                                },
                                "fees": {
                                    "revenue": str(profit["revenue"]),
                                    "tcg_fees": str(profit["tcg_fees"]),
                                    "customs": str(profit["customs"]),
                                    "shipping": str(profit["shipping"]),
                                },
                                "scores": {
                                    "velocity": str(vel_score),
                                    "maturity": str(decay),
                                    "headache": str(headache),
                                    "trend": trend_cls.value,
                                    "bundle_sds": str(bundle_result.sds),
                                },
                            },
                        })
                        logger.debug("signal_generated", card_id=price.card_id, source="generator")

                    except Exception as e:
                        logger.error("signal_error", card_id=str(price.card_id), error=str(e), source="generator")
                        continue

            # Sort by profit descending, limit
            signals.sort(key=lambda s: float(s["net_profit"]), reverse=True)
            max_signals = getattr(settings, "MAX_SIGNALS_PER_SCAN", 50)
            signals = signals[:max_signals]

            logger.info(
                "scan_completed",
                total_generated=len(signals),
                filters=filter_counts,
                source="generator",
            )

        except Exception as e:
            logger.error("scan_failed", error=str(e), source="generator")
            raise

        return signals

    async def run_and_notify(self, user_profiles: list[UserProfile]) -> int:
        """
        Scan for signals and deliver via Telegram to each user.

        Filters by user's min_profit_threshold.

        Returns: Total signals delivered.
        """
        total_delivered = 0

        try:
            signals = await self.scan_for_signals()
            logger.info(
                "notify_started",
                total_signals=len(signals),
                total_users=len(user_profiles),
                source="generator",
            )

            for user in user_profiles:
                try:
                    # Filter signals by user threshold
                    user_signals = [
                        s for s in signals
                        if s["net_profit"] >= user.min_profit_threshold
                    ]

                    if user_signals and user.telegram_chat_id:
                        count = await self.notifier.send_batch_signals(
                            user.telegram_chat_id, user_signals
                        )
                        total_delivered += count
                        logger.info(
                            "user_delivery",
                            user_id=str(user.id),
                            count=count,
                            source="generator",
                        )

                except Exception as e:
                    logger.error(
                        "user_delivery_error",
                        user_id=str(user.id),
                        error=str(e),
                        source="generator",
                    )
                    continue

            logger.info("notify_completed", total_delivered=total_delivered, source="generator")

        except Exception as e:
            logger.error("notify_failed", error=str(e), source="generator")

        return total_delivered
