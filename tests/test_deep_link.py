"""Tests for deep link URL constructor."""

from __future__ import annotations

from urllib.parse import quote

from src.signals.deep_link import (
    build_cardmarket_url,
    build_signal_urls,
    build_tcgplayer_url,
)


class TestTCGPlayerURL:
    def test_existing_url_passthrough(self) -> None:
        url = build_tcgplayer_url("Charizard ex", existing_url="https://tcgplayer.com/card/123")
        assert url == "https://tcgplayer.com/card/123"

    def test_fallback_search_url(self) -> None:
        url = build_tcgplayer_url("Charizard ex")
        assert "tcgplayer.com/search" in url
        assert quote("Charizard ex") in url

    def test_fallback_with_set_name(self) -> None:
        url = build_tcgplayer_url("Charizard ex", set_name="Scarlet & Violet")
        assert quote("Charizard ex Scarlet & Violet") in url


class TestCardmarketURL:
    def test_existing_url_passthrough(self) -> None:
        url = build_cardmarket_url("Pikachu", existing_url="https://cardmarket.com/card/456")
        assert url == "https://cardmarket.com/card/456"

    def test_fallback_search_url(self) -> None:
        url = build_cardmarket_url("Pikachu")
        assert "cardmarket.com" in url
        assert quote("Pikachu") in url


class TestBuildSignalUrls:
    def test_both_existing_passthrough(self) -> None:
        urls = build_signal_urls(
            "Card", tcgplayer_url="https://tcg.com/1", cardmarket_url="https://cm.com/1"
        )
        assert urls["tcgplayer_url"] == "https://tcg.com/1"
        assert urls["cardmarket_url"] == "https://cm.com/1"

    def test_both_constructed_fallback(self) -> None:
        urls = build_signal_urls("Charizard ex", set_name="SV1")
        assert "tcgplayer.com" in urls["tcgplayer_url"]
        assert "cardmarket.com" in urls["cardmarket_url"]

    def test_mixed_existing_and_fallback(self) -> None:
        urls = build_signal_urls(
            "Charizard ex", tcgplayer_url="https://tcg.com/1", cardmarket_url=None
        )
        assert urls["tcgplayer_url"] == "https://tcg.com/1"
        assert "cardmarket.com" in urls["cardmarket_url"]
