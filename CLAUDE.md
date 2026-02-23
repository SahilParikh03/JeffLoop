# CLAUDE.md — TCG Radar Engineering Protocol

## Identity

You are the lead engineer on **TCG Radar**, a Pokémon card market intelligence SaaS. You write production code, not prototypes. Every line ships.

Read `TCG_RADAR_SPEC.md` before writing any code. It is the single source of truth. If the spec doesn't cover something, ask — don't guess.

---

## Model Routing

**Sonnet 4.5** — Default for all code generation, architecture decisions, debugging, and complex logic (fee calculations, rules engine, database queries).

**Opus 4.6** — Escalate ONLY for: security-critical code (RLS policies, auth, API key handling), architectural decisions that affect multiple modules, and resolving ambiguity in the spec.

**Haiku 4.5** — Use for: file renaming, import sorting, docstring generation, simple CRUD boilerplate, config file creation, commit message drafting, and any task where the output is <20 lines of deterministic code.

**Rule:** If you're unsure which model, use Sonnet. Never use Opus for boilerplate. Never use Haiku for business logic.

---

## Agent Spawning

Spawn sub-agents for parallelizable work. Keep the orchestrator agent lean — it delegates, reviews, and merges. It does not write implementation code itself.

### Agent Roles

| Agent | Scope | Model |
|-------|-------|-------|
| `data-pipeline` | JustTCG integration, pokemontcg.io integration, PokeTrace integration, DB writes to `market_prices` | Sonnet |
| `rules-engine` | Layer 2 logic: Variant ID check → Velocity Score → Trend filter → Rotation calendar → Seller quality → Effective Buy Price → Fee calc → Headache Score → Bundle Logic | Sonnet |
| `scraper` | Playwright network interception, targeted Cardmarket checks, anti-detection, fallback chain | Sonnet |
| `signals` | Signal generation, exclusivity rotation, cascade with cooldown, Telegram/Discord delivery | Sonnet |
| `db-admin` | Schema migrations, RLS policies, audit log, index optimization | Sonnet (escalate to Opus for RLS) |
| `tests` | Unit tests, integration tests, mock API responses | Sonnet |
| `config` | Environment variables, feature flags, `CUSTOMS_REGIME`, forwarder constants | Haiku |

**Do not spawn more than 3 agents simultaneously.** Each agent works on one module, writes tests for that module, then reports done.

---

## Project Structure

```
tcg-radar/
├── CLAUDE.md                    # This file
├── TCG_RADAR_SPEC.md            # Product spec (read-only reference)
├── .env.example                 # Template for secrets
├── docker-compose.yml           # Postgres + app containers
├── alembic/                     # DB migrations
│   └── versions/
├── src/
│   ├── __init__.py
│   ├── main.py                  # Entrypoint, scheduler orchestration
│   ├── config.py                # All constants, feature flags, regime switches
│   ├── models/
│   │   ├── __init__.py
│   │   ├── market_price.py      # SQLAlchemy model for market_prices
│   │   ├── signal.py            # SQLAlchemy model for signals (tenant-isolated)
│   │   ├── signal_audit.py      # SQLAlchemy model for signal_audit
│   │   ├── user_profile.py      # Seller level, country, fee config, forwarder prefs
│   │   └── card_metadata.py     # pokemontcg.io data, regulation marks, variant IDs
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── justtcg.py           # JustTCG API client
│   │   ├── pokemontcg.py        # pokemontcg.io API client
│   │   ├── poketrace.py         # PokeTrace API client (Phase 2)
│   │   └── scheduler.py         # Poll cadence management, Layer 3.5 overrides
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── variant_check.py     # Section 4.7 — FIRST filter, always
│   │   ├── velocity.py          # V_s with Staleness + Maturity penalties
│   │   ├── trend.py             # Falling knife detection
│   │   ├── rotation.py          # Calendar overlay, regulation mark parser
│   │   ├── seller_quality.py    # Rating floor, sale count minimum
│   │   ├── effective_price.py   # Listing + shipping + condition mapping
│   │   ├── fees.py              # Tiered F_selling, customs, forwarder, insurance
│   │   ├── headache.py          # Labor-to-Loot ratio
│   │   ├── bundle.py            # Seller Density Score, shipping amortization
│   │   └── profit.py            # P_real master calculation (calls all above)
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── network_intercept.py # page.route interception (PRIMARY method)
│   │   ├── css_fallback.py      # Deep selectors (BACKUP only)
│   │   ├── vision_fallback.py   # Screenshot + AI (EMERGENCY only)
│   │   ├── anti_detect.py       # Fingerprint rotation, delays, proxy mgmt
│   │   └── runner.py            # Orchestrates scrape jobs from Layer 3 triggers
│   ├── events/
│   │   ├── __init__.py
│   │   ├── limitless.py         # Tournament result parser
│   │   ├── social_listener.py   # Layer 3.5 — keyword frequency on Twitter/Reddit/Discord
│   │   ├── synergy.py           # Co-occurrence matrix, support card detection
│   │   └── triggers.py          # Event → targeted scrape trigger logic
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── generator.py         # Composite score, signal creation
│   │   ├── rotation.py          # User priority rotation, exclusivity windows
│   │   ├── cascade.py           # Expiry + 10s cooldown buffer logic
│   │   ├── delivery.py          # Telegram bot, Discord bot (Phase 2)
│   │   └── deep_link.py         # Cardmarket/TCGPlayer URL construction
│   └── utils/
│       ├── __init__.py
│       ├── forex.py             # EUR/USD with 2% buffer
│       └── condition_map.py     # Cardmarket → TCGPlayer grade translation
├── tests/
│   ├── __init__.py
│   ├── test_variant_check.py
│   ├── test_velocity.py
│   ├── test_fees.py
│   ├── test_profit.py
│   ├── test_bundle.py
│   ├── test_cascade.py
│   ├── test_condition_map.py
│   └── fixtures/
│       ├── mock_justtcg.json
│       ├── mock_pokemontcg.json
│       └── mock_cardmarket_response.json
└── scripts/
    ├── seed_rotation_calendar.py
    └── seed_decklist_history.py
```

**Rule:** One module = one responsibility. If a file exceeds 300 lines, split it. No god files.

---

## Coding Standards

### Python

- Python 3.11+. Type hints on every function signature. No `Any` types except in test fixtures.
- `async/await` for all I/O (API calls, DB queries, scraping). Use `asyncio` + `httpx` for HTTP. Use `asyncpg` or `SQLAlchemy async` for Postgres.
- Pydantic v2 for all data models that cross module boundaries (API responses, signal payloads, user profiles).
- No print statements. Use `structlog` for structured logging. Every log line includes `card_id`, `source`, and `timestamp` at minimum.
- Constants live in `config.py`. No magic numbers in business logic. Every threshold from the spec (97% seller rating, 0.5 velocity floor, 15% LP penalty, etc.) must be a named constant.

### Database

- Alembic for all migrations. No raw DDL outside migrations.
- RLS policies are defined in migrations, not application code. The app connects as a scoped role, never as superuser.
- Every query that touches `signals` must filter by `tenant_id`. No exceptions. If you write a query without tenant scoping, it's a bug.
- Indexes: `market_prices(card_id, source)`, `signals(tenant_id, created_at)`, `signal_audit(signal_id)`.

### Testing

- Every module in `engine/` must have corresponding tests before it's considered done.
- Tests use mock API responses from `tests/fixtures/`. Never call live APIs in tests.
- Test the edge cases from the spec explicitly:
  - Variant mismatch (Section 4.7)
  - Condition mapping penalties (Section 4.6)
  - Customs regime switch (pre/post July 2026)
  - Cascade cooldown buffer (10-second gap)
  - Maturity decay on sets >60 days old
  - Insurance deadzone ($50-$150 cards)
  - Ghost listing staleness penalty
  - Bundle vs single-card shipping suppression

---

## Execution Order

Build in this order. Do not skip ahead.

### Sprint 1 (Weeks 1-2): Data Foundation

1. `config.py` — all constants from spec
2. Docker + Postgres + Alembic setup
3. DB schema: `market_prices`, `card_metadata`, `user_profiles` tables
4. `pipeline/justtcg.py` — fetch and store prices
5. `pipeline/pokemontcg.py` — fetch card metadata, regulation marks, variant IDs
6. `pipeline/scheduler.py` — basic polling loop
7. Tests for pipeline modules

### Sprint 2 (Weeks 3-4): Rules Engine

Build in the EXACT order from Layer 2 (this is the filter chain — order matters):

1. `engine/variant_check.py` — FIRST. Always.
2. `engine/velocity.py` — with staleness and maturity penalties
3. `engine/trend.py` — falling knife filter
4. `engine/rotation.py` — calendar + regulation mark parser
5. `engine/seller_quality.py` — rating and sale count floor
6. `engine/effective_price.py` — listing + shipping
7. `engine/fees.py` — tiered TCGPlayer, eBay, Cardmarket, customs, forwarder, insurance
8. `engine/headache.py` — Labor-to-Loot
9. `engine/bundle.py` — Seller Density Score
10. `engine/profit.py` — master `P_real` calculation that chains all above
11. `utils/condition_map.py` — grade translation table
12. `utils/forex.py` — EUR/USD with buffer
13. Tests for every engine module

### Sprint 3 (Weeks 5-6): Signals + Delivery

1. DB schema: `signals`, `signal_audit` tables with RLS
2. `signals/generator.py` — composite scoring, signal creation
3. `signals/rotation.py` — user priority, exclusivity windows
4. `signals/cascade.py` — expiry + cooldown buffer
5. `signals/deep_link.py` — URL construction
6. `signals/delivery.py` — Telegram bot integration
7. Integration test: full pipeline → rules engine → signal → Telegram delivery
8. Manual validation against live market data

---

## Things That Will Bite You

Read these before writing code. They come from extensive design review.

1. **Variant check runs FIRST.** If you put it after the fee calculation, you'll generate false spreads on promo vs standard cards. Section 4.7 exists for a reason.

2. **`F_selling` is not a flat percentage.** It's `min(P_target × 0.1075, 75) + 0.30` for TCGPlayer. If you hardcode 10.75%, you'll be wrong on every card above $698.

3. **Condition mapping is pessimistic.** Cardmarket "Excellent" = TCGPlayer "Lightly Played" with a -15% penalty. If you map EXC → NM, every signal is a false positive.

4. **Shipping cannot be ignored on sub-$25 cards.** A $10 card with $15 shipping is not arbitrage. The Bundle Logic (Section 4.5) exists to solve this. If `SDS = 1` and the card is under $25, check if `P_real` survives full single-card shipping. If not, suppress.

5. **The cascade has a 10-second cooldown.** Not 0 seconds. Not 1 second. Ten seconds. Without this, two users get the same signal due to Telegram delivery latency.

6. **`CUSTOMS_REGIME` is a date-triggered config flag.** Before July 1, 2026: de minimis rules. After: €3 flat duty per item. This must be a config switch, not a code branch buried in the fee calculator.

7. **Network interception is the PRIMARY scraping method.** `page.route`, not CSS selectors. CSS is backup. Screenshot+AI is emergency. If you write the scraper starting with CSS selectors, you'll rewrite it within a week.

8. **Never pass DOM content or seller descriptions to any AI/LLM call.** CVE-2026-25253. Structured data or screenshots only. This is a security boundary, not a preference.

9. **Every signal gets an audit row.** Full snapshot of what the system saw: raw prices, fee breakdown, user profile at time of calculation. If you skip this, there's no way to debug false positives or resolve user disputes.

10. **The `signals` table has RLS. Every query needs `tenant_id`.** If you write `SELECT * FROM signals` without a tenant filter, it's a production security bug.

---

## What Not To Build

- No web dashboard in Phase 1. Telegram bot is the delivery layer.
- No mobile app. Not now.
- No AI-powered "chat with your portfolio." Signals are structured data, not conversations.
- No multi-TCG support yet. Pokémon only until the core loop is validated.
- No user-facing API until Phase 3. Internal only.
- No payment/billing integration in Phase 1. Manual onboarding for beta users.

---

## Environment Variables

```
# APIs
JUSTTCG_API_KEY=
POKEMONTCG_API_KEY=
POKETRACE_API_KEY=
TELEGRAM_BOT_TOKEN=

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/tcgradar

# Feature Flags
CUSTOMS_REGIME=pre_july_2026
ENABLE_LAYER_3_SCRAPING=false
ENABLE_LAYER_35_SOCIAL=false
ENABLE_BUNDLE_LOGIC=true

# Scraping (when enabled)
PROXY_URL=
SCRAPE_MAX_PAGES_PER_HOUR=30
SCRAPE_DELAY_MIN_SECONDS=2
SCRAPE_DELAY_MAX_SECONDS=8

# Defaults (override in user profiles)
DEFAULT_FORWARDER_RECEIVING_FEE=3.50
DEFAULT_FORWARDER_CONSOLIDATION_FEE=7.50
DEFAULT_INSURANCE_RATE=0.025
DEFAULT_FOREX_BUFFER=0.02
DEFAULT_MIN_SELLER_RATING=97.0
DEFAULT_MIN_SELLER_SALES=100
DEFAULT_MIN_PROFIT_THRESHOLD=5.00
DEFAULT_MIN_HEADACHE_SCORE=5
```

---

## Commit Protocol

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`
- One module per PR. No mega-commits.
- Every PR must include tests. No exceptions.
- Commit messages drafted by Haiku. Code reviewed by Sonnet.
