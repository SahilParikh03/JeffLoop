"""
TCG Radar — Seller Density Score & Bundle Logic (Section 4.5)

SDS = count of profitable cards from the same seller in a single scan.
Determines shipping amortization and signal suppression.

SDS tiers:
- SDS >= 5: "Bundle Alert" — shipping amortized across bundle
- SDS 2-4: "Partial Bundle" — partial amortization
- SDS = 1: "Single Card" — full single-card shipping applies

Suppression rule: SDS=1 + card < $25 + net_profit <= 0 → suppress signal
(A $10 card with $15 shipping is not arbitrage)
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import NamedTuple

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


class BundleTier(str, Enum):
    """SDS classification tier."""
    BUNDLE_ALERT = "bundle_alert"     # SDS >= 5
    PARTIAL_BUNDLE = "partial_bundle" # SDS 2-4
    SINGLE_CARD = "single_card"       # SDS = 1


class BundleResult(NamedTuple):
    """Result of bundle/SDS evaluation."""
    sds: int
    tier: BundleTier
    suppress: bool
    reason: str


def calculate_seller_density_score(
    seller_card_count: int,
    card_price_usd: Decimal,
    net_profit: Decimal,
) -> BundleResult:
    """
    Evaluate bundle opportunity based on Seller Density Score.

    Does NOT recalculate P_real — accepts pre-computed net_profit.

    Suppression logic:
    - SDS=1 AND card_price < $25 AND net_profit <= 0 → suppress
    - All other cases → do not suppress

    Args:
        seller_card_count: Number of profitable cards from this seller.
        card_price_usd: Card's effective price in USD.
        net_profit: Pre-computed net profit (from profit.py).

    Returns:
        BundleResult with SDS, tier classification, suppress flag, and reason.

    Raises:
        ValueError: If seller_card_count < 1.
    """
    if seller_card_count < 1:
        raise ValueError("seller_card_count must be at least 1")

    sds = seller_card_count

    # Classify tier
    if sds >= settings.SDS_BUNDLE_ALERT:
        tier = BundleTier.BUNDLE_ALERT
    elif sds >= settings.SDS_PARTIAL_MIN:
        tier = BundleTier.PARTIAL_BUNDLE
    else:
        tier = BundleTier.SINGLE_CARD

    # Suppression check: SDS=1 + sub-$25 + unprofitable
    suppress = False
    reason = "ok"
    if (
        sds == settings.SDS_SINGLE
        and card_price_usd < settings.BUNDLE_SINGLE_CARD_THRESHOLD
        and net_profit <= Decimal("0")
    ):
        suppress = True
        reason = (
            f"SDS=1, card_price=${card_price_usd} < ${settings.BUNDLE_SINGLE_CARD_THRESHOLD}, "
            f"net_profit=${net_profit} <= $0"
        )

    logger.debug(
        "bundle_evaluated",
        sds=sds,
        tier=tier.value,
        card_price_usd=str(card_price_usd),
        net_profit=str(net_profit),
        suppress=suppress,
        reason=reason,
        source="bundle",
    )
    return BundleResult(sds=sds, tier=tier, suppress=suppress, reason=reason)
