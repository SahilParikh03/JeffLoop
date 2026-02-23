"""
TCG Radar - Net Profit Calculator (Section 4.1)

Net_Profit = TCGPlayer_Sell_Price - COGS - Platform_Fees - Customs_Import
             - Shipping - Forwarder_Costs
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import structlog

from src.config import CustomsRegime, settings
from src.utils.condition_map import CardmarketGrade, map_condition
from src.utils.forex import convert_eur_to_usd

logger = structlog.get_logger(__name__)

_TWO_DP = Decimal("0.01")
_HUNDRED = Decimal("100")
_ZERO = Decimal("0")

_CONDITION_ALIASES: dict[str, str] = {
    "MINT": CardmarketGrade.MINT.value,
    "MT": CardmarketGrade.MINT.value,
    "NEAR MINT": CardmarketGrade.NEAR_MINT.value,
    "NEAR_MINT": CardmarketGrade.NEAR_MINT.value,
    "NM": CardmarketGrade.NEAR_MINT.value,
    "EXCELLENT": CardmarketGrade.EXCELLENT.value,
    "EXC": CardmarketGrade.EXCELLENT.value,
    "GOOD": CardmarketGrade.GOOD.value,
    "GD": CardmarketGrade.GOOD.value,
    "LIGHT PLAYED": CardmarketGrade.LIGHT_PLAYED.value,
    "LIGHT_PLAYED": CardmarketGrade.LIGHT_PLAYED.value,
    "LIGHTLY PLAYED": CardmarketGrade.LIGHT_PLAYED.value,
    "LIGHTLY_PLAYED": CardmarketGrade.LIGHT_PLAYED.value,
    "LP": CardmarketGrade.LIGHT_PLAYED.value,
    "PLAYED": CardmarketGrade.PLAYED.value,
    "PL": CardmarketGrade.PLAYED.value,
    "POOR": CardmarketGrade.POOR.value,
    "DAMAGED": CardmarketGrade.POOR.value,
    "PO": CardmarketGrade.POOR.value,
}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _normalize_condition(condition: str) -> CardmarketGrade:
    normalized = condition.strip().upper()
    mapped = _CONDITION_ALIASES.get(normalized, normalized)
    return CardmarketGrade(mapped)


def _normalize_customs_regime(customs_regime: str) -> CustomsRegime:
    normalized = customs_regime.strip().lower()
    by_value = {regime.value: regime for regime in CustomsRegime}
    if normalized in by_value:
        return by_value[normalized]

    normalized_member = customs_regime.strip().upper()
    if normalized_member in CustomsRegime.__members__:
        return CustomsRegime[normalized_member]

    raise ValueError(f"Unsupported customs_regime '{customs_regime}'")


def _calculate_customs(cogs_usd: Decimal, forex_rate: Decimal, regime: CustomsRegime) -> Decimal:
    if regime in (CustomsRegime.DE_MINIMIS, CustomsRegime.PRE_JULY_2026):
        if cogs_usd < settings.US_DE_MINIMIS_USD:
            return _ZERO
        return _quantize(cogs_usd * settings.US_CUSTOMS_STANDARD_RATE)

    if regime in (CustomsRegime.IOSS_EU, CustomsRegime.POST_JULY_2026):
        vat_cost = cogs_usd * settings.EU_VAT_RATE
        flat_duty_usd = convert_eur_to_usd(
            settings.EU_CUSTOMS_FLAT_DUTY_EUR,
            forex_rate,
            buffer=settings.DEFAULT_FOREX_BUFFER,
        )
        return _quantize(vat_cost + flat_duty_usd)

    if regime == CustomsRegime.UK_LOW_VALUE:
        if cogs_usd > settings.UK_LOW_VALUE_THRESHOLD_USD:
            return _quantize(cogs_usd * settings.UK_VAT_RATE)
        return _ZERO

    raise ValueError(f"Unsupported customs regime '{regime.value}'")


def calculate_net_profit(
    cm_price_eur: Decimal,
    tcg_price_usd: Decimal,
    forex_rate: Decimal,
    condition: str,
    customs_regime: str,
    seller_level: str | None = None,
    use_forwarder: bool = False,
    forwarder_receiving_fee: Decimal = Decimal("3.50"),
    forwarder_consolidation_fee: Decimal = Decimal("7.50"),
    insurance_rate: Decimal = Decimal("0.025"),
) -> dict[str, Decimal]:
    """Calculate net profit and return a 2dp fee/cost breakdown."""
    if cm_price_eur < _ZERO:
        raise ValueError("cm_price_eur must be non-negative")
    if tcg_price_usd < _ZERO:
        raise ValueError("tcg_price_usd must be non-negative")
    if forex_rate <= _ZERO:
        raise ValueError("forex_rate must be positive")
    if forwarder_receiving_fee < _ZERO:
        raise ValueError("forwarder_receiving_fee must be non-negative")
    if forwarder_consolidation_fee < _ZERO:
        raise ValueError("forwarder_consolidation_fee must be non-negative")
    if insurance_rate < _ZERO:
        raise ValueError("insurance_rate must be non-negative")

    cardmarket_grade = _normalize_condition(condition)
    condition_mapping = map_condition(cardmarket_grade)
    regime = _normalize_customs_regime(customs_regime)

    cogs_usd = convert_eur_to_usd(
        cm_price_eur,
        forex_rate,
        buffer=settings.DEFAULT_FOREX_BUFFER,
    )
    adjusted_tcg_price = _quantize(tcg_price_usd * condition_mapping.price_multiplier)
    tcg_fees = _quantize(adjusted_tcg_price * settings.TCGPLAYER_FEE_RATE)
    customs = _calculate_customs(cogs_usd, forex_rate, regime)
    shipping = _quantize(settings.SHIPPING_COST_USD)

    forwarder_costs = _ZERO
    if use_forwarder:
        insurance_eur = cm_price_eur * insurance_rate
        insurance_usd = convert_eur_to_usd(
            insurance_eur,
            forex_rate,
            buffer=settings.DEFAULT_FOREX_BUFFER,
        )
        forwarder_costs = _quantize(
            forwarder_receiving_fee + forwarder_consolidation_fee + insurance_usd
        )

    revenue = _quantize(adjusted_tcg_price - tcg_fees)
    total_costs = cogs_usd + customs + shipping + forwarder_costs
    net_profit = _quantize(revenue - total_costs)

    margin_pct = _ZERO
    if revenue != _ZERO:
        margin_pct = _quantize((net_profit / revenue) * _HUNDRED)

    result = {
        "net_profit": net_profit,
        "revenue": revenue,
        "cogs_usd": _quantize(cogs_usd),
        "tcg_fees": tcg_fees,
        "customs": _quantize(customs),
        "shipping": shipping,
        "forwarder_costs": _quantize(forwarder_costs),
        "margin_pct": margin_pct,
    }

    logger.info(
        "profit_calculated",
        seller_level=seller_level,
        customs_regime=regime.value,
        condition=cardmarket_grade.value,
        use_forwarder=use_forwarder,
        net_profit=str(result["net_profit"]),
        margin_pct=str(result["margin_pct"]),
    )
    return result

