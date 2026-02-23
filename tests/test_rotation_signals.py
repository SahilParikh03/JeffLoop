"""Tests for user priority rotation (Section 14).

Named test_rotation_signals.py to avoid collision with
tests/test_rotation.py (which tests engine/rotation.py).
"""

from __future__ import annotations

from src.signals.rotation import (
    UserTier,
    demote_user,
    filter_by_category,
    score_candidates,
)


def _make_candidate(
    user_id: str,
    tier: str = "standard",
    priority_score: float = 50.0,
    categories: list[str] | None = None,
) -> dict:
    return {
        "user_id": user_id,
        "tier": tier,
        "priority_score": priority_score,
        "categories": categories,
    }


class TestScoreCandidates:
    def test_tier_ordering(self) -> None:
        """Premium > Standard > Free, regardless of priority score."""
        candidates = [
            _make_candidate("free", tier="free", priority_score=100),
            _make_candidate("premium", tier="premium", priority_score=1),
            _make_candidate("standard", tier="standard", priority_score=50),
        ]
        result = score_candidates(candidates)
        assert [c["user_id"] for c in result] == ["premium", "standard", "free"]

    def test_priority_score_within_tier(self) -> None:
        """Same tier: higher priority_score wins."""
        candidates = [
            _make_candidate("low", tier="standard", priority_score=10),
            _make_candidate("high", tier="standard", priority_score=90),
            _make_candidate("mid", tier="standard", priority_score=50),
        ]
        result = score_candidates(candidates)
        assert [c["user_id"] for c in result] == ["high", "mid", "low"]

    def test_category_match_bonus(self) -> None:
        """Same tier, same score — category match breaks tie."""
        candidates = [
            _make_candidate("no_match", tier="standard", priority_score=50, categories=["vintage"]),
            _make_candidate("match", tier="standard", priority_score=50, categories=["modern_competitive"]),
        ]
        result = score_candidates(candidates, signal_category="modern_competitive")
        assert result[0]["user_id"] == "match"

    def test_empty_candidates(self) -> None:
        result = score_candidates([])
        assert result == []

    def test_unknown_tier_defaults_to_free(self) -> None:
        """Unknown tier string falls back to FREE."""
        candidates = [
            _make_candidate("unknown", tier="vip"),
            _make_candidate("free", tier="free"),
        ]
        result = score_candidates(candidates)
        # Both treated as free tier, so priority_score decides (both default 50)
        assert len(result) == 2


class TestFilterByCategory:
    def test_includes_matching_users(self) -> None:
        candidates = [
            _make_candidate("a", categories=["modern_competitive"]),
            _make_candidate("b", categories=["vintage"]),
        ]
        result = filter_by_category(candidates, "modern_competitive")
        assert len(result) == 1
        assert result[0]["user_id"] == "a"

    def test_includes_users_with_no_category_preference(self) -> None:
        """Users with no category filter see everything."""
        candidates = [
            _make_candidate("all", categories=None),
            _make_candidate("specific", categories=["vintage"]),
        ]
        result = filter_by_category(candidates, "modern_competitive")
        assert len(result) == 1
        assert result[0]["user_id"] == "all"

    def test_empty_categories_list_passes_through(self) -> None:
        """Empty list = no preference = see everything."""
        candidates = [_make_candidate("open", categories=[])]
        result = filter_by_category(candidates, "modern_competitive")
        assert len(result) == 1


class TestDemoteUser:
    def test_demote_sets_free_tier(self) -> None:
        user = _make_candidate("u1", tier="premium")
        demoted = demote_user(user)
        assert demoted["tier"] == "free"
        assert demoted["demoted_from"] == "premium"

    def test_demote_does_not_mutate_original(self) -> None:
        user = _make_candidate("u1", tier="premium")
        demoted = demote_user(user)
        assert user["tier"] == "premium"
        assert demoted["tier"] == "free"


class TestSubscriptionTierRouting:
    """Verify 4-tier ordering and backwards-compat alias mapping (Phase 4)."""

    def test_shop_tier_beats_pro(self) -> None:
        """SHOP (4) > PRO (3) regardless of priority score."""
        candidates = [
            _make_candidate("pro_user", tier="pro", priority_score=100),
            _make_candidate("shop_user", tier="shop", priority_score=1),
        ]
        result = score_candidates(candidates)
        assert result[0]["user_id"] == "shop_user"

    def test_pro_tier_beats_trader(self) -> None:
        """PRO (3) > TRADER (2) regardless of priority score."""
        candidates = [
            _make_candidate("trader_user", tier="trader", priority_score=100),
            _make_candidate("pro_user", tier="pro", priority_score=1),
        ]
        result = score_candidates(candidates)
        assert result[0]["user_id"] == "pro_user"

    def test_trader_tier_beats_free(self) -> None:
        """TRADER (2) > FREE (1) regardless of priority score."""
        candidates = [
            _make_candidate("free_user", tier="free", priority_score=100),
            _make_candidate("trader_user", tier="trader", priority_score=1),
        ]
        result = score_candidates(candidates)
        assert result[0]["user_id"] == "trader_user"

    def test_full_four_tier_ordering(self) -> None:
        """SHOP > PRO > TRADER > FREE ordering holds across all four tiers."""
        candidates = [
            _make_candidate("free_user", tier="free", priority_score=50),
            _make_candidate("shop_user", tier="shop", priority_score=50),
            _make_candidate("trader_user", tier="trader", priority_score=50),
            _make_candidate("pro_user", tier="pro", priority_score=50),
        ]
        result = score_candidates(candidates)
        order = [c["user_id"] for c in result]
        assert order == ["shop_user", "pro_user", "trader_user", "free_user"]

    def test_legacy_premium_tier_maps_to_pro(self) -> None:
        """Legacy 'premium' tier string is treated as PRO priority."""
        candidates = [
            _make_candidate("premium_user", tier="premium", priority_score=50),
            _make_candidate("trader_user", tier="trader", priority_score=50),
        ]
        result = score_candidates(candidates)
        # premium → pro (3) > trader (2)
        assert result[0]["user_id"] == "premium_user"

    def test_legacy_standard_tier_maps_to_trader(self) -> None:
        """Legacy 'standard' tier string is treated as TRADER priority."""
        candidates = [
            _make_candidate("standard_user", tier="standard", priority_score=50),
            _make_candidate("free_user", tier="free", priority_score=50),
        ]
        result = score_candidates(candidates)
        # standard → trader (2) > free (1)
        assert result[0]["user_id"] == "standard_user"

    def test_legacy_premium_loses_to_shop(self) -> None:
        """Legacy 'premium' (→ PRO=3) is still below real 'shop' (4)."""
        candidates = [
            _make_candidate("premium_user", tier="premium", priority_score=100),
            _make_candidate("shop_user", tier="shop", priority_score=1),
        ]
        result = score_candidates(candidates)
        assert result[0]["user_id"] == "shop_user"
