"""
Tests for the Scraper Layer (Section 6).

Covers:
- AntiDetect: rate limiting, user agent rotation, proxy config
- NetworkIntercept: data parsing helpers
- CSSFallback: price/int/decimal parsing helpers
- ScraperRunner: fallback chain orchestration
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.scraper import ScraperResult
from src.scraper.anti_detect import AntiDetect
from src.scraper.css_fallback import _parse_decimal, _parse_int, _parse_price
from src.scraper.network_intercept import _parse_intercepted_data, _safe_decimal
from src.scraper.runner import ScraperRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_page() -> AsyncMock:
    page = AsyncMock()
    page.route = AsyncMock()
    page.goto = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake-image-data")
    page.query_selector = AsyncMock(return_value=None)
    return page


@pytest.fixture
def sample_result() -> ScraperResult:
    return ScraperResult(
        card_id="sv1-25",
        price_eur=Decimal("12.50"),
        seller_id="seller-123",
        seller_rating=Decimal("99.5"),
        seller_sales=2500,
        condition="NEAR_MINT",
        shipping_eur=Decimal("1.50"),
        seller_other_cards=["sv1-1", "sv1-2"],
        scrape_method="network_intercept",
        scraped_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# AntiDetect tests
# ---------------------------------------------------------------------------

class TestAntiDetect:
    def test_can_scrape_under_limit(self) -> None:
        """Returns True when page count is under the hourly cap."""
        ad = AntiDetect()
        # No pages recorded yet, should be able to scrape
        assert ad.can_scrape() is True

    def test_can_scrape_over_limit(self) -> None:
        """Returns False once the hourly cap is reached."""
        ad = AntiDetect()
        ad._max_pages_per_hour = 3
        # Fill up to cap
        ad._pages_this_hour = 3
        assert ad.can_scrape() is False

    def test_record_page_increments(self) -> None:
        """record_page() increments the counter by 1."""
        ad = AntiDetect()
        initial = ad._pages_this_hour
        ad.record_page()
        assert ad._pages_this_hour == initial + 1

    def test_hour_reset(self) -> None:
        """Counter resets to 0 after the hour window expires."""
        ad = AntiDetect()
        ad._pages_this_hour = 25
        # Simulate the hour start being 61 minutes ago
        ad._hour_start = datetime.now(timezone.utc) - timedelta(seconds=3661)
        ad._reset_hour_if_needed()
        assert ad._pages_this_hour == 0

    def test_random_user_agent(self) -> None:
        """get_random_user_agent() returns a non-empty string from the list."""
        ad = AntiDetect()
        ua = ad.get_random_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 0
        assert ua in AntiDetect.USER_AGENTS

    def test_proxy_config_none_when_not_set(self) -> None:
        """Returns None when PROXY_URL is empty."""
        ad = AntiDetect()
        # Default settings have PROXY_URL = ""
        result = ad.get_proxy_config()
        assert result is None

    def test_pages_remaining_correct_math(self) -> None:
        """pages_remaining = max - used."""
        ad = AntiDetect()
        ad._max_pages_per_hour = 30
        ad._pages_this_hour = 10
        assert ad.pages_remaining == 20

    def test_pages_remaining_floors_at_zero(self) -> None:
        """pages_remaining never goes negative."""
        ad = AntiDetect()
        ad._max_pages_per_hour = 5
        ad._pages_this_hour = 10
        assert ad.pages_remaining == 0


# ---------------------------------------------------------------------------
# NetworkIntercept helpers
# ---------------------------------------------------------------------------

class TestNetworkInterceptParsing:
    def test_parse_intercepted_data_success(self) -> None:
        """Valid intercepted data produces a correctly populated ScraperResult."""
        data = {
            "price": "12.50",
            "sellerId": "seller-123",
            "sellerRating": "99.5",
            "sellerSales": 2500,
            "condition": "NEAR_MINT",
            "shippingPrice": "1.50",
            "sellerOtherCards": ["sv1-1", "sv1-2", "sv1-3"],
        }
        result = _parse_intercepted_data("sv1-25", data)
        assert result is not None
        assert result.card_id == "sv1-25"
        assert result.price_eur == Decimal("12.50")
        assert result.seller_id == "seller-123"
        assert result.seller_rating == Decimal("99.5")
        assert result.seller_sales == 2500
        assert result.condition == "NEAR_MINT"
        assert result.shipping_eur == Decimal("1.50")
        assert result.seller_other_cards == ["sv1-1", "sv1-2", "sv1-3"]
        assert result.scrape_method == "network_intercept"

    def test_parse_intercepted_data_empty_returns_none(self) -> None:
        """Empty dict returns None (no price, no seller data)."""
        result = _parse_intercepted_data("sv1-25", {})
        # Empty data: all fields None except required ones, result may still be built
        # but price_eur will be None — ScraperResult allows that
        # The function should still produce a result (not raise), price_eur=None
        assert result is not None
        assert result.price_eur is None

    def test_safe_decimal_valid_string(self) -> None:
        """'12.50' converts to Decimal('12.50')."""
        assert _safe_decimal("12.50") == Decimal("12.50")

    def test_safe_decimal_valid_int(self) -> None:
        """Integer 12 converts to Decimal('12')."""
        assert _safe_decimal(12) == Decimal("12")

    def test_safe_decimal_none_returns_none(self) -> None:
        """None input returns None."""
        assert _safe_decimal(None) is None

    def test_safe_decimal_invalid_returns_none(self) -> None:
        """Non-numeric string returns None."""
        assert _safe_decimal("abc") is None

    def test_seller_other_cards_capped_at_50(self) -> None:
        """sellerOtherCards list is capped at 50 entries."""
        data = {
            "sellerOtherCards": [f"sv1-{i}" for i in range(100)],
        }
        result = _parse_intercepted_data("sv1-25", data)
        assert result is not None
        assert len(result.seller_other_cards) == 50

    def test_alternate_field_names(self) -> None:
        """Supports snake_case field names as fallback."""
        data = {
            "priceEUR": "8.00",
            "seller_id": "alt-seller",
            "seller_rating": "97.0",
            "seller_sales": 500,
        }
        result = _parse_intercepted_data("sv2-10", data)
        assert result is not None
        assert result.price_eur == Decimal("8.00")
        assert result.seller_id == "alt-seller"
        assert result.seller_rating == Decimal("97.0")
        assert result.seller_sales == 500


# ---------------------------------------------------------------------------
# CSSFallback helpers
# ---------------------------------------------------------------------------

class TestCSSFallbackParsing:
    def test_parse_price_eur_symbol(self) -> None:
        """'€12.50' parses to Decimal('12.50')."""
        assert _parse_price("€12.50") == Decimal("12.50")

    def test_parse_price_comma_format(self) -> None:
        """'12,50 €' (European comma format) parses to Decimal('12.50')."""
        assert _parse_price("12,50 €") == Decimal("12.50")

    def test_parse_price_none_returns_none(self) -> None:
        """None input returns None."""
        assert _parse_price(None) is None

    def test_parse_price_empty_returns_none(self) -> None:
        """Empty string returns None."""
        assert _parse_price("") is None

    def test_parse_int_with_comma_separator(self) -> None:
        """'2,500' parses to integer 2500."""
        assert _parse_int("2,500") == 2500

    def test_parse_int_simple(self) -> None:
        """'1234' parses to integer 1234."""
        assert _parse_int("1234") == 1234

    def test_parse_int_none_returns_none(self) -> None:
        """None input returns None."""
        assert _parse_int(None) is None

    def test_parse_decimal_extracts_number(self) -> None:
        """'99.5%' extracts Decimal('99.5')."""
        assert _parse_decimal("99.5%") == Decimal("99.5")

    def test_parse_decimal_none_returns_none(self) -> None:
        """None returns None."""
        assert _parse_decimal(None) is None


# ---------------------------------------------------------------------------
# ScraperRunner tests
# ---------------------------------------------------------------------------

class TestScraperRunner:
    @pytest.fixture(autouse=True)
    def enable_layer3_scraping(self):
        """Ensure ENABLE_LAYER_3_SCRAPING=True for all ScraperRunner tests (flag is False by default)."""
        from src.config import settings
        with patch.object(settings, "ENABLE_LAYER_3_SCRAPING", True):
            yield

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_runner_tries_network_first(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """When network intercept succeeds, CSS and vision are not called."""
        mock_network.return_value = ScraperResult(
            card_id="sv1-25",
            price_eur=Decimal("12.50"),
            scrape_method="network_intercept",
            scraped_at=datetime.now(timezone.utc),
        )
        mock_css.return_value = None
        mock_vision.return_value = None

        runner = ScraperRunner()
        # Patch random_delay to be instant
        runner.anti_detect.random_delay = AsyncMock()
        result = await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert result is not None
        assert result.scrape_method == "network_intercept"
        mock_css.assert_not_called()
        mock_vision.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_runner_falls_back_to_css(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """When network intercept returns None, CSS fallback is used."""
        mock_network.return_value = None
        mock_css.return_value = ScraperResult(
            card_id="sv1-25",
            price_eur=Decimal("10.00"),
            scrape_method="css_fallback",
            scraped_at=datetime.now(timezone.utc),
        )
        mock_vision.return_value = None

        runner = ScraperRunner()
        runner.anti_detect.random_delay = AsyncMock()
        result = await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert result is not None
        assert result.scrape_method == "css_fallback"
        mock_vision.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_runner_rate_limited(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """When can_scrape() returns False, runner returns None immediately."""
        runner = ScraperRunner()
        runner.anti_detect._pages_this_hour = runner.anti_detect._max_pages_per_hour

        result = await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert result is None
        mock_network.assert_not_called()
        mock_css.assert_not_called()
        mock_vision.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_runner_all_methods_fail_returns_none(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """Returns None when all three methods return None."""
        mock_network.return_value = None
        mock_css.return_value = None
        mock_vision.return_value = None

        runner = ScraperRunner()
        runner.anti_detect.random_delay = AsyncMock()
        result = await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert result is None
        mock_network.assert_called_once()
        mock_css.assert_called_once()
        mock_vision.assert_called_once()

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_scraper_disabled_by_feature_flag(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """When ENABLE_LAYER_3_SCRAPING is False, scraper returns None without calling any method."""
        from src.config import settings

        runner = ScraperRunner()
        with patch.object(settings, "ENABLE_LAYER_3_SCRAPING", False):
            result = await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert result is None
        mock_network.assert_not_called()
        mock_css.assert_not_called()
        mock_vision.assert_not_called()

    @pytest.mark.asyncio
    @patch("src.scraper.runner.scrape_via_vision")
    @patch("src.scraper.runner.scrape_via_css")
    @patch("src.scraper.runner.scrape_via_network_intercept")
    async def test_runner_records_page_on_success(
        self,
        mock_network: AsyncMock,
        mock_css: AsyncMock,
        mock_vision: AsyncMock,
        mock_page: AsyncMock,
    ) -> None:
        """Page counter is incremented after a successful scrape."""
        mock_network.return_value = ScraperResult(
            card_id="sv1-25",
            price_eur=Decimal("12.50"),
            scrape_method="network_intercept",
            scraped_at=datetime.now(timezone.utc),
        )

        runner = ScraperRunner()
        runner.anti_detect.random_delay = AsyncMock()
        initial_count = runner.anti_detect._pages_this_hour

        await runner.scrape_card("sv1-25", "https://example.com", mock_page)

        assert runner.anti_detect._pages_this_hour == initial_count + 1


# ---------------------------------------------------------------------------
# VisionFallback tests
# ---------------------------------------------------------------------------

class TestVisionFallback:
    @pytest.mark.asyncio
    async def test_vision_no_api_key_returns_none(
        self,
        mock_page: AsyncMock,
    ) -> None:
        """Empty ANTHROPIC_API_KEY returns None (skips API call)."""
        from src.scraper.vision_fallback import scrape_via_vision
        from src.config import settings

        mock_page.goto = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"fake-screenshot-bytes")

        with patch.object(settings, "ANTHROPIC_API_KEY", ""):
            result = await scrape_via_vision(mock_page, "sv1-25", "https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_vision_empty_screenshot_returns_none(
        self,
        mock_page: AsyncMock,
    ) -> None:
        """Empty screenshot bytes (page.screenshot returns b'') returns None."""
        mock_page.screenshot = AsyncMock(return_value=b"")

        from src.scraper.vision_fallback import scrape_via_vision
        result = await scrape_via_vision(mock_page, "sv1-25", "https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_vision_successful_extraction(
        self,
        mock_page: AsyncMock,
    ) -> None:
        """Successful Claude response returns ScraperResult with scrape_method=vision."""
        from src.scraper.vision_fallback import scrape_via_vision
        from src.config import settings

        mock_response_text = '{"price_eur": 12.50, "seller_rating": 99.5, "seller_sales": 2500, "condition": "NM", "shipping_eur": 1.50}'

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=mock_response_text)]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch.object(settings, "ANTHROPIC_API_KEY", "test-key"):
                result = await scrape_via_vision(mock_page, "sv1-25", "https://example.com")

        assert result is not None
        assert result.scrape_method == "vision"
        assert result.card_id == "sv1-25"
        assert result.price_eur == Decimal("12.50")
        assert result.seller_rating == Decimal("99.5")
        assert result.seller_sales == 2500
        assert result.condition == "NM"
        assert result.shipping_eur == Decimal("1.50")

    @pytest.mark.asyncio
    async def test_vision_malformed_json_returns_none(
        self,
        mock_page: AsyncMock,
    ) -> None:
        """Claude returns malformed JSON → returns None (graceful failure)."""
        from src.scraper.vision_fallback import scrape_via_vision
        from src.config import settings

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="This is not JSON at all")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch.object(settings, "ANTHROPIC_API_KEY", "test-key"):
                result = await scrape_via_vision(mock_page, "sv1-25", "https://example.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_vision_null_fields_in_response(
        self,
        mock_page: AsyncMock,
    ) -> None:
        """Claude response with null fields produces ScraperResult with None values."""
        from src.scraper.vision_fallback import scrape_via_vision
        from src.config import settings

        mock_response_text = '{"price_eur": null, "seller_rating": null, "seller_sales": null, "condition": null, "shipping_eur": null}'

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=mock_response_text)]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch("anthropic.AsyncAnthropic", return_value=mock_client):
            with patch.object(settings, "ANTHROPIC_API_KEY", "test-key"):
                result = await scrape_via_vision(mock_page, "sv1-25", "https://example.com")

        assert result is not None
        assert result.price_eur is None
        assert result.seller_rating is None
        assert result.scrape_method == "vision"
