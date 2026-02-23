"""
TCG Radar - Variant ID Validation (Section 4.7)

FIRST filter in Layer 2. Before any other calculation, ensure both sides of a
spread point to the exact same pokemontcg.io canonical ID:
    "{set_code}-{card_number}" (example: "sv1-25")

Known mismatch categories:
- Promo stamps (GameStop, Pokemon Center, Build & Battle)
- Regional exclusive prints
- Reverse holo vs standard holo
- First edition vs unlimited
- Japanese vs English prints with the same artwork
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

MATCH = "MATCH"
VARIANT_MISMATCH = "VARIANT_MISMATCH"


def validate_variant(tcgplayer_id: str, cardmarket_id: str) -> str:
    """
    Validate cross-platform card identity by strict canonical ID equality.

    Args:
        tcgplayer_id: Canonical ID from TCGPlayer side (via pokemontcg.io mapping).
        cardmarket_id: Canonical ID from Cardmarket side (via pokemontcg.io mapping).

    Returns:
        "MATCH" when IDs are identical and non-empty, else "VARIANT_MISMATCH".
    """
    if not tcgplayer_id or not cardmarket_id:
        logger.warning(
            "variant_mismatch_detected",
            tcgplayer_id=tcgplayer_id,
            cardmarket_id=cardmarket_id,
            reason="missing_or_empty_id",
        )
        return VARIANT_MISMATCH

    if tcgplayer_id != cardmarket_id:
        logger.warning(
            "variant_mismatch_detected",
            tcgplayer_id=tcgplayer_id,
            cardmarket_id=cardmarket_id,
            reason="id_mismatch",
        )
        return VARIANT_MISMATCH

    return MATCH

