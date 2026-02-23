"""
TCG Radar — User Priority Rotation (Section 14)

Determines signal delivery order based on user subscription tier
and priority score. Higher-tier users see signals first.

Ordering: Tier > priority_score > category_match

Tiers:
- premium: First priority, exclusive window
- standard: Second priority, after premium window expires
- free: Last, only gets cascaded/demoted signals

Priority score tracks engagement — users who act on signals get
higher priority within their tier.
"""

from __future__ import annotations

from decimal import Decimal
from enum import IntEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class UserTier(IntEnum):
    """Subscription tier with numeric ordering for sorting."""
    PREMIUM = 3
    STANDARD = 2
    FREE = 1


def score_candidates(
    candidates: list[dict[str, Any]],
    signal_category: str | None = None,
) -> list[dict[str, Any]]:
    """
    Sort user candidates by delivery priority.

    Ordering (descending priority):
    1. Tier (premium > standard > free)
    2. priority_score (higher = more engaged user)
    3. category_match bonus (if signal category matches user preference)

    Each candidate dict must have:
    - "user_id": str
    - "tier": str — one of "premium", "standard", "free"
    - "priority_score": float or Decimal
    - "categories": list[str] | None — user's preferred categories

    Args:
        candidates: List of user candidate dicts.
        signal_category: Signal's category for matching bonus.

    Returns:
        Candidates sorted by priority (highest first).
    """
    scored: list[tuple[int, float, int, dict[str, Any]]] = []

    for candidate in candidates:
        tier_name = candidate.get("tier", "free").lower()
        try:
            tier_value = UserTier[tier_name.upper()].value
        except KeyError:
            tier_value = UserTier.FREE.value

        priority = float(candidate.get("priority_score", 0))

        category_bonus = 0
        if signal_category and candidate.get("categories"):
            if signal_category in candidate["categories"]:
                category_bonus = 1

        scored.append((tier_value, priority, category_bonus, candidate))

    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)

    result = [item[3] for item in scored]
    logger.debug(
        "candidates_scored",
        total=len(result),
        signal_category=signal_category,
        top_user=result[0].get("user_id") if result else None,
        source="rotation",
    )
    return result


def filter_by_category(
    candidates: list[dict[str, Any]],
    signal_category: str,
) -> list[dict[str, Any]]:
    """
    Filter candidates to those interested in a specific category.

    Users with no category preference (None or empty) pass through
    as "interested in everything."

    Args:
        candidates: List of user candidate dicts.
        signal_category: The signal's category to match.

    Returns:
        Filtered list of candidates.
    """
    result = []
    for c in candidates:
        categories = c.get("categories")
        if not categories or signal_category in categories:
            result.append(c)

    logger.debug(
        "candidates_filtered_by_category",
        total_before=len(candidates),
        total_after=len(result),
        category=signal_category,
        source="rotation",
    )
    return result


def demote_user(
    user: dict[str, Any],
    reason: str = "cascade_limit_reached",
) -> dict[str, Any]:
    """
    Demote a user's effective tier for the current signal.

    Does NOT modify the user's actual subscription — only their
    delivery priority for this signal cycle.

    Args:
        user: User candidate dict.
        reason: Why the demotion occurred.

    Returns:
        Copy of user dict with tier set to "free" and demotion metadata.
    """
    demoted = dict(user)
    original_tier = demoted.get("tier", "unknown")
    demoted["tier"] = "free"
    demoted["demoted_from"] = original_tier
    demoted["demotion_reason"] = reason

    logger.info(
        "user_demoted",
        user_id=user.get("user_id"),
        original_tier=original_tier,
        new_tier="free",
        reason=reason,
        source="rotation",
    )
    return demoted
