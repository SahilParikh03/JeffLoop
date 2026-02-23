"""
TCG Radar — Condition Mapping Layer (Section 4.6)

Cross-platform grade translation: Cardmarket → TCGPlayer.
Uses MANDATORY pessimistic mapping per spec.

"Near Mint" means different things on different platforms. Cardmarket uses
a more granular scale. A Cardmarket "Excellent" card is frequently rejected
as "Lightly Played" on TCGPlayer, leading to returns.

Rule: When calculating P_real, always use the TCGPlayer-equivalent
condition price for P_target, not the NM price.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import NamedTuple

import structlog

logger = structlog.get_logger(__name__)


class CardmarketGrade(str, Enum):
    """
    Cardmarket condition grades.

    Enum values match the raw platform codes from Section 6
    (Data Points Extracted Per Listing).
    """
    MINT = "MT"
    NEAR_MINT = "NM"
    EXCELLENT = "EXC"
    GOOD = "GD"
    LIGHT_PLAYED = "LP"
    PLAYED = "PL"
    POOR = "PO"


class TCGPlayerGrade(str, Enum):
    """TCGPlayer condition grades."""
    NEAR_MINT = "NM"
    LIGHTLY_PLAYED = "LP"
    MODERATELY_PLAYED = "MP"
    HEAVILY_PLAYED = "HP"
    DAMAGED = "DMG"


class ConditionMapping(NamedTuple):
    """Result of mapping a Cardmarket grade to TCGPlayer equivalent."""
    tcgplayer_grade: TCGPlayerGrade
    price_multiplier: Decimal  # Applied to P_target (e.g., 0.85 = -15% penalty)


# ---------------------------------------------------------------------------
# Mapping table — Section 4.6
# ---------------------------------------------------------------------------

_CONDITION_MAP: dict[CardmarketGrade, ConditionMapping] = {
    CardmarketGrade.MINT: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.NEAR_MINT,
        price_multiplier=Decimal("1.00"),
    ),
    CardmarketGrade.NEAR_MINT: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.NEAR_MINT,
        price_multiplier=Decimal("1.00"),
    ),
    CardmarketGrade.EXCELLENT: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.LIGHTLY_PLAYED,
        price_multiplier=Decimal("0.85"),  # -15% penalty
    ),
    CardmarketGrade.GOOD: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.MODERATELY_PLAYED,
        price_multiplier=Decimal("0.75"),  # -25% penalty
    ),
    CardmarketGrade.LIGHT_PLAYED: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.MODERATELY_PLAYED,
        price_multiplier=Decimal("0.75"),  # -25% penalty
    ),
    CardmarketGrade.PLAYED: ConditionMapping(
        tcgplayer_grade=TCGPlayerGrade.HEAVILY_PLAYED,
        price_multiplier=Decimal("0.60"),  # -40% penalty
    ),
    # POOR is intentionally omitted — signals must never be generated
}


def map_condition(cardmarket_grade: CardmarketGrade) -> ConditionMapping:
    """
    Map a Cardmarket condition grade to its TCGPlayer equivalent with
    price penalty.

    Args:
        cardmarket_grade: The Cardmarket condition enum value.

    Returns:
        ConditionMapping with the TCGPlayer grade and price multiplier.

    Raises:
        ValueError: If the grade is POOR/Damaged. No signal should ever
                    be generated for cards in Poor condition.
    """
    if cardmarket_grade == CardmarketGrade.POOR:
        logger.warning(
            "condition_mapping_suppressed",
            cardmarket_grade=cardmarket_grade.value,
            reason="Poor/Damaged cards must not generate signals",
        )
        raise ValueError(
            f"Cannot map condition '{cardmarket_grade.value}' (Poor/Damaged). "
            f"Signal generation must be suppressed for this condition."
        )

    mapping = _CONDITION_MAP[cardmarket_grade]
    logger.debug(
        "condition_mapped",
        cardmarket_grade=cardmarket_grade.value,
        tcgplayer_grade=mapping.tcgplayer_grade.value,
        price_multiplier=str(mapping.price_multiplier),
    )
    return mapping
