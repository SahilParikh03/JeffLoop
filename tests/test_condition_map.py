"""
TCG Radar — Condition Mapping Tests (Section 4.6)

Tests the Cardmarket → TCGPlayer condition mapping with pessimistic penalties.
Every mapping is validated against the spec table in Section 4.6.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.utils.condition_map import (
    CardmarketGrade,
    TCGPlayerGrade,
    ConditionMapping,
    map_condition,
)


class TestConditionMappingMint:
    """Section 4.6 — Mint cards map to Near Mint with no penalty."""

    def test_mint_to_near_mint(self) -> None:
        """Mint (MT) maps directly to Near Mint with 1.0 multiplier (Section 4.6)."""
        result = map_condition(CardmarketGrade.MINT)

        assert result.tcgplayer_grade == TCGPlayerGrade.NEAR_MINT
        assert result.price_multiplier == Decimal("1.00")

    def test_mint_multiplier_no_penalty(self) -> None:
        """Mint condition incurs no price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.MINT)

        # Validate exact Decimal comparison (no rounding)
        assert result.price_multiplier == Decimal("1.00")
        assert result.price_multiplier * Decimal("100.00") == Decimal("100.00")


class TestConditionMappingNearMint:
    """Section 4.6 — Near Mint cards map to Near Mint with no penalty."""

    def test_near_mint_to_near_mint(self) -> None:
        """Near Mint (NM) maps directly to Near Mint with 1.0 multiplier (Section 4.6)."""
        result = map_condition(CardmarketGrade.NEAR_MINT)

        assert result.tcgplayer_grade == TCGPlayerGrade.NEAR_MINT
        assert result.price_multiplier == Decimal("1.00")

    def test_near_mint_multiplier_no_penalty(self) -> None:
        """Near Mint condition incurs no price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.NEAR_MINT)

        assert result.price_multiplier == Decimal("1.00")
        # Test with realistic price
        test_price = Decimal("50.00")
        adjusted = test_price * result.price_multiplier
        assert adjusted == Decimal("50.00")


class TestConditionMappingExcellent:
    """Section 4.6 — Excellent (EXC) maps pessimistically to Lightly Played with -15% penalty."""

    def test_excellent_to_lightly_played(self) -> None:
        """Excellent (EXC) maps to Lightly Played per Section 4.6."""
        result = map_condition(CardmarketGrade.EXCELLENT)

        assert result.tcgplayer_grade == TCGPlayerGrade.LIGHTLY_PLAYED
        assert result.price_multiplier == Decimal("0.85")

    def test_excellent_penalty_15_percent(self) -> None:
        """Excellent condition applies -15% price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.EXCELLENT)

        # Verify the penalty is exactly -15%
        assert result.price_multiplier == Decimal("0.85")
        # Test: $100 card becomes $85 after penalty
        test_price = Decimal("100.00")
        adjusted = test_price * result.price_multiplier
        assert adjusted == Decimal("85.00")

    def test_excellent_realistic_prices(self) -> None:
        """Excellent condition penalty applies honestly across price ranges (Section 4.6)."""
        result = map_condition(CardmarketGrade.EXCELLENT)

        # Test $25 card
        assert Decimal("25.00") * result.price_multiplier == Decimal("21.25")
        # Test $10 card
        assert Decimal("10.00") * result.price_multiplier == Decimal("8.50")
        # Test $500 card
        assert Decimal("500.00") * result.price_multiplier == Decimal("425.00")


class TestConditionMappingGood:
    """Section 4.6 — Good (GD) maps to Moderately Played with -25% penalty."""

    def test_good_to_moderately_played(self) -> None:
        """Good (GD) maps to Moderately Played per Section 4.6."""
        result = map_condition(CardmarketGrade.GOOD)

        assert result.tcgplayer_grade == TCGPlayerGrade.MODERATELY_PLAYED
        assert result.price_multiplier == Decimal("0.75")

    def test_good_penalty_25_percent(self) -> None:
        """Good condition applies -25% price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.GOOD)

        # Verify the penalty is exactly -25%
        assert result.price_multiplier == Decimal("0.75")
        # Test: $100 card becomes $75 after penalty
        test_price = Decimal("100.00")
        adjusted = test_price * result.price_multiplier
        assert adjusted == Decimal("75.00")

    def test_good_decimal_precision(self) -> None:
        """Good condition multiplier maintains Decimal precision (Section 4.6)."""
        result = map_condition(CardmarketGrade.GOOD)

        # Test sub-dollar amounts to ensure no float rounding
        test_price = Decimal("1.33")
        adjusted = test_price * result.price_multiplier
        # Verify: 1.33 × 0.75 = 0.9975 (not rounded)
        assert adjusted == Decimal("0.9975")


class TestConditionMappingLightPlayed:
    """Section 4.6 — Light Played (LP) maps to Moderately Played with -25% penalty."""

    def test_light_played_to_moderately_played(self) -> None:
        """Light Played (LP) maps to Moderately Played per Section 4.6."""
        result = map_condition(CardmarketGrade.LIGHT_PLAYED)

        assert result.tcgplayer_grade == TCGPlayerGrade.MODERATELY_PLAYED
        assert result.price_multiplier == Decimal("0.75")

    def test_light_played_penalty_25_percent(self) -> None:
        """Light Played condition applies -25% price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.LIGHT_PLAYED)

        # Same as Good condition
        assert result.price_multiplier == Decimal("0.75")
        test_price = Decimal("100.00")
        adjusted = test_price * result.price_multiplier
        assert adjusted == Decimal("75.00")

    def test_light_played_equals_good_penalty(self) -> None:
        """Light Played and Good have identical penalties (Section 4.6)."""
        lp_result = map_condition(CardmarketGrade.LIGHT_PLAYED)
        good_result = map_condition(CardmarketGrade.GOOD)

        # Both should map to MP with -25% penalty
        assert lp_result.tcgplayer_grade == good_result.tcgplayer_grade
        assert lp_result.price_multiplier == good_result.price_multiplier


class TestConditionMappingPlayed:
    """Section 4.6 — Played (PL) maps to Heavily Played with -40% penalty."""

    def test_played_to_heavily_played(self) -> None:
        """Played (PL) maps to Heavily Played per Section 4.6."""
        result = map_condition(CardmarketGrade.PLAYED)

        assert result.tcgplayer_grade == TCGPlayerGrade.HEAVILY_PLAYED
        assert result.price_multiplier == Decimal("0.60")

    def test_played_penalty_40_percent(self) -> None:
        """Played condition applies -40% price penalty (Section 4.6)."""
        result = map_condition(CardmarketGrade.PLAYED)

        # Verify the penalty is exactly -40%
        assert result.price_multiplier == Decimal("0.60")
        # Test: $100 card becomes $60 after penalty
        test_price = Decimal("100.00")
        adjusted = test_price * result.price_multiplier
        assert adjusted == Decimal("60.00")

    def test_played_realistic_prices(self) -> None:
        """Played condition penalty applies honestly across price ranges (Section 4.6)."""
        result = map_condition(CardmarketGrade.PLAYED)

        # Test bulk card prices (where Played condition is more common)
        assert Decimal("15.00") * result.price_multiplier == Decimal("9.00")
        assert Decimal("10.00") * result.price_multiplier == Decimal("6.00")
        assert Decimal("1.00") * result.price_multiplier == Decimal("0.60")


class TestConditionMappingPoor:
    """Section 4.6 — Poor (PO) condition must raise ValueError (no signal generation)."""

    def test_poor_raises_value_error(self) -> None:
        """Poor (PO) condition always raises ValueError per Section 4.6.

        No signal should ever be generated for cards in Poor condition.
        """
        with pytest.raises(ValueError) as exc_info:
            map_condition(CardmarketGrade.POOR)

        assert "Cannot map condition" in str(exc_info.value)
        assert "Poor/Damaged" in str(exc_info.value)

    def test_poor_error_message_clarity(self) -> None:
        """Poor condition error message explains why (Section 4.6)."""
        with pytest.raises(ValueError) as exc_info:
            map_condition(CardmarketGrade.POOR)

        error_msg = str(exc_info.value)
        assert "Signal generation must be suppressed" in error_msg


class TestConditionMappingComparison:
    """Cross-compare all conditions to validate internal consistency (Section 4.6)."""

    def test_all_grades_except_poor_are_mappable(self) -> None:
        """All Cardmarket grades except Poor should map successfully (Section 4.6)."""
        mappable_grades = [
            CardmarketGrade.MINT,
            CardmarketGrade.NEAR_MINT,
            CardmarketGrade.EXCELLENT,
            CardmarketGrade.GOOD,
            CardmarketGrade.LIGHT_PLAYED,
            CardmarketGrade.PLAYED,
        ]

        for grade in mappable_grades:
            result = map_condition(grade)
            assert isinstance(result, ConditionMapping)
            assert isinstance(result.tcgplayer_grade, TCGPlayerGrade)
            assert isinstance(result.price_multiplier, Decimal)

    def test_penalty_ordering_correct(self) -> None:
        """Penalties increase in severity from Mint to Played (Section 4.6)."""
        mint = map_condition(CardmarketGrade.MINT)
        nm = map_condition(CardmarketGrade.NEAR_MINT)
        exc = map_condition(CardmarketGrade.EXCELLENT)
        good = map_condition(CardmarketGrade.GOOD)
        lp = map_condition(CardmarketGrade.LIGHT_PLAYED)
        played = map_condition(CardmarketGrade.PLAYED)

        # Penalties should be monotonically decreasing
        assert mint.price_multiplier >= nm.price_multiplier
        assert nm.price_multiplier >= exc.price_multiplier
        assert exc.price_multiplier >= good.price_multiplier
        assert good.price_multiplier >= lp.price_multiplier
        assert lp.price_multiplier >= played.price_multiplier

    def test_exact_penalty_values(self) -> None:
        """Validate the exact penalty values from the spec (Section 4.6)."""
        penalties = {
            CardmarketGrade.MINT: Decimal("1.00"),
            CardmarketGrade.NEAR_MINT: Decimal("1.00"),
            CardmarketGrade.EXCELLENT: Decimal("0.85"),
            CardmarketGrade.GOOD: Decimal("0.75"),
            CardmarketGrade.LIGHT_PLAYED: Decimal("0.75"),
            CardmarketGrade.PLAYED: Decimal("0.60"),
        }

        for grade, expected_multiplier in penalties.items():
            result = map_condition(grade)
            assert result.price_multiplier == expected_multiplier, \
                f"Grade {grade} has multiplier {result.price_multiplier}, expected {expected_multiplier}"


class TestConditionMappingReturnType:
    """Validate the return type structure (Section 4.6)."""

    def test_returns_condition_mapping_namedtuple(self) -> None:
        """map_condition() returns a ConditionMapping NamedTuple (Section 4.6)."""
        result = map_condition(CardmarketGrade.EXCELLENT)

        assert isinstance(result, ConditionMapping)
        assert hasattr(result, "tcgplayer_grade")
        assert hasattr(result, "price_multiplier")

    def test_result_fields_are_correct_types(self) -> None:
        """ConditionMapping fields have correct types (Section 4.6)."""
        result = map_condition(CardmarketGrade.PLAYED)

        assert isinstance(result.tcgplayer_grade, TCGPlayerGrade)
        assert isinstance(result.price_multiplier, Decimal)

    def test_decimal_precision_maintained(self) -> None:
        """Price multipliers maintain Decimal precision, never use float (Section 4.6)."""
        result = map_condition(CardmarketGrade.EXCELLENT)

        # Verify it's Decimal, not float
        assert isinstance(result.price_multiplier, Decimal)
        # Multiply with another Decimal to ensure no float conversion
        test_calc = result.price_multiplier * Decimal("100.00")
        assert isinstance(test_calc, Decimal)
