"""
TCG Radar â€” Configuration & Constants

All constants extracted from TCG_RADAR_SPEC.md. Every threshold, fee rate,
and magic number lives here. No hardcoded values in business logic.

Usage:
    from src.config import settings
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CustomsRegime(str, Enum):
    """Section 4.1.2 â€” Date-triggered config flag for EU customs rules."""
    DE_MINIMIS = "de_minimis"
    IOSS_EU = "ioss_eu"
    UK_LOW_VALUE = "uk_low_value"
    PRE_JULY_2026 = "pre_july_2026"
    POST_JULY_2026 = "post_july_2026"


class VelocityTier(str, Enum):
    """Section 4.2 â€” Velocity Score classification."""
    LIQUID_GOLD = "liquid_gold"       # V_s > 1.5
    STANDARD_FLIP = "standard_flip"   # 0.5 < V_s < 1.5
    BAGHOLDER_RISK = "bagholder_risk" # V_s < 0.5


class HeadacheTier(int, Enum):
    """Section 4.4 â€” Labor-to-Loot ratio tiers."""
    TIER_1 = 1  # H > 15 (one card, easy money)
    TIER_2 = 2  # 5 < H < 15 (a few cards, decent)
    TIER_3 = 3  # H < 5 (bulk deal, high labor)


class SignalType(str, Enum):
    """Signal classification types."""
    ARBITRAGE = "arbitrage"
    EVENT_DRIVEN = "event_driven"
    BUNDLE = "bundle"
    INVESTMENT = "investment"


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    Central configuration for TCG Radar.

    Loads from environment variables with fallback defaults.
    All constants reference their spec section.
    """

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # -----------------------------------------------------------------------
    # API Keys
    # -----------------------------------------------------------------------
    JUSTTCG_API_KEY: str = ""
    POKEMONTCG_API_KEY: str = ""
    POKETRACE_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_CHANNEL_ID: int = 0
    TWITTER_BEARER_TOKEN: str = ""          # Phase 3 — Twitter/X API v2 Bearer Token

    # eBay Browse API (Section 5 — US price discovery)
    EBAY_APP_ID: str = ""                   # eBay Developer App ID (Client ID)
    EBAY_CERT_ID: str = ""                  # eBay Developer Cert ID (Client Secret)
    EBAY_OAUTH_URL: str = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_BROWSE_URL: str = "https://api.ebay.com/buy/browse/v1"

    # Discord social listener (Layer 3.5 — Section 3.5)
    DISCORD_MONITOR_CHANNEL_IDS: str = ""   # Comma-separated channel IDs to monitor

    # -----------------------------------------------------------------------
    # Phase 3 — Live Forex API (ExchangeRate-API)
    # -----------------------------------------------------------------------
    EXCHANGERATE_API_KEY: str = ""          # API key from exchangerate-api.com
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    FOREX_CACHE_TTL_SECONDS: int = 900      # 15-minute cache to avoid hammering API

    # -----------------------------------------------------------------------
    # Phase 3 — Vision Fallback (Claude Vision API)
    # -----------------------------------------------------------------------
    OPENROUTER_API_KEY: str = ""            # OpenRouter API key for vision fallback
    VISION_MODEL_ID: str = "claude-opus-4-6"  # Model for screenshot extraction

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/tcgradar"

    # -----------------------------------------------------------------------
    # Feature Flags
    # -----------------------------------------------------------------------
    CUSTOMS_REGIME: CustomsRegime = CustomsRegime.PRE_JULY_2026
    ENABLE_LAYER_3_SCRAPING: bool = False
    ENABLE_LAYER_35_SOCIAL: bool = False
    ENABLE_BUNDLE_LOGIC: bool = True

    # -----------------------------------------------------------------------
    # Section 4.1.1 â€” TCGPlayer Seller Fee (Feb 10, 2026 Update)
    # F_selling = min(P_target Ã— 0.1075, 75) + 0.30
    # -----------------------------------------------------------------------
    TCGPLAYER_FEE_RATE: Decimal = Decimal("0.1075")
    TCGPLAYER_FEE_CAP: Decimal = Decimal("75.00")
    TCGPLAYER_FIXED_FEE: Decimal = Decimal("0.30")

    # eBay: F_selling = P_target Ã— 0.1325 (no cap change)
    EBAY_FEE_RATE: Decimal = Decimal("0.1325")

    # Cardmarket professional: F_selling â‰ˆ P_target Ã— 0.05
    CARDMARKET_PRO_FEE_RATE: Decimal = Decimal("0.05")

    # -----------------------------------------------------------------------
    # Section 4.1.2 â€” EU Customs "July 1st Cliff"
    # -----------------------------------------------------------------------
    US_DE_MINIMIS_USD: Decimal = Decimal("800.00")
    US_CUSTOMS_STANDARD_RATE: Decimal = Decimal("0.025")
    EU_VAT_RATE: Decimal = Decimal("0.21")
    UK_VAT_RATE: Decimal = Decimal("0.20")
    UK_LOW_VALUE_THRESHOLD_USD: Decimal = Decimal("135.00")
    SHIPPING_COST_USD: Decimal = Decimal("15.00")
    EU_CUSTOMS_FLAT_DUTY_EUR: Decimal = Decimal("3.00")       # â‚¬3 per item post-July 2026
    EU_CUSTOMS_CLIFF_DATE: date = date(2026, 7, 1)
    EU_SINGLE_CARD_SUPPRESS_THRESHOLD_EUR: Decimal = Decimal("20.00")  # Suppress sub-â‚¬20 singles for EU
    EU_MIN_SDS_POST_CUSTOMS: int = 3                          # Minimum SDS for EU users post-July

    # -----------------------------------------------------------------------
    # Section 4.1.2 â€” Forwarder Fee Constants
    # Pessimistic midpoint of 2026 market rates (user-configurable in profile)
    # -----------------------------------------------------------------------
    DEFAULT_FORWARDER_RECEIVING_FEE: Decimal = Decimal("3.50")
    DEFAULT_FORWARDER_CONSOLIDATION_FEE: Decimal = Decimal("7.50")
    DEFAULT_INSURANCE_RATE: Decimal = Decimal("0.025")        # 2.5% of declared value
    INSURANCE_THRESHOLD: Decimal = Decimal("30.00")            # Apply insurance when P_buy > $30

    # -----------------------------------------------------------------------
    # Section 4.1 â€” Signal Suppression
    # If P_real < 0.10 Ã— P_buy_effective, the signal is noise
    # -----------------------------------------------------------------------
    MIN_PROFIT_RATIO: Decimal = Decimal("0.10")

    # -----------------------------------------------------------------------
    # Section 4.2 â€” Velocity Score Thresholds
    # -----------------------------------------------------------------------
    VELOCITY_TIER_1_FLOOR: Decimal = Decimal("1.5")
    VELOCITY_TIER_2_FLOOR: Decimal = Decimal("0.5")
    VELOCITY_LIQUID_GOLD: Decimal = Decimal("1.5")
    VELOCITY_STANDARD_FLOOR: Decimal = Decimal("0.5")

    # -----------------------------------------------------------------------
    # Section 4.2.1 â€” Staleness Penalty (Ghost Listings)
    # Applied as multiplier on V_s
    # -----------------------------------------------------------------------
    STALENESS_FRESH_HOURS: int = 1
    STALENESS_PENALTY_1H: Decimal = Decimal("1.0")    # < 1 hour
    STALENESS_PENALTY_2H: Decimal = Decimal("0.95")   # 1-2 hours
    STALENESS_PENALTY_4H: Decimal = Decimal("0.85")   # 2-4 hours
    STALENESS_PENALTY_OLD: Decimal = Decimal("0.70")   # > 4 hours
    STALENESS_SCRAPE_TRIGGER_HOURS: int = 4             # Auto-trigger Layer 3 scrape

    # -----------------------------------------------------------------------
    # Section 4.2.2 â€” Maturity Penalty (Hype Decay)
    # Applied as multiplier on V_s based on set age
    # -----------------------------------------------------------------------
    MATURITY_FRESH_DAYS: int = 30
    MATURITY_DECAY_30D: Decimal = Decimal("1.0")      # < 30 days
    MATURITY_DECAY_60D: Decimal = Decimal("0.9")      # 30-60 days
    MATURITY_DECAY_90D: Decimal = Decimal("0.8")      # 60-90 days
    MATURITY_DECAY_OLD: Decimal = Decimal("0.7")      # > 90 days
    MATURITY_REPRINT_RUMOR_PENALTY: Decimal = Decimal("0.8")  # Additional Ã— 0.8

    # -----------------------------------------------------------------------
    # Section 4.3 â€” Trend-Adjusted Velocity (Falling Knife Filter)
    # -----------------------------------------------------------------------
    FALLING_KNIFE_THRESHOLD: Decimal = Decimal("-0.10")  # -10%/day

    # -----------------------------------------------------------------------
    # Section 4.4 â€” Headache Score Thresholds (Labor-to-Loot)
    # -----------------------------------------------------------------------
    HEADACHE_TIER_1_FLOOR: Decimal = Decimal("15.00")   # H > 15 â†’ Tier 1
    HEADACHE_TIER_2_FLOOR: Decimal = Decimal("5.00")    # 5 < H < 15 â†’ Tier 2
    # H < 5 â†’ Tier 3

    # -----------------------------------------------------------------------
    # Section 4.5 â€” Seller Density Score (Bundle Logic)
    # -----------------------------------------------------------------------
    SDS_BUNDLE_ALERT: int = 5       # SDS >= 5 â†’ "Bundle Alert"
    SDS_PARTIAL_MIN: int = 2        # SDS 2-4 â†’ "Partial bundle"
    SDS_SINGLE: int = 1             # SDS = 1 â†’ full single-card shipping
    BUNDLE_SINGLE_CARD_THRESHOLD: Decimal = Decimal("25.00")  # Sub-$25 cards need bundle check

    # -----------------------------------------------------------------------
    # Section 4.6 â€” Condition Mapping Penalties
    # Cardmarket â†’ TCGPlayer pessimistic mapping
    # -----------------------------------------------------------------------
    CONDITION_PENALTY_EXCELLENT: Decimal = Decimal("0.85")   # -15%
    CONDITION_PENALTY_GOOD: Decimal = Decimal("0.75")        # -25%
    CONDITION_PENALTY_LIGHT_PLAYED: Decimal = Decimal("0.75")  # -25%
    CONDITION_PENALTY_PLAYED: Decimal = Decimal("0.60")      # -40%
    # Poor/Damaged â†’ signal suppressed (no penalty, just don't generate)

    # -----------------------------------------------------------------------
    # Section 5 â€” Seller Quality Floor
    # -----------------------------------------------------------------------
    MIN_SELLER_RATING: Decimal = Decimal("97.0")
    MIN_SELLER_SALES: int = 100

    # -----------------------------------------------------------------------
    # Section 6 â€” Scraping Configuration
    # -----------------------------------------------------------------------
    PROXY_URL: str = ""
    SCRAPE_MAX_PAGES_PER_HOUR: int = 30
    SCRAPE_DELAY_MIN_SECONDS: int = 2
    SCRAPE_DELAY_MAX_SECONDS: int = 8

    # -----------------------------------------------------------------------
    # Section 7 â€” Rotation Calendar
    # Hard-coded, updated manually when PokÃ©mon announces changes
    # -----------------------------------------------------------------------
    ROTATION_CALENDAR: dict = {
        "G": {
            "rotation_date": "2026-04-10",
            "status": "DEATH_SPIRAL",
            "suppress_window_days": 42,   # 6 weeks prior
            "spread_override_threshold": Decimal("0.40"),  # 40% spread overrides suppression
        },
        "H": {
            "rotation_date": None,
            "status": "STANDARD_LEGAL",
            "suppress_window_days": 0,
            "spread_override_threshold": None,
        },
    }
    CURRENT_REGULATION_MARK: str = "H"

    # -----------------------------------------------------------------------
    # Section 14 â€” Signal Cascade Configuration
    # -----------------------------------------------------------------------
    CASCADE_COOLDOWN_SECONDS: int = 10
    CASCADE_MAX_LIMIT: int = 5
    CASCADE_POLL_INTERVAL_SECONDS: int = 5

    # -----------------------------------------------------------------------
    # Forex â€” Section 4.1
    # -----------------------------------------------------------------------
    DEFAULT_FOREX_BUFFER: Decimal = Decimal("0.02")  # 2% buffer on EUR/USD
    EUR_USD_RATE: Decimal = Decimal("1.08")          # Spot EUR/USD rate (overridable via env)

    # -----------------------------------------------------------------------
    # Scheduler â€” Polling Cadence
    # -----------------------------------------------------------------------
    JUSTTCG_POLL_INTERVAL_HOURS: int = 6
    POKEMONTCG_REFRESH_INTERVAL_HOURS: int = 24
    SOCIAL_SPIKE_POLL_INTERVAL_MINUTES: int = 30
    SOCIAL_SPIKE_REVERT_HOURS: int = 4
    SOCIAL_SPIKE_MULTIPLIER: float = 5.0
    SIGNAL_SCAN_INTERVAL_MINUTES: int = 30

    # -----------------------------------------------------------------------
    # PokeTrace API Configuration
    # -----------------------------------------------------------------------
    POKETRACE_BASE_URL: str = "https://api.poketrace.com/v1"
    POKETRACE_POLL_INTERVAL_HOURS: int = 12

    # eBay polling cadence (Section 5)
    EBAY_POLL_INTERVAL_HOURS: int = 12

    # -----------------------------------------------------------------------
    # Limitless TCG Configuration
    # -----------------------------------------------------------------------
    LIMITLESS_BASE_URL: str = "https://play.limitlesstcg.com/api"
    LIMITLESS_POLL_INTERVAL_MINUTES: int = 60

    # -----------------------------------------------------------------------
    # User Profile Defaults
    # -----------------------------------------------------------------------
    DEFAULT_MIN_PROFIT_THRESHOLD: Decimal = Decimal("5.00")
    DEFAULT_MIN_HEADACHE_SCORE: int = 5
    DEFAULT_CURRENCY: str = "USD"


# Singleton instance
settings = Settings()
