"""
TCG Radar - Maturity Decay (Section 4.2.2)

New sets and anniversary products have artificially inflated velocity during
their hype window. This decays predictably based on set age.

Maturity Decay multiplier to apply to V_s (Velocity Score):
- Set age < 30 days: 1.0 (no penalty - flag as HYPE WINDOW)
- Set age 30-60 days: 0.9 (minor decay)
- Set age 60-90 days: 0.8 (hype fading)
- Set age > 90 days: 0.7 (normalized market)

If reprint is rumored AND set_age > 60 days: apply additional -20% (multiply by 0.8)
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def calculate_maturity_decay(
    set_release_date: date,
    reference_date: date | None = None,
) -> Decimal:
    """
    Calculate maturity decay multiplier based on set age.

    Hype decays predictably:
    - Fresh sets (< 30 days): Full velocity (1.0), but flag as HIGH VOLATILITY
    - Young sets (30-60 days): Minor decay (0.9)
    - Maturing sets (60-90 days): Hype fading (0.8)
    - Normalized (> 90 days): Market equilibrium (0.7)

    Reprint rumors add additional -20% penalty on sets > 60 days old.

    Args:
        set_release_date: Release date of the card set.
        reference_date: Date to calculate age against (default: today).
                       Allows testing with fixed dates.

    Returns:
        Decimal multiplier (1.0, 0.9, 0.8, 0.7) to apply to velocity score.
    """
    if reference_date is None:
        reference_date = date.today()

    # Calculate set age in days
    age_delta = reference_date - set_release_date
    set_age_days = age_delta.days

    # Future release dates get no penalty
    if set_age_days < 0:
        logger.debug(
            "maturity_decay_future_set",
            set_release_date=set_release_date.isoformat(),
            reference_date=reference_date.isoformat(),
            set_age_days=set_age_days,
            result="1.0",
        )
        return Decimal("1.0")

    # Determine decay band
    if set_age_days < 30:
        decay_multiplier = settings.MATURITY_DECAY_30D  # 1.0
        decay_band = "FRESH (<30d)"
    elif set_age_days < 60:
        decay_multiplier = settings.MATURITY_DECAY_60D  # 0.9
        decay_band = "YOUNG (30-60d)"
    elif set_age_days < 90:
        decay_multiplier = settings.MATURITY_DECAY_90D  # 0.8
        decay_band = "MATURING (60-90d)"
    else:
        decay_multiplier = settings.MATURITY_DECAY_OLD  # 0.7
        decay_band = "NORMALIZED (>90d)"

    logger.debug(
        "maturity_decay_calculated",
        set_release_date=set_release_date.isoformat(),
        reference_date=reference_date.isoformat(),
        set_age_days=set_age_days,
        decay_band=decay_band,
        decay_multiplier=str(decay_multiplier),
    )

    return decay_multiplier


def apply_maturity_penalty_with_reprint_rumor(
    base_decay: Decimal,
    set_release_date: date,
    reprint_rumored: bool = False,
    reference_date: date | None = None,
) -> Decimal:
    """
    Apply maturity decay multiplier with optional reprint rumor penalty.

    If reprint_rumored=True AND set_age > 60 days:
        Final multiplier = base_decay * MATURITY_REPRINT_RUMOR_PENALTY (0.8)

    This models the market's anticipatory markdown before a reprint is officially
    announced. Collectors liquidate holdings in advance.

    Args:
        base_decay: Result from calculate_maturity_decay().
        set_release_date: Release date of the card set.
        reprint_rumored: Whether credible reprint rumors exist.
        reference_date: Reference date for age calculation.

    Returns:
        Decimal multiplier with reprint penalty applied if applicable.
    """
    if reference_date is None:
        reference_date = date.today()

    set_age_days = (reference_date - set_release_date).days

    if reprint_rumored and set_age_days > 60:
        penalized_multiplier = base_decay * settings.MATURITY_REPRINT_RUMOR_PENALTY
        logger.debug(
            "maturity_reprint_penalty_applied",
            base_decay=str(base_decay),
            reprint_rumor_penalty=str(settings.MATURITY_REPRINT_RUMOR_PENALTY),
            final_multiplier=str(penalized_multiplier),
            set_age_days=set_age_days,
        )
        return penalized_multiplier

    return base_decay
