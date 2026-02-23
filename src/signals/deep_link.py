"""
TCG Radar — Deep Link URL Constructor (Section 14)

Constructs marketplace URLs for signal delivery.
Pass-through when metadata URLs exist, fallback construction when missing.
"""

from __future__ import annotations

from urllib.parse import quote

import structlog

logger = structlog.get_logger(__name__)

_TCGPLAYER_SEARCH_BASE = "https://www.tcgplayer.com/search/pokemon/product?q="
_CARDMARKET_SEARCH_BASE = "https://www.cardmarket.com/en/Pokemon/Cards?searchString="


def build_tcgplayer_url(
    card_name: str,
    set_name: str | None = None,
    existing_url: str | None = None,
) -> str:
    """
    Build a TCGPlayer deep link.

    Uses existing URL if available, otherwise constructs a search URL.

    Args:
        card_name: Card display name (e.g., "Charizard ex").
        set_name: Set name for disambiguation (optional).
        existing_url: Pre-existing URL from card metadata.

    Returns:
        TCGPlayer URL string.
    """
    if existing_url:
        return existing_url

    query = card_name
    if set_name:
        query = f"{card_name} {set_name}"

    url = f"{_TCGPLAYER_SEARCH_BASE}{quote(query)}"
    logger.debug(
        "tcgplayer_url_constructed",
        card_name=card_name,
        set_name=set_name,
        url=url,
        source="deep_link",
    )
    return url


def build_cardmarket_url(
    card_name: str,
    set_name: str | None = None,
    existing_url: str | None = None,
) -> str:
    """
    Build a Cardmarket deep link.

    Uses existing URL if available, otherwise constructs a search URL.

    Args:
        card_name: Card display name.
        set_name: Set name for disambiguation (optional).
        existing_url: Pre-existing URL from card metadata.

    Returns:
        Cardmarket URL string.
    """
    if existing_url:
        return existing_url

    query = card_name
    if set_name:
        query = f"{card_name} {set_name}"

    url = f"{_CARDMARKET_SEARCH_BASE}{quote(query)}"
    logger.debug(
        "cardmarket_url_constructed",
        card_name=card_name,
        set_name=set_name,
        url=url,
        source="deep_link",
    )
    return url


def build_signal_urls(
    card_name: str,
    set_name: str | None = None,
    tcgplayer_url: str | None = None,
    cardmarket_url: str | None = None,
) -> dict[str, str]:
    """
    Build both marketplace URLs for a signal.

    Args:
        card_name: Card display name.
        set_name: Set name for disambiguation.
        tcgplayer_url: Pre-existing TCGPlayer URL.
        cardmarket_url: Pre-existing Cardmarket URL.

    Returns:
        Dict with "tcgplayer_url" and "cardmarket_url" keys.
    """
    return {
        "tcgplayer_url": build_tcgplayer_url(card_name, set_name, tcgplayer_url),
        "cardmarket_url": build_cardmarket_url(card_name, set_name, cardmarket_url),
    }
