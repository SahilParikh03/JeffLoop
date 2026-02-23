"""
TCG Radar — Signal Cascade Logic (Section 14)

When a user doesn't act on a signal before it expires, the signal
cascades to the next user in priority order — but with a mandatory
10-second cooldown buffer to prevent two users from seeing the same
signal due to Telegram delivery latency.

Rules:
- 10-second cooldown after expiry before cascade is available
- Maximum 5 cascades, then demote to free tier (caller handles demotion)
- Cascade only if not acted_on
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from src.config import settings

logger = structlog.get_logger(__name__)


def compute_cascade_available_at(
    expires_at: datetime,
    cooldown_seconds: int | None = None,
) -> datetime:
    """
    Compute when a signal becomes available for cascade.

    available_at = expires_at + cooldown (10 seconds by default)

    Args:
        expires_at: Signal expiry timestamp (timezone-aware).
        cooldown_seconds: Override cooldown (default: CASCADE_COOLDOWN_SECONDS).

    Returns:
        Timezone-aware datetime when cascade is permitted.
    """
    cooldown = cooldown_seconds if cooldown_seconds is not None else settings.CASCADE_COOLDOWN_SECONDS
    available = expires_at + timedelta(seconds=cooldown)

    logger.debug(
        "cascade_available_at_computed",
        expires_at=expires_at.isoformat(),
        cooldown_seconds=cooldown,
        available_at=available.isoformat(),
        source="cascade",
    )
    return available


def should_cascade(
    expires_at: datetime,
    acted_on: bool,
    cascade_count: int,
    reference_time: datetime | None = None,
    cooldown_seconds: int | None = None,
    max_cascades: int | None = None,
) -> tuple[bool, str]:
    """
    Determine whether a signal should cascade to the next user.

    Cascade requires ALL of:
    1. Signal was NOT acted on
    2. Cascade count < max limit (5)
    3. Current time >= expires_at + cooldown (10 seconds)

    Args:
        expires_at: Signal expiry timestamp.
        acted_on: Whether the user acted on the signal.
        cascade_count: Current cascade count for this signal.
        reference_time: Current time (default: now UTC). Allows deterministic testing.
        cooldown_seconds: Override cooldown seconds.
        max_cascades: Override max cascade limit.

    Returns:
        Tuple of (should_cascade: bool, reason: str).
    """
    now = reference_time if reference_time is not None else datetime.now(timezone.utc)
    max_limit = max_cascades if max_cascades is not None else settings.CASCADE_MAX_LIMIT

    # Check: was it acted on?
    if acted_on:
        reason = "signal_acted_on"
        logger.debug("cascade_check", result=False, reason=reason, source="cascade")
        return False, reason

    # Check: cascade limit reached?
    if cascade_count >= max_limit:
        reason = f"cascade_limit_reached ({cascade_count}/{max_limit})"
        logger.debug("cascade_check", result=False, reason=reason, source="cascade")
        return False, reason

    # Check: cooldown elapsed?
    available_at = compute_cascade_available_at(expires_at, cooldown_seconds)
    if now < available_at:
        seconds_remaining = (available_at - now).total_seconds()
        reason = f"cooldown_pending ({seconds_remaining:.1f}s remaining)"
        logger.debug("cascade_check", result=False, reason=reason, source="cascade")
        return False, reason

    reason = "cascade_ready"
    logger.debug(
        "cascade_check",
        result=True,
        reason=reason,
        cascade_count=cascade_count,
        source="cascade",
    )
    return True, reason


def increment_cascade_count(
    current_count: int,
    max_cascades: int | None = None,
) -> tuple[int, bool]:
    """
    Increment cascade count and check if limit reached.

    Args:
        current_count: Current cascade count.
        max_cascades: Override max limit (default: CASCADE_MAX_LIMIT).

    Returns:
        Tuple of (new_count, limit_reached).
        When limit_reached=True, caller should demote signal to free tier.
    """
    max_limit = max_cascades if max_cascades is not None else settings.CASCADE_MAX_LIMIT
    new_count = current_count + 1
    limit_reached = new_count >= max_limit

    logger.debug(
        "cascade_incremented",
        old_count=current_count,
        new_count=new_count,
        max_limit=max_limit,
        limit_reached=limit_reached,
        source="cascade",
    )
    return new_count, limit_reached
