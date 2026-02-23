# TCG Radar — Project Status (Agent Context Brief)

> **Last updated:** 2026-02-22  
> **Read this file before writing any code.** Also read `CLAUDE.md` and `TCG_RADAR_SPEC.md`.

## What This Project Is

A Pokémon TCG card market intelligence platform that finds cross-market arbitrage opportunities between **Cardmarket** (EU, EUR) and **TCGPlayer** (US, USD). It polls both platforms, runs every card pair through a Rules Engine, scores opportunities, and delivers signals via Telegram.

## Architecture at a Glance

```
Layer 1: Data Ingestion (polling)
  ├── src/pipeline/justtcg.py      → JustTCG (RapidAPI) → market_prices table
  ├── src/pipeline/pokemontcg.py   → pokemontcg.io v2   → card_metadata table
  └── src/pipeline/scheduler.py    → Orchestrates both on independent cadences

Layer 2: Rules Engine (filtering + scoring)
  ├── src/engine/variant_check.py  → Validates card ID equality (Section 4.7)
  ├── src/engine/seller_quality.py → Seller rating ≥97%, sales ≥100 (Section 5)
  ├── src/engine/profit.py         → Net profit calculator with customs (Section 4.1)
  ├── src/engine/velocity.py       → Sales velocity tier classifier (Section 4.2)
  ├── src/engine/maturity.py       → Set age decay multiplier (Section 4.2.2)
  ├── src/engine/rotation.py       → Rotation calendar risk checker (Section 7)
  └── src/engine/headache.py       → Labor-per-dollar tier (Section 4.4)

Layer 3: Utilities
  ├── src/utils/forex.py           → EUR↔USD with 2% pessimistic buffer (Section 4.1)
  └── src/utils/condition_map.py   → Cardmarket→TCGPlayer grade mapping (Section 4.6)

Layer 4: Signal Generation + Delivery
  ├── src/signals/generator.py     → ⚠️ NEEDS REFACTOR (has placeholder stubs)
  └── src/signals/telegram.py      → Telegram bot: single, batch, daily digest

Config + Models:
  ├── src/config.py                → ALL constants, thresholds, enums (pydantic-settings)
  ├── src/models/market_price.py   → MarketPrice ORM model (UUID PK)
  ├── src/models/card_metadata.py  → CardMetadata ORM model
  ├── src/models/user_profile.py   → UserProfile ORM model (Telegram notifications)
  └── src/models/base.py           → SQLAlchemy async base

Entry Point:
  └── src/main.py                  → structlog config, DB init, scheduler start
```

## What's Done (Sprints 1-3)

| Component | File | Lines | Status |
|-----------|------|-------|--------|
| Config | `src/config.py` | ~200 | ✅ All constants, enums, pydantic-settings |
| DB Models | `src/models/*.py` | ~300 | ✅ MarketPrice, CardMetadata, UserProfile |
| Migration | `alembic/versions/001_initial_schema.py` | 124 | ✅ All 3 tables |
| JustTCG Client | `src/pipeline/justtcg.py` | 314 | ✅ Async, retry, Pydantic, upsert |
| pokemontcg Client | `src/pipeline/pokemontcg.py` | 416 | ✅ Auto-pagination, upsert |
| Scheduler | `src/pipeline/scheduler.py` | 259 | ✅ Independent cadences, social spike |
| Main | `src/main.py` | 178 | ✅ structlog, DB health check |
| Forex | `src/utils/forex.py` | ~80 | ✅ Pessimistic 2% buffer |
| Condition Map | `src/utils/condition_map.py` | ~100 | ✅ All grades + penalties |
| Variant Check | `src/engine/variant_check.py` | 57 | ✅ |
| Seller Quality | `src/engine/seller_quality.py` | 53 | ✅ |
| Net Profit | `src/engine/profit.py` | 175 | ✅ 3 customs regimes, forwarder |
| Velocity | `src/engine/velocity.py` | 65 | ✅ |
| Maturity Decay | `src/engine/maturity.py` | 136 | ✅ + reprint rumor penalty |
| Rotation Risk | `src/engine/rotation.py` | 217 | ✅ ROTATION_CALENDAR lookup |
| Headache Score | `src/engine/headache.py` | 48 | ✅ |
| Telegram | `src/signals/telegram.py` | 296 | ✅ MarkdownV2, rate limiting |
| Signal Generator | `src/signals/generator.py` | 466 | ⚠️ Works but uses placeholder stubs |

## What's Next — S3-D: Refactor Signal Generator

`src/signals/generator.py` needs to be **rewritten** to:
1. Call the REAL engine modules instead of inline placeholder stubs
2. Accept `TelegramNotifier` in constructor and use it in `run_and_notify()`
3. Stay under 300 lines (currently 466)
4. Use actual DB card data (condition, seller info, regulation mark) instead of hardcoded defaults

## Project Conventions

- **Python 3.11+**, type hints on everything
- **Decimal** for all financial math — never float
- **structlog** for logging (JSON format)
- **No magic numbers** — all constants in `src/config.py`
- **async/await** for all I/O
- **< 300 lines** per file
- Tests in `tests/` with `pytest` + `pytest-asyncio`
- Import pattern: `from src.config import settings`

## Key Config Values (from `src/config.py`)

```python
TCGPLAYER_FEE_RATE = Decimal("0.1075")   # 10.75%
US_DE_MINIMIS_USD  = Decimal("800.00")
EU_VAT_RATE        = Decimal("0.21")     # 21%
UK_VAT_RATE        = Decimal("0.20")     # 20%
DEFAULT_FOREX_BUFFER = Decimal("0.02")   # 2% pessimistic
MIN_SELLER_RATING  = Decimal("97.0")
MIN_SELLER_SALES   = 100
SHIPPING_COST_USD  = Decimal("4.50")
VELOCITY_TIER_1_FLOOR = Decimal("5.0")
VELOCITY_TIER_2_FLOOR = Decimal("0.5")
```

## File Tree (source only)

```
src/
├── config.py
├── main.py
├── engine/
│   ├── __init__.py
│   ├── headache.py
│   ├── maturity.py
│   ├── profit.py
│   ├── rotation.py
│   ├── seller_quality.py
│   ├── variant_check.py
│   └── velocity.py
├── models/
│   ├── __init__.py
│   ├── base.py
│   ├── card_metadata.py
│   ├── market_price.py
│   └── user_profile.py
├── pipeline/
│   ├── __init__.py
│   ├── justtcg.pyOk goodco
│   ├── pokemontcg.py
│   └── scheduler.py
├── signals/
│   ├── __init__.py
│   ├── generator.py
│   └── telegram.py
└── utils/
    ├── __init__.py
    ├── condition_map.py
    └── forex.py
```
