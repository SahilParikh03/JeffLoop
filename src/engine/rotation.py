"""
TCG Radar - Rotation Risk Checker (Section 7)

Pokémon TCG rotations happen ~once per year when the regulation mark changes.
Cards exit "Standard" format when their set rotates out.

Regulation mark order: D → E → F → G → H → I
Current mark: H (Section 7)
"G" rotates April 10, 2026 (Section 7)

Risk levels based on time until rotation:
- SAFE: >6 months until rotation (or no announced rotation)
- WATCH: 3-6 months until rotation
- DANGER: <3 months until rotation
- ROTATED: Already rotated or banned
- UNKNOWN: No regulation mark data

This filter prevents selling cards into a liquidation cascade.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)

# Regulation mark progression order (D is oldest, I is newest/future)
REGULATION_MARK_ORDER = ["D", "E", "F", "G", "H", "I"]


def check_rotation_risk(
    regulation_mark: str | None,
    legality_standard: str | None = None,
    reference_date: date | None = None,
) -> dict[str, Any]:
    """
    Check rotation risk for a card based on regulation mark and legality.

    Returns dict with:
    - at_risk: bool — True if signal should be suppressed/flagged
    - risk_level: str — One of SAFE, WATCH, DANGER, ROTATED, UNKNOWN
    - months_until_rotation: int | None — Estimated months to rotation
    - rotation_date: date | None — Expected rotation date if available

    Logic:
    1. If legality_standard == "Banned" → ROTATED, at_risk=True
    2. If regulation_mark is None → UNKNOWN, at_risk=False
    3. Else: Look up rotation date from ROTATION_CALENDAR
       - No rotation date (current legal mark like "H") → SAFE
       - Past rotation → ROTATED
       - Days until rotation: >180d → SAFE, 90-180d → WATCH, <90d → DANGER

    Args:
        regulation_mark: Card's regulation mark (e.g., "G", "H").
        legality_standard: Card's legality (e.g., "Standard", "Banned").
        reference_date: Date to calculate rotation distance (default: today).

    Returns:
        Dict with rotation risk assessment.
    """
    if reference_date is None:
        reference_date = date.today()

    # 1. Check if already banned
    if legality_standard == "Banned":
        logger.debug(
            "rotation_risk_banned",
            legality_standard=legality_standard,
        )
        return {
            "at_risk": True,
            "risk_level": "ROTATED",
            "months_until_rotation": None,
            "rotation_date": None,
        }

    # 2. Check if regulation mark is None
    if regulation_mark is None:
        logger.debug(
            "rotation_risk_unknown_mark",
            regulation_mark=regulation_mark,
        )
        return {
            "at_risk": False,
            "risk_level": "UNKNOWN",
            "months_until_rotation": None,
            "rotation_date": None,
        }

    # 3. Look up rotation info from calendar
    rotation_info = settings.ROTATION_CALENDAR.get(regulation_mark)

    if rotation_info is None:
        # Mark not in calendar — likely already rotated
        logger.warning(
            "rotation_risk_unknown_mark_in_calendar",
            regulation_mark=regulation_mark,
        )
        return {
            "at_risk": True,
            "risk_level": "ROTATED",
            "months_until_rotation": None,
            "rotation_date": None,
        }

    # Get rotation date (may be None for current legal marks like "H")
    rotation_date_raw = rotation_info.get("rotation_date")

    if rotation_date_raw is None:
        # Current legal mark with no announced rotation
        logger.debug(
            "rotation_risk_no_announced_rotation",
            regulation_mark=regulation_mark,
            status=rotation_info.get("status"),
        )
        return {
            "at_risk": False,
            "risk_level": "SAFE",
            "months_until_rotation": None,
            "rotation_date": None,
        }

    # Parse rotation_date if it's a string
    if isinstance(rotation_date_raw, str):
        rotation_date = datetime.strptime(rotation_date_raw, "%Y-%m-%d").date()
    else:
        rotation_date = rotation_date_raw

    # Calculate days until rotation
    days_until_rotation = (rotation_date - reference_date).days

    if days_until_rotation < 0:
        # Rotation date has passed
        logger.debug(
            "rotation_risk_already_rotated",
            regulation_mark=regulation_mark,
            rotation_date=rotation_date.isoformat(),
            reference_date=reference_date.isoformat(),
        )
        return {
            "at_risk": True,
            "risk_level": "ROTATED",
            "months_until_rotation": 0,
            "rotation_date": rotation_date,
        }

    # Estimate months (rough conversion: 1 month = 30 days)
    months_until = max(0, days_until_rotation // 30)

    # Classify risk level by time to rotation
    if days_until_rotation > 180:  # >6 months
        risk_level = "SAFE"
        at_risk = False
        reason = "rotation >6 months away"
    elif days_until_rotation > 90:  # 3-6 months
        risk_level = "WATCH"
        at_risk = True
        reason = "rotation 3-6 months away"
    else:  # <3 months
        risk_level = "DANGER"
        at_risk = True
        reason = "rotation <3 months away"

    logger.debug(
        "rotation_risk_assessed",
        regulation_mark=regulation_mark,
        rotation_date=rotation_date.isoformat(),
        reference_date=reference_date.isoformat(),
        days_until_rotation=days_until_rotation,
        months_until_rotation=months_until,
        risk_level=risk_level,
        at_risk=at_risk,
        reason=reason,
    )

    return {
        "at_risk": at_risk,
        "risk_level": risk_level,
        "months_until_rotation": months_until,
        "rotation_date": rotation_date,
    }


def get_mark_distance_from_current(regulation_mark: str | None) -> int:
    """
    Calculate how many marks behind the current mark this card is.

    Current mark = "H" (index 4 in REGULATION_MARK_ORDER).

    Returns:
    - 0: Current or future mark ("H", "I")
    - 1: One mark behind ("G")
    - 2+: Two or more marks behind ("F", "E", "D")
    - None: Unknown or invalid mark

    Args:
        regulation_mark: The card's regulation mark.

    Returns:
        Distance from current mark (0 = current, 1 = one behind, etc.)
        or None if mark is unknown.
    """
    if regulation_mark is None or regulation_mark not in REGULATION_MARK_ORDER:
        return None

    current_mark_idx = REGULATION_MARK_ORDER.index("H")  # "H" is current
    mark_idx = REGULATION_MARK_ORDER.index(regulation_mark)

    distance = current_mark_idx - mark_idx

    return max(0, distance)  # Never negative (future marks or current)
