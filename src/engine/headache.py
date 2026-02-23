"""
TCG Radar - Headache Score (Section 4.4)

Labor-to-Loot formula:
    H = Net_Profit / Number_of_Transactions
"""

from __future__ import annotations

from decimal import Decimal

from src.config import HeadacheTier, settings


def calculate_headache_score(net_profit: Decimal, num_transactions: int) -> tuple[Decimal, int]:
    """
    Calculate headache score and classify its labor tier.

    Tier rules:
    - H > HEADACHE_TIER_1_FLOOR -> tier 1
    - HEADACHE_TIER_2_FLOOR < H <= HEADACHE_TIER_1_FLOOR -> tier 2
    - H <= HEADACHE_TIER_2_FLOOR -> tier 3

    Args:
        net_profit: Total expected net profit for the opportunity.
        num_transactions: Number of transactions needed to realize that profit.

    Returns:
        Tuple of (headache_score, tier_number).

    Raises:
        ValueError: If num_transactions is zero or negative.
    """
    if num_transactions <= 0:
        raise ValueError("num_transactions must be greater than 0")

    headache_score = net_profit / Decimal(num_transactions)

    if headache_score > settings.HEADACHE_TIER_1_FLOOR:
        tier = HeadacheTier.TIER_1.value
    elif headache_score > settings.HEADACHE_TIER_2_FLOOR:
        tier = HeadacheTier.TIER_2.value
    else:
        tier = HeadacheTier.TIER_3.value

    return headache_score, tier

