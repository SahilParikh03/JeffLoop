"""Tests for platform fee calculator (Section 4.1.1)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.config import settings
from src.engine.fees import Platform, calculate_platform_fees

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


class TestTCGPlayerFees:
    """TCGPlayer: min(P × 0.1075, $75) + $0.30"""

    def test_low_price_below_cap(self) -> None:
        fee = calculate_platform_fees(Decimal("100.00"), Platform.TCGPLAYER)
        expected = _q(Decimal("100.00") * settings.TCGPLAYER_FEE_RATE + settings.TCGPLAYER_FIXED_FEE)
        assert fee == expected

    def test_exact_cap_boundary(self) -> None:
        """At ~$697.67, variable fee = $75.00 exactly."""
        boundary = _q(settings.TCGPLAYER_FEE_CAP / settings.TCGPLAYER_FEE_RATE)
        fee = calculate_platform_fees(boundary, Platform.TCGPLAYER)
        expected = _q(settings.TCGPLAYER_FEE_CAP + settings.TCGPLAYER_FIXED_FEE)
        assert fee == expected

    def test_above_cap_capped_at_75(self) -> None:
        """Above $698, variable fee stays at $75."""
        fee = calculate_platform_fees(Decimal("1000.00"), Platform.TCGPLAYER)
        expected = _q(settings.TCGPLAYER_FEE_CAP + settings.TCGPLAYER_FIXED_FEE)
        assert fee == expected

    def test_zero_price(self) -> None:
        fee = calculate_platform_fees(Decimal("0.00"), Platform.TCGPLAYER)
        assert fee == _q(settings.TCGPLAYER_FIXED_FEE)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            calculate_platform_fees(Decimal("-1.00"), Platform.TCGPLAYER)


class TestEbayFees:
    """eBay: P × 0.1325"""

    def test_standard_price(self) -> None:
        fee = calculate_platform_fees(Decimal("50.00"), Platform.EBAY)
        expected = _q(Decimal("50.00") * settings.EBAY_FEE_RATE)
        assert fee == expected


class TestCardmarketFees:
    """Cardmarket: P × 0.05"""

    def test_standard_price(self) -> None:
        fee = calculate_platform_fees(Decimal("80.00"), Platform.CARDMARKET)
        expected = _q(Decimal("80.00") * settings.CARDMARKET_PRO_FEE_RATE)
        assert fee == expected


class TestEdgeCases:
    def test_small_price_fixed_fee_dominates(self) -> None:
        """On very cheap cards, $0.30 fixed fee dominates."""
        fee = calculate_platform_fees(Decimal("1.00"), Platform.TCGPLAYER)
        variable = _q(Decimal("1.00") * settings.TCGPLAYER_FEE_RATE)
        expected = _q(variable + settings.TCGPLAYER_FIXED_FEE)
        assert fee == expected
        assert fee > variable  # Fixed fee matters more

    def test_high_value_card_cap_hit(self) -> None:
        """$2000 card still capped at $75 + $0.30 = $75.30."""
        fee = calculate_platform_fees(Decimal("2000.00"), Platform.TCGPLAYER)
        assert fee == Decimal("75.30")
