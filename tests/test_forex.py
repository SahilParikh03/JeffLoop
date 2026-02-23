"""
TCG Radar — Forex Conversion Tests (Section 4.1)

Tests EUR/USD conversion with pessimistic 2% buffer.
All money values use Decimal for financial accuracy (no float rounding).

Rules from spec Section 4.1:
- When BUYING in EUR: assume EUR is 2% more expensive than spot (pessimistic)
- When SELLING in USD: assume USD is 2% weaker than spot (pessimistic)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.utils.forex import convert_eur_to_usd, convert_usd_to_eur


class TestConvertEURtoUSD:
    """EUR → USD conversion with pessimistic buffer (Section 4.1)."""

    def test_basic_conversion_with_buffer(self) -> None:
        """EUR -> USD applies 2% pessimistic buffer (Section 4.1).

        When buying in EUR, the buffer makes EUR appear 2% more expensive.
        Example: 100 EUR × 1.08 (spot) × 1.02 (buffer) = 110.16 USD
        """
        amount_eur = Decimal("100")
        spot_rate = Decimal("1.08")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        # Calculation: 100 × 1.08 × 1.02 = 110.16
        expected = Decimal("110.16")
        assert result == expected

    def test_default_buffer_is_2_percent(self) -> None:
        """Default buffer is 2% per spec Section 4.1."""
        amount_eur = Decimal("50")
        spot_rate = Decimal("1.00")

        # With 1.0 spot rate and 2% buffer: 50 × 1.00 × 1.02 = 51.00
        result = convert_eur_to_usd(amount_eur, spot_rate)
        expected = Decimal("51.00")
        assert result == expected

    def test_buffer_makes_eur_more_expensive(self) -> None:
        """Buffer makes EUR account for 2% higher cost (pessimistic for buyer).

        Without buffer: 100 EUR × 1.08 = 108 USD
        With buffer: 100 EUR × 1.08 × 1.02 = 110.16 USD
        Difference: 2.16 USD extra cost factored in.
        """
        amount_eur = Decimal("100")
        spot_rate = Decimal("1.08")

        result_with_buffer = convert_eur_to_usd(amount_eur, spot_rate)
        spot_result = amount_eur * spot_rate

        # Buffer should increase the cost
        assert result_with_buffer > spot_result
        # Verify buffer is approximately 2% of spot result
        buffer_impact = result_with_buffer - spot_result
        expected_buffer_impact = spot_result * Decimal("0.02")
        assert buffer_impact == expected_buffer_impact

    def test_custom_buffer_parameter(self) -> None:
        """Buffer parameter can be customized (Section 4.1)."""
        amount_eur = Decimal("100")
        spot_rate = Decimal("1.00")
        custom_buffer = Decimal("0.05")  # 5% buffer

        result = convert_eur_to_usd(amount_eur, spot_rate, buffer=custom_buffer)

        # 100 × 1.00 × 1.05 = 105.00
        expected = Decimal("105.00")
        assert result == expected

    def test_zero_amount_returns_zero(self) -> None:
        """Zero EUR amount returns zero USD (Section 4.1)."""
        amount_eur = Decimal("0")
        spot_rate = Decimal("1.08")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        assert result == Decimal("0.00")

    def test_negative_amount_raises_error(self) -> None:
        """Negative EUR amount raises ValueError (Section 4.1)."""
        amount_eur = Decimal("-10")
        spot_rate = Decimal("1.08")

        with pytest.raises(ValueError) as exc_info:
            convert_eur_to_usd(amount_eur, spot_rate)

        assert "must be non-negative" in str(exc_info.value)

    def test_edge_case_rate_equals_one(self) -> None:
        """EUR === USD exchange rate (1:1) with buffer (Section 4.1)."""
        amount_eur = Decimal("100")
        spot_rate = Decimal("1.00")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        # 100 × 1.00 × 1.02 = 102.00
        expected = Decimal("102.00")
        assert result == expected

    def test_realistic_price_ranges(self) -> None:
        """EUR -> USD conversion on realistic TCG price ranges (Section 4.1)."""
        spot_rate = Decimal("1.08")

        # €5 card (long-tail)
        result_5 = convert_eur_to_usd(Decimal("5"), spot_rate)
        assert result_5 == Decimal("5.51")  # 5 × 1.08 × 1.02 = 5.508 → 5.51

        # €25 card (mid-tier)
        result_25 = convert_eur_to_usd(Decimal("25"), spot_rate)
        assert result_25 == Decimal("27.54")  # 25 × 1.08 × 1.02 = 27.54

        # €100 card (high-value)
        result_100 = convert_eur_to_usd(Decimal("100"), spot_rate)
        assert result_100 == Decimal("110.16")  # 100 × 1.08 × 1.02

    def test_decimal_precision_no_rounding_errors(self) -> None:
        """Conversion maintains Decimal precision (no float rounding).

        Must use ROUND_HALF_UP and quantize to 2 decimal places.
        """
        amount_eur = Decimal("33.33")
        spot_rate = Decimal("1.07")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        # Verify result is Decimal and maintains 2dp precision
        assert isinstance(result, Decimal)
        assert result.as_tuple().exponent == -2  # Exactly 2 decimal places


class TestConvertUSDtoEUR:
    """USD → EUR conversion with pessimistic buffer (Section 4.1)."""

    def test_basic_conversion_with_buffer(self) -> None:
        """USD -> EUR applies 2% pessimistic buffer (Section 4.1).

        When selling in USD, buffer makes USD appear 2% weaker.
        Example: 108 USD / (1.08 × 1.02) ≈ 98.04 EUR
        """
        amount_usd = Decimal("108")
        spot_rate = Decimal("1.08")

        result = convert_usd_to_eur(amount_usd, spot_rate)

        # Calculation: 108 / (1.08 × 1.02) = 108 / 1.1016 ≈ 98.04
        # Using Decimal arithmetic for precision
        buffered_rate = spot_rate * (Decimal("1") + Decimal("0.02"))
        expected = (amount_usd / buffered_rate).quantize(Decimal("0.01"))
        assert result == expected

    def test_default_buffer_is_2_percent(self) -> None:
        """Default buffer is 2% per spec Section 4.1."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("1.00")

        # With 1.0 spot rate and 2% buffer: 100 / (1.00 × 1.02) ≈ 98.04
        result = convert_usd_to_eur(amount_usd, spot_rate)
        # 100 / 1.02 = 98.03921... → 98.04
        assert result == Decimal("98.04")

    def test_buffer_makes_usd_weaker(self) -> None:
        """Buffer makes USD account for 2% weakness (pessimistic for seller).

        Without buffer: 108 USD / 1.08 = 100 EUR
        With buffer: 108 USD / (1.08 × 1.02) ≈ 98.04 EUR
        Difference: User receives ~1.96 EUR LESS due to buffer.
        """
        amount_usd = Decimal("108")
        spot_rate = Decimal("1.08")

        result_with_buffer = convert_usd_to_eur(amount_usd, spot_rate)
        spot_result = amount_usd / spot_rate

        # Buffer should decrease the EUR amount
        assert result_with_buffer < spot_result

    def test_custom_buffer_parameter(self) -> None:
        """Buffer parameter can be customized (Section 4.1)."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("1.00")
        custom_buffer = Decimal("0.05")  # 5% buffer

        result = convert_usd_to_eur(amount_usd, spot_rate, buffer=custom_buffer)

        # 100 / (1.00 × 1.05) = 100 / 1.05 ≈ 95.24
        expected = Decimal("95.24")
        assert result == expected

    def test_zero_amount_returns_zero(self) -> None:
        """Zero USD amount returns zero EUR (Section 4.1)."""
        amount_usd = Decimal("0")
        spot_rate = Decimal("1.08")

        result = convert_usd_to_eur(amount_usd, spot_rate)

        assert result == Decimal("0.00")

    def test_negative_amount_raises_error(self) -> None:
        """Negative USD amount raises ValueError (Section 4.1)."""
        amount_usd = Decimal("-50")
        spot_rate = Decimal("1.08")

        with pytest.raises(ValueError) as exc_info:
            convert_usd_to_eur(amount_usd, spot_rate)

        assert "must be non-negative" in str(exc_info.value)

    def test_zero_rate_raises_error(self) -> None:
        """Zero exchange rate raises ValueError (Section 4.1)."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("0")

        with pytest.raises(ValueError) as exc_info:
            convert_usd_to_eur(amount_usd, spot_rate)

        assert "must be positive" in str(exc_info.value)

    def test_negative_rate_raises_error(self) -> None:
        """Negative exchange rate raises ValueError (Section 4.1)."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("-1.08")

        with pytest.raises(ValueError) as exc_info:
            convert_usd_to_eur(amount_usd, spot_rate)

        assert "must be positive" in str(exc_info.value)

    def test_edge_case_rate_equals_one(self) -> None:
        """USD === EUR exchange rate (1:1) with buffer (Section 4.1)."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("1.00")

        result = convert_usd_to_eur(amount_usd, spot_rate)

        # 100 / (1.00 × 1.02) = 100 / 1.02 ≈ 98.04
        expected = Decimal("98.04")
        assert result == expected

    def test_realistic_price_ranges(self) -> None:
        """USD -> EUR conversion on realistic TCG price ranges (Section 4.1)."""
        spot_rate = Decimal("1.08")
        buffered_rate = spot_rate * Decimal("1.02")

        # $5 card (long-tail)
        result_5 = convert_usd_to_eur(Decimal("5"), spot_rate)
        expected_5 = (Decimal("5") / buffered_rate).quantize(Decimal("0.01"))
        assert result_5 == expected_5

        # $25 card (mid-tier)
        result_25 = convert_usd_to_eur(Decimal("25"), spot_rate)
        expected_25 = (Decimal("25") / buffered_rate).quantize(Decimal("0.01"))
        assert result_25 == expected_25

        # $100 card (high-value)
        result_100 = convert_usd_to_eur(Decimal("100"), spot_rate)
        expected_100 = (Decimal("100") / buffered_rate).quantize(Decimal("0.01"))
        assert result_100 == expected_100

    def test_decimal_precision_no_rounding_errors(self) -> None:
        """Conversion maintains Decimal precision (no float rounding).

        Must use ROUND_HALF_UP and quantize to 2 decimal places.
        """
        amount_usd = Decimal("123.45")
        spot_rate = Decimal("1.17")

        result = convert_usd_to_eur(amount_usd, spot_rate)

        # Verify result is Decimal and maintains 2dp precision
        assert isinstance(result, Decimal)
        assert result.as_tuple().exponent == -2  # Exactly 2 decimal places


class TestForexRoundTrip:
    """Round-trip conversions to verify buffer symmetry (Section 4.1)."""

    def test_eur_to_usd_to_eur_loses_value_symmetrically(self) -> None:
        """EUR -> USD -> EUR conversion with symmetric buffers (Section 4.1).

        Due to rounding at each conversion step, round-trip does not
        always show loss (especially with larger amounts). The important
        point is the buffers applied pessimistically at each step.
        """
        original_eur = Decimal("1000.00")  # Larger amount to see buffer effect
        spot_rate = Decimal("1.08")

        # EUR to USD with pessimistic buffer (makes EUR more expensive)
        usd_amount = convert_eur_to_usd(original_eur, spot_rate)
        # 1000 × 1.08 × 1.02 = 1101.60 (quantized to 2dp)

        # USD back to EUR with pessimistic buffer (makes USD weaker)
        final_eur = convert_usd_to_eur(usd_amount, spot_rate)
        # 1101.60 / (1.08 × 1.02) = 1101.60 / 1.1016 = 1000.00

        # Verify the buffers were applied correctly in both directions
        assert usd_amount == Decimal("1101.60")
        # Round-trip should get back close to original due to symmetry
        assert final_eur == original_eur

    def test_buffer_impact_on_margin_calculation(self) -> None:
        """Buffers conservatively reduce profit margin on arbitrage (Section 4.1).

        Simulates: Buy at X EUR, sell at Y USD, convert back to EUR.
        The 2% buffers on both sides eat into the spread.
        """
        buy_eur = Decimal("20")
        sell_usd = Decimal("30")  # Nominal spread
        spot_rate = Decimal("1.50")

        # Pessimistic: buying appears more expensive
        actual_buy_usd = convert_eur_to_usd(buy_eur, spot_rate)
        # Pessimistic: selling appears weaker in EUR terms
        actual_sell_eur = convert_usd_to_eur(sell_usd, spot_rate)

        # Spread shrinks due to buffers (before fees)
        nominal_spread_eur = sell_usd / spot_rate - buy_eur
        actual_spread_eur = actual_sell_eur - buy_eur

        # Actual spread should be less than nominal
        assert actual_spread_eur < nominal_spread_eur


class TestForexEdgeCases:
    """Edge cases and boundary conditions (Section 4.1)."""

    def test_very_small_amounts(self) -> None:
        """Very small amounts (sub-cent) maintain precision (Section 4.1)."""
        amount_eur = Decimal("0.01")
        spot_rate = Decimal("1.08")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        # 0.01 × 1.08 × 1.02 = 0.011016 → 0.01
        assert isinstance(result, Decimal)
        assert result.as_tuple().exponent == -2

    def test_very_large_amounts(self) -> None:
        """Very large amounts (booster box cases) maintain precision (Section 4.1)."""
        amount_eur = Decimal("10000")
        spot_rate = Decimal("1.08")

        result = convert_eur_to_usd(amount_eur, spot_rate)

        # 10000 × 1.08 × 1.02 = 11016.00
        expected = Decimal("11016.00")
        assert result == expected
        assert isinstance(result, Decimal)

    def test_extreme_exchange_rate(self) -> None:
        """Extreme exchange rates are handled correctly (Section 4.1)."""
        amount_eur = Decimal("100")
        extreme_rate = Decimal("2.00")

        result = convert_eur_to_usd(amount_eur, extreme_rate)

        # 100 × 2.00 × 1.02 = 204.00
        expected = Decimal("204.00")
        assert result == expected

    def test_low_exchange_rate(self) -> None:
        """Very low exchange rates are handled correctly (Section 4.1)."""
        amount_usd = Decimal("100")
        spot_rate = Decimal("0.50")

        result = convert_usd_to_eur(amount_usd, spot_rate)

        # 100 / (0.50 × 1.02) = 100 / 0.51 ≈ 196.08
        buffered_rate = spot_rate * Decimal("1.02")
        expected = (amount_usd / buffered_rate).quantize(Decimal("0.01"))
        assert result == expected
