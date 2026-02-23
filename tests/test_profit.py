"""Tests for net profit calculator (Section 4.1)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pytest

from src.config import CustomsRegime, settings
from src.engine.profit import calculate_net_profit
from src.utils.forex import convert_eur_to_usd

_TWO_DP = Decimal("0.01")
_HUNDRED = Decimal("100")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def test_calculate_net_profit_de_minimis_below_threshold_has_no_customs() -> None:
    """de_minimis: COGS below threshold should not pay customs."""
    cm_price_eur = Decimal("100.00")
    tcg_price_usd = Decimal("200.00")
    forex_rate = Decimal("1.00")

    result = calculate_net_profit(
        cm_price_eur=cm_price_eur,
        tcg_price_usd=tcg_price_usd,
        forex_rate=forex_rate,
        condition="NM",
        customs_regime=CustomsRegime.DE_MINIMIS.value,
    )

    cogs = convert_eur_to_usd(cm_price_eur, forex_rate, buffer=settings.DEFAULT_FOREX_BUFFER)
    adjusted_price = _q(tcg_price_usd)
    fees = _q(min(adjusted_price * settings.TCGPLAYER_FEE_RATE, settings.TCGPLAYER_FEE_CAP) + settings.TCGPLAYER_FIXED_FEE)
    revenue = _q(adjusted_price - fees)
    expected_net = _q(revenue - cogs - settings.SHIPPING_COST_USD)
    expected_margin = _q((expected_net / revenue) * _HUNDRED)

    assert result["customs"] == Decimal("0.00")
    assert result["cogs_usd"] == cogs
    assert result["tcg_fees"] == fees
    assert result["revenue"] == revenue
    assert result["net_profit"] == expected_net
    assert result["margin_pct"] == expected_margin


def test_calculate_net_profit_de_minimis_above_threshold_applies_customs() -> None:
    """de_minimis: COGS above threshold pays standard US customs rate."""
    result = calculate_net_profit(
        cm_price_eur=Decimal("900.00"),
        tcg_price_usd=Decimal("1500.00"),
        forex_rate=Decimal("1.00"),
        condition="NM",
        customs_regime=CustomsRegime.DE_MINIMIS.value,
    )

    cogs = convert_eur_to_usd(Decimal("900.00"), Decimal("1.00"), buffer=settings.DEFAULT_FOREX_BUFFER)
    expected_customs = _q(cogs * settings.US_CUSTOMS_STANDARD_RATE)

    assert cogs > settings.US_DE_MINIMIS_USD
    assert result["customs"] == expected_customs


def test_calculate_net_profit_ioss_eu_applies_vat_and_flat_duty() -> None:
    """IOSS_EU: customs should include VAT plus flat EUR duty converted to USD."""
    forex_rate = Decimal("1.00")
    cm_price_eur = Decimal("100.00")
    result = calculate_net_profit(
        cm_price_eur=cm_price_eur,
        tcg_price_usd=Decimal("250.00"),
        forex_rate=forex_rate,
        condition="NM",
        customs_regime=CustomsRegime.IOSS_EU.value,
    )

    cogs = convert_eur_to_usd(cm_price_eur, forex_rate, buffer=settings.DEFAULT_FOREX_BUFFER)
    vat = cogs * settings.EU_VAT_RATE
    flat_duty_usd = convert_eur_to_usd(
        settings.EU_CUSTOMS_FLAT_DUTY_EUR,
        forex_rate,
        buffer=settings.DEFAULT_FOREX_BUFFER,
    )
    expected_customs = _q(vat + flat_duty_usd)

    assert result["customs"] == expected_customs


def test_calculate_net_profit_uk_low_value_applies_vat_above_threshold() -> None:
    """UK_LOW_VALUE: VAT applies when COGS exceeds configured threshold."""
    cm_price_eur = Decimal("200.00")
    forex_rate = Decimal("1.00")
    result = calculate_net_profit(
        cm_price_eur=cm_price_eur,
        tcg_price_usd=Decimal("400.00"),
        forex_rate=forex_rate,
        condition="NM",
        customs_regime=CustomsRegime.UK_LOW_VALUE.value,
    )

    cogs = convert_eur_to_usd(cm_price_eur, forex_rate, buffer=settings.DEFAULT_FOREX_BUFFER)
    expected_customs = _q(cogs * settings.UK_VAT_RATE)

    assert cogs > settings.UK_LOW_VALUE_THRESHOLD_USD
    assert result["customs"] == expected_customs


def test_calculate_net_profit_forwarder_costs_are_added() -> None:
    """Forwarder enabled: receiving + consolidation + insurance are included."""
    cm_price_eur = Decimal("50.00")
    forex_rate = Decimal("1.00")

    without_forwarder = calculate_net_profit(
        cm_price_eur=cm_price_eur,
        tcg_price_usd=Decimal("200.00"),
        forex_rate=forex_rate,
        condition="NM",
        customs_regime=CustomsRegime.DE_MINIMIS.value,
        use_forwarder=False,
    )
    with_forwarder = calculate_net_profit(
        cm_price_eur=cm_price_eur,
        tcg_price_usd=Decimal("200.00"),
        forex_rate=forex_rate,
        condition="NM",
        customs_regime=CustomsRegime.DE_MINIMIS.value,
        use_forwarder=True,
    )

    insurance_usd = convert_eur_to_usd(
        cm_price_eur * settings.DEFAULT_INSURANCE_RATE,
        forex_rate,
        buffer=settings.DEFAULT_FOREX_BUFFER,
    )
    expected_forwarder = _q(
        settings.DEFAULT_FORWARDER_RECEIVING_FEE
        + settings.DEFAULT_FORWARDER_CONSOLIDATION_FEE
        + insurance_usd
    )

    assert with_forwarder["forwarder_costs"] == expected_forwarder
    assert with_forwarder["net_profit"] < without_forwarder["net_profit"]


def test_calculate_net_profit_condition_penalty_is_applied() -> None:
    """Condition penalty: EXC should reduce adjusted TCG price and revenue."""
    common_kwargs = {
        "cm_price_eur": Decimal("100.00"),
        "tcg_price_usd": Decimal("200.00"),
        "forex_rate": Decimal("1.00"),
        "customs_regime": CustomsRegime.DE_MINIMIS.value,
    }
    nm = calculate_net_profit(condition="NM", **common_kwargs)
    exc = calculate_net_profit(condition="EXC", **common_kwargs)

    adjusted_exc = _q(Decimal("200.00") * settings.CONDITION_PENALTY_EXCELLENT)
    expected_exc_fees = _q(min(adjusted_exc * settings.TCGPLAYER_FEE_RATE, settings.TCGPLAYER_FEE_CAP) + settings.TCGPLAYER_FIXED_FEE)
    expected_exc_revenue = _q(adjusted_exc - expected_exc_fees)

    assert exc["revenue"] == expected_exc_revenue
    assert exc["net_profit"] < nm["net_profit"]


def test_calculate_net_profit_poor_condition_raises() -> None:
    """Poor condition should be rejected by condition mapping layer."""
    with pytest.raises(ValueError, match="Cannot map condition"):
        calculate_net_profit(
            cm_price_eur=Decimal("100.00"),
            tcg_price_usd=Decimal("200.00"),
            forex_rate=Decimal("1.00"),
            condition="Poor",
            customs_regime=CustomsRegime.DE_MINIMIS.value,
        )

