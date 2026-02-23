"""Tests for effective price calculator (Section 4.1)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.config import settings
from src.engine.effective_price import (
    calculate_condition_adjusted_sell_price,
    calculate_effective_buy_price,
)
from src.utils.condition_map import CardmarketGrade
from src.utils.forex import convert_eur_to_usd

_TWO_DP = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Buy side tests
# ---------------------------------------------------------------------------

class TestEffectiveBuyPrice:
    def test_basic_conversion(self) -> None:
        """Listing + shipping converted to USD with pessimistic buffer."""
        result = calculate_effective_buy_price(
            listing_eur=Decimal("50.00"),
            shipping_eur=Decimal("5.00"),
            forex_rate=Decimal("1.08"),
        )
        expected = convert_eur_to_usd(Decimal("55.00"), Decimal("1.08"), buffer=settings.DEFAULT_FOREX_BUFFER)
        assert result == expected

    def test_zero_shipping(self) -> None:
        """Free shipping — only listing converted."""
        result = calculate_effective_buy_price(
            listing_eur=Decimal("100.00"),
            shipping_eur=Decimal("0.00"),
            forex_rate=Decimal("1.10"),
        )
        expected = convert_eur_to_usd(Decimal("100.00"), Decimal("1.10"), buffer=settings.DEFAULT_FOREX_BUFFER)
        assert result == expected

    def test_custom_forex_buffer(self) -> None:
        """Override the default 2% buffer."""
        result = calculate_effective_buy_price(
            listing_eur=Decimal("100.00"),
            shipping_eur=Decimal("0.00"),
            forex_rate=Decimal("1.00"),
            forex_buffer=Decimal("0.05"),
        )
        expected = convert_eur_to_usd(Decimal("100.00"), Decimal("1.00"), buffer=Decimal("0.05"))
        assert result == expected

    def test_negative_listing_raises(self) -> None:
        with pytest.raises(ValueError, match="listing_eur"):
            calculate_effective_buy_price(Decimal("-1.00"), Decimal("0"), Decimal("1.08"))

    def test_negative_shipping_raises(self) -> None:
        with pytest.raises(ValueError, match="shipping_eur"):
            calculate_effective_buy_price(Decimal("10.00"), Decimal("-1.00"), Decimal("1.08"))

    def test_zero_forex_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="forex_rate"):
            calculate_effective_buy_price(Decimal("10.00"), Decimal("0"), Decimal("0"))


# ---------------------------------------------------------------------------
# Sell side tests
# ---------------------------------------------------------------------------

class TestConditionAdjustedSellPrice:
    def test_near_mint_no_penalty(self) -> None:
        """NM → NM, multiplier 1.00."""
        adjusted, mult = calculate_condition_adjusted_sell_price(
            Decimal("100.00"), CardmarketGrade.NEAR_MINT
        )
        assert adjusted == Decimal("100.00")
        assert mult == Decimal("1.00")

    def test_excellent_15pct_penalty(self) -> None:
        """EXC → LP, -15% penalty."""
        adjusted, mult = calculate_condition_adjusted_sell_price(
            Decimal("100.00"), CardmarketGrade.EXCELLENT
        )
        assert adjusted == Decimal("85.00")
        assert mult == Decimal("0.85")

    def test_played_40pct_penalty(self) -> None:
        """PL → HP, -40% penalty."""
        adjusted, mult = calculate_condition_adjusted_sell_price(
            Decimal("100.00"), CardmarketGrade.PLAYED
        )
        assert adjusted == Decimal("60.00")
        assert mult == Decimal("0.60")

    def test_poor_raises_value_error(self) -> None:
        """POOR must suppress signal — raises ValueError."""
        with pytest.raises(ValueError, match="Cannot map condition"):
            calculate_condition_adjusted_sell_price(
                Decimal("100.00"), CardmarketGrade.POOR
            )
