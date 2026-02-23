# DEPLOYMENT.md — TCG Radar Deployment Guide

## Prerequisites

Before deploying TCG Radar, ensure your environment meets these requirements:

### System Requirements
- **Python 3.11+** — Required for async/await, type hints, and Pydantic v2 compatibility
- **Docker and Docker Compose** — For containerized PostgreSQL and app deployment
- **PostgreSQL 15+** — Via Docker Compose (included) or standalone instance
- **Playwright Chromium** — Required if Layer 3 scraping is enabled (`ENABLE_LAYER_3_SCRAPING=true`)

### API Keys and Credentials
Gather these before starting:
- **JustTCG API Key** — Required. Marketplace data polling.
- **pokemontcg.io API Key** — Required. Card metadata and regulation marks.
- **PokeTrace API Key** — Optional (Phase 2+). Velocity data enhancement. Skip if unavailable; system falls back to calculated velocity.
- **Telegram Bot Token** — Required for signal delivery. Create via @BotFather on Telegram.
- **Discord Bot Token** — Optional (Phase 2+). Discord signal delivery. Skip if Discord delivery not needed.
- **Twitter Bearer Token** — Optional (Phase 3+). Social spike detection. Skip if `ENABLE_LAYER_35_SOCIAL=false`.
- **ExchangeRate-API Key** — Optional. Live EUR/USD rates. Skip if `EUR_USD_RATE` fallback is acceptable.
- **Anthropic API Key** — Optional (Phase 3+). Vision fallback scraping. Emergency use only.

---

## Quick Start

### 1. Clone and Set Up Environment

```bash
# Clone the repository (if not already done)
git clone <tcg-radar-repo>
cd tcg-radar

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
# Use your preferred editor: nano, vim, or VS Code
nano .env
```

At minimum, set:
- `JUSTTCG_API_KEY`
- `POKEMONTCG_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL` (or use the default for Docker Compose)

### 2. Start the Database

```bash
# Start PostgreSQL container via Docker Compose
docker-compose up -d

# Verify the database is running
docker-compose logs postgres
```

The default `docker-compose.yml` creates a PostgreSQL 15 container with:
- Host: `localhost`
- Port: `5432`
- Database: `tcgradar`
- User: `tcgradar`
- Password: (set via POSTGRES_PASSWORD in compose file)

### 3. Run Database Migrations

```bash
# Apply all pending migrations to bring the database schema current
alembic upgrade head

# Verify the migration was successful
alembic current
```

This creates all required tables:
- `market_prices` — JustTCG/Cardmarket price data
- `card_metadata` — Card IDs, regulation marks, variant info from pokemontcg.io
- `user_profiles` — Tenant configuration, fee overrides, notification settings
- `price_history` — Append-only price history for trend calculation
- `signals` — Generated signals with RLS tenant isolation
- `signal_audit` — Audit trail of signal calculations
- `synergy_cooccurrence` — Support card matrices from tournament decklists
- `users` — Core user identity table (added in migration 006)

### 4. Install Python Dependencies

```bash
# Install the project in editable mode with dev dependencies
pip install -e ".[dev]"
```

This installs:
- `httpx` — HTTP client for async API calls
- `asyncpg` or `sqlalchemy` — Database drivers
- `pydantic` — Data validation
- `structlog` — Structured logging
- `playwright` — Web automation (if Layer 3 enabled)
- `pytest` — Testing framework

### 5. Install Playwright Browsers (if needed)

Only required if `ENABLE_LAYER_3_SCRAPING=true`:

```bash
# Install Chromium for Cardmarket scraping
playwright install chromium
```

This downloads the Chromium browser binary. On first run, may take 2-3 minutes and ~300 MB disk space.

### 6. Run Tests to Verify Setup

```bash
# Run the full test suite
pytest tests/ -v

# Expected output: 400+ tests passing
# If any fail, check:
# - DATABASE_URL is correct and database is running
# - All required API key env vars are set (for mock tests, this is less critical)
# - Python version is 3.11+
```

### 7. Create the First User

The scheduler's signal scan queries `user_profiles` for delivery targets. If the table is empty, no signals will ever fire. Create at least one subscriber before starting the scheduler.

```bash
# Create a subscriber (replace values with your Telegram chat ID and country)
python scripts/add_user.py --telegram-chat-id 123456789 --country US --tier free

# With Discord delivery enabled:
python scripts/add_user.py --telegram-chat-id 123456789 --country US --tier trader --discord-channel-id 987654321
```

To find your Telegram chat ID: message @userinfobot on Telegram; it replies with your numeric chat ID.

**Important:** Migration 006 adds a FK constraint `signals.tenant_id → users.id`. Every user_profile must have a matching users row. The `add_user.py` script handles this correctly — do not insert into user_profiles directly via SQL without also inserting into users first.

### 8. Start the Scheduler

```bash
# Run the main scheduler loop
python -m src.main

# Expected output:
# - Logs for JustTCG polling (every 6 hours)
# - Logs for signal generation (every 30 minutes)
# - Logs for Telegram delivery (as signals fire)
```

The scheduler will:
1. Poll JustTCG for price updates every 6 hours
2. Fetch card metadata from pokemontcg.io every 24 hours
3. Run the rules engine (signal scan) every 30 minutes
4. Deliver signals to Telegram as they're generated
5. Maintain price_history append-only table for trend analysis

---

## Environment Variables Reference

All variables are read from `.env` at startup. See `.env.example` for a template.

### API Keys

**JUSTTCG_API_KEY** (required)
- JustTCG marketplace API key for price data polling
- Obtain from JustTCG admin portal
- No default; system will not function without this

**POKEMONTCG_API_KEY** (required)
- pokemontcg.io API key for card metadata and regulation marks
- Obtain from pokemontcg.io account settings
- No default; system will not function without this

**POKETRACE_API_KEY** (optional, Phase 2+)
- PokeTrace API key for velocity data (sales velocity enhancement)
- Obtain from PokeTrace dashboard
- If empty: system uses calculated velocity from price_history (fallback to 1.0 if insufficient history)

**TELEGRAM_BOT_TOKEN** (required)
- Telegram bot token from @BotFather
- Format: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
- No default; system cannot deliver signals without this

**DISCORD_BOT_TOKEN** (optional, Phase 2+)
- Discord bot token from Discord Developer Portal
- If empty: Discord delivery is skipped; system falls back to Telegram only
- Required if Discord delivery is enabled in user profiles

**DISCORD_CHANNEL_ID** (optional, Phase 2+)
- Discord channel ID for signal delivery
- Format: numeric snowflake (e.g., `1234567890`)
- If empty: Discord signals are dropped (logged as warning)

**TWITTER_BEARER_TOKEN** (optional, Phase 3+)
- Twitter/X API v2 Bearer Token for social spike detection
- Obtain from Twitter Developer Portal
- If empty and `ENABLE_LAYER_35_SOCIAL=true`: social spike detection is skipped with warning

**EXCHANGERATE_API_KEY** (optional, Phase 3+)
- exchangerate-api.com key for live EUR/USD rates
- If empty: `get_current_forex_rate()` returns static `EUR_USD_RATE` config value
- No penalty for being empty; fallback is safe for production

**ANTHROPIC_API_KEY** (optional, Phase 3+)
- Anthropic API key for vision fallback scraping
- Used only if Layer 3 scraping fails CSS extraction and network interception
- Leave empty to skip vision fallback; system will log a failure and move on

### Database

**DATABASE_URL** (required)
- PostgreSQL connection string using asyncpg driver
- Format: `postgresql+asyncpg://user:password@host:port/dbname`
- Example: `postgresql+asyncpg://tcgradar:secret@localhost:5432/tcgradar`
- Default for Docker Compose: connection string is set by compose file
- If using standalone PostgreSQL: set this to your connection string

### Feature Flags

**CUSTOMS_REGIME** (required, controls fee calculation)
- Values: `pre_july_2026` or `post_july_2026`
- Default: `pre_july_2026`
- Controls whether €3 flat duty per item is applied to EU imports
- Switch to `post_july_2026` on July 1, 2026
- This is a configuration change, not a code deployment — update at any time without restart

**ENABLE_LAYER_3_SCRAPING** (optional)
- Values: `true` or `false`
- Default: `false`
- If `true`: enables Playwright-based Cardmarket scraping when JustTCG data is >4 hours stale
- Requires PROXY_URL and SCRAPE_MAX_PAGES_PER_HOUR configuration
- Requires Playwright Chromium to be installed
- If `false`: system relies on JustTCG API data only

**ENABLE_LAYER_35_SOCIAL** (optional)
- Values: `true` or `false`
- Default: `false`
- If `true`: enables Reddit/Twitter keyword spike detection for tournament-driven card surges
- Requires TWITTER_BEARER_TOKEN for Twitter; Reddit requires no auth
- If `false`: social spike events are not monitored

**ENABLE_BUNDLE_LOGIC** (optional)
- Values: `true` or `false`
- Default: `true`
- If `true`: enables Seller Density Score calculation for multi-card bundle opportunities
- If `false`: bundle signals are not generated; only single-card arbitrage

### Scraping Configuration (when ENABLE_LAYER_3_SCRAPING=true)

**PROXY_URL** (optional, strongly recommended for production)
- HTTP/S proxy URL for all scraping requests
- Format: `http://user:password@proxy.hostname:8080` or `socks5://...`
- If empty: scraping requests come from your local IP (high risk of blocking)
- Recommended: use a residential proxy service (e.g., Bright Data, Smartproxy) for Cardmarket scraping

**SCRAPE_MAX_PAGES_PER_HOUR** (optional)
- Maximum Cardmarket pages to scrape per hour
- Default: `30`
- Range: 10-50 (higher = more risk of IP blocking)
- Recommended: 20-30 for production

**SCRAPE_DELAY_MIN_SECONDS** (optional)
- Minimum random delay between successive scrape requests
- Default: `2`
- Range: 1-5 seconds
- Helps avoid detection

**SCRAPE_DELAY_MAX_SECONDS** (optional)
- Maximum random delay between successive scrape requests
- Default: `8`
- Range: 5-15 seconds
- Actual delay is randomly chosen between min and max

### Defaults (Overridable per User)

**DEFAULT_FORWARDER_RECEIVING_FEE**
- Per-card receiving fee at US forwarder
- Default: `3.50` (USD)
- Overridable per user in user_profiles.forwarder_receiving_fee

**DEFAULT_FORWARDER_CONSOLIDATION_FEE**
- Per-shipment consolidation fee
- Default: `7.50` (USD)
- Overridable per user in user_profiles.forwarder_consolidation_fee

**DEFAULT_INSURANCE_RATE**
- Insurance rate as decimal (2.5% = 0.025)
- Default: `0.025`
- Overridable per user in user_profiles.insurance_rate

**DEFAULT_FOREX_BUFFER**
- EUR/USD pessimistic buffer (2% = 0.02)
- Default: `0.02`
- Applied to all EUR-to-USD conversions to account for market volatility

**EUR_USD_RATE**
- Static fallback EUR/USD rate when no live API key is configured
- Default: `1.08` (indicative)
- Used by `get_current_forex_rate()` if EXCHANGERATE_API_KEY is empty
- Update manually if live API is unavailable for extended periods

**DEFAULT_MIN_SELLER_RATING**
- Minimum acceptable seller rating percentage
- Default: `97.0`
- Overridable per user in user_profiles.min_seller_rating

**DEFAULT_MIN_SELLER_SALES**
- Minimum seller transaction count
- Default: `100`
- Overridable per user in user_profiles.min_seller_sales

**DEFAULT_MIN_PROFIT_THRESHOLD**
- Minimum P_real (net profit USD) to generate a signal
- Default: `5.00`
- Overridable per user in user_profiles.min_profit_threshold

**DEFAULT_MIN_HEADACHE_SCORE**
- Minimum acceptable headache score (Labor-to-Loot ratio)
- Default: `5`
- Overridable per user in user_profiles.min_headache_score
- Higher = easier (less labor per dollar profit)

---

## Running Tests

### Full Test Suite

```bash
# Run all tests
pytest tests/ -v

# Expected: 400+ tests passing
# Run time: ~30-60 seconds depending on system
```

### With Coverage Report

```bash
# Generate coverage report
pytest tests/ --cov=src --cov-report=term-missing

# Shows which lines are tested and which are not
# Aim for >95% coverage on engine/ and signals/ modules
```

### Test Specific Modules

```bash
# Test only fee calculations
pytest tests/test_fees.py -v

# Test only profit calculations
pytest tests/test_profit.py -v

# Test signal generation
pytest tests/test_generator.py -v

# Test integration end-to-end
pytest tests/test_integration.py -v
```

### Debugging Failed Tests

```bash
# Run with verbose output and print statements
pytest tests/test_fees.py -v -s

# Stop on first failure
pytest tests/ -x

# Run only tests matching a pattern
pytest tests/ -k "bundle" -v
```

---

## Database Migration Procedure

All database schema changes must go through Alembic. Never run raw DDL outside migrations.

### Applying Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Check current migration state
alembic current

# Show migration history
alembic history --verbose
```

### Migration Chain

The following migrations form the complete schema. They must be applied in order:

1. **001_initial_schema.py**
   - Creates `market_prices` table
   - Creates `card_metadata` table
   - Creates `user_profiles` table

2. **002_signals_schema.py**
   - Creates `signals` table with RLS policies
   - Creates `signal_audit` table
   - Enables RLS on signals table (tenant isolation)

3. **003_phase2_schema.py**
   - Creates `price_history` table (append-only)
   - Adds seller columns to `market_prices`: seller_id, seller_rating, seller_sales, sales_30d, active_listings
   - Creates index on (card_id, source, recorded_at) for trend queries

4. **004_synergy_schema.py**
   - Creates `synergy_cooccurrence` table (support card matrix)
   - Stores co-occurrence counts from tournament decklists

5. **005_discord_profile.py**
   - Adds `discord_channel_id` column to `user_profiles`
   - Makes discord delivery opt-in via this field

6. **006_users_table.py** *(Phase 4)*
   - Creates `users` table (id, email, created_at, is_active)
   - Adds FK constraint: `signals.tenant_id → users.id`
   - Adds FK constraint: `user_profiles.id → users.id` (1:1 extension pattern)
   - **Note:** Creating a user_profile row now requires a users row with the same UUID first

7. **007_subscription_tier.py** *(Phase 4)*
   - Adds `subscription_tier` column to `user_profiles` (default: `"free"`)
   - Valid values: `free`, `trader`, `pro`, `shop`

### Creating New Migrations

```bash
# Create a new migration with auto-detection
alembic revision --autogenerate -m "add_new_column_to_table"

# Edit the generated file in alembic/versions/
# Test locally before deploying to production
alembic upgrade head

# Verify the schema change
alembic current
```

### Rolling Back Migrations

```bash
# Roll back one migration
alembic downgrade -1

# Roll back to a specific migration (use revision hash from history)
alembic downgrade 001_initial_schema

# Roll back all migrations (WARNING: destructive)
alembic downgrade base
```

### Testing Migrations Locally

```bash
# Start a fresh database
docker-compose down -v
docker-compose up -d

# Apply migrations
alembic upgrade head

# Verify all tables exist
psql postgresql://tcgradar:tcgradar@localhost:5432/tcgradar -c "\dt"

# Check signal RLS is enforced
psql postgresql://tcgradar:tcgradar@localhost:5432/tcgradar -c "\d signals"
```

---

## Feature Flags: Detailed Configuration

### CUSTOMS_REGIME: Pre/Post-July 2026 Switch

**What it does:** Controls whether €3 flat import duty is applied per item when calculating fees for EU→US imports.

**Values:**
- `pre_july_2026` (default)
  - De minimis rules apply
  - No per-item duty unless shipment >$800
  - Lower cost = more profitable spreads

- `post_july_2026`
  - €3 flat duty per card imported
  - Applied uniformly across all cards
  - Reduces margin, affects profitability rankings

**When to switch:**
- Set to `post_july_2026` on or after July 1, 2026
- This is a simple config change — no code changes required
- System will immediately recalculate all active signals with new fee tier

**Implementation:** Checked in `src/engine/fees.py` within `calculate_platform_fees()` when computing EU import duties.

### ENABLE_LAYER_3_SCRAPING: Targeted Cardmarket Scraping

**What it does:** When JustTCG data is stale (>4 hours old), use Playwright to scrape Cardmarket directly for current pricing.

**Values:**
- `false` (default)
  - Relies entirely on JustTCG API polling
  - No Playwright overhead, no IP blocking risk
  - May miss real-time Cardmarket-only listings

- `true`
  - Enables Playwright-based scraping
  - Triggered when JustTCG data is >4 hours stale
  - Falls back to CSS selectors if network interception fails
  - Falls back to vision (AI) if CSS fails (Phase 3)

**Prerequisites if enabled:**
- `playwright install chromium` must be run before startup
- PROXY_URL strongly recommended to avoid IP blocks
- SCRAPE_MAX_PAGES_PER_HOUR and delay settings tuned

**When to enable:**
- Production environment where real-time pricing is critical
- When you have a proxy service available
- Not necessary if JustTCG API coverage is sufficient for your market

**Implementation:** Checked in `src/main.py` scheduler initialization. If `true`, scheduler instantiates ScraperRunner and attaches it to the signal generator.

### ENABLE_LAYER_35_SOCIAL: Social Spike Detection

**What it does:** Monitors Reddit and Twitter/X for sudden keyword frequency spikes (e.g., tournament spike, meta shift) to trigger targeted scraping.

**Values:**
- `false` (default)
  - Social monitoring disabled
  - No Reddit/Twitter API calls
  - Lower latency for signal generation

- `true`
  - Monitors Reddit (no auth required) every 30 minutes
  - Monitors Twitter (requires TWITTER_BEARER_TOKEN) every 30 minutes
  - Triggers targeted scraping when 3+ keywords spike
  - Adds event-driven signal type to `signals` table

**Prerequisites if enabled:**
- TWITTER_BEARER_TOKEN must be set (for Twitter monitoring)
- Reddit monitoring works without authentication

**When to enable:**
- Live trading environment where tournament meta shifts happen
- When you want to catch early hype cycles
- Not necessary if you're only doing arbitrage-based signals

**Implementation:** Checked in `src/main.py` scheduler initialization. If `true`, scheduler instantiates SocialListener and wires event triggers to scraper.

### ENABLE_BUNDLE_LOGIC: Seller Density Score Calculation

**What it does:** Calculate Seller Density Score (SDS) to identify multi-card bundle opportunities from the same seller.

**Values:**
- `true` (default)
  - Calculates SDS for every price listing
  - Enables bundle-type signals when SDS ≥ 5
  - Amortizes shipping cost across multiple cards

- `false`
  - Treats every listing as single-card
  - SDS remains 1 for all cards
  - Shipping is fully allocated to the primary card

**When to disable:**
- If you only trade single cards (not bundles)
- If bundle shipping logistics are not set up yet
- For simpler profitability model

**Impact:** Significantly affects P_real calculation when multiple cards from the same seller are available. Disabling it conservatively calculates profit (shipping cost fully on primary card).

**Implementation:** Checked in `src/engine/bundle.py` in `calculate_seller_density_score()`. If flag is `false`, returns SDS=1 for all listings.

---

## Scraping Setup: Layer 3 Configuration

### Prerequisites

Layer 3 scraping requires:
1. `playwright install chromium` — Install Chromium once before first use
2. PROXY_URL — Strongly recommended (optional but recommended)
3. SCRAPE_MAX_PAGES_PER_HOUR — Configured (default 30, adjust based on proxy capacity)

### Installation

```bash
# Install Playwright Chromium (one-time setup)
playwright install chromium

# On Windows:
# - May require 500+ MB disk space
# - Takes 2-3 minutes on first run
# - Downloads to ~/.cache/ms-playwright/

# Verify installation
playwright install --help
```

### Proxy Configuration

A proxy service is essential for production scraping to avoid Cardmarket IP blocks.

```bash
# In .env, set:
PROXY_URL=http://user:password@proxy.provider.com:8080

# Or with SOCKS5:
PROXY_URL=socks5://user:password@proxy.provider.com:1080

# Test the proxy before enabling scraping
curl -x $PROXY_URL https://www.cardmarket.com/
```

**Recommended proxy providers:**
- Bright Data (formerly Luminati) — Residential proxies
- Smartproxy — Low cost, good coverage
- Oxylabs — Enterprise-grade
- ScraperAPI — All-in-one (handles rotation automatically)

**Cost consideration:** Most providers charge $5-$50/month for 10-50 GB/month data. At 30 pages/hour, you use ~100 MB/day = 3 GB/month. Budget accordingly.

### Rate Limiting

```bash
# In .env, configure scrape rates:
SCRAPE_MAX_PAGES_PER_HOUR=30          # Adjust based on proxy capacity
SCRAPE_DELAY_MIN_SECONDS=2            # Minimum delay between requests
SCRAPE_DELAY_MAX_SECONDS=8            # Maximum delay between requests
```

**Conservative settings (for shared proxy):**
- SCRAPE_MAX_PAGES_PER_HOUR=20
- SCRAPE_DELAY_MIN_SECONDS=3
- SCRAPE_DELAY_MAX_SECONDS=10

**Aggressive settings (for dedicated proxy):**
- SCRAPE_MAX_PAGES_PER_HOUR=50
- SCRAPE_DELAY_MIN_SECONDS=1
- SCRAPE_DELAY_MAX_SECONDS=3

### Fallback Chain

If Layer 3 scraping is enabled, the system follows this fallback chain:

1. **Network Interception (PRIMARY)**
   - Intercept network requests via `page.route()`
   - Extract prices from JSON responses (most reliable)
   - Fastest method, lowest detection risk

2. **CSS Selectors (BACKUP)**
   - Parse DOM using deep CSS selectors
   - Used if network interception fails
   - Slower, higher detection risk

3. **Vision/AI (EMERGENCY — Phase 3)**
   - Take screenshot and use vision model to extract prices
   - Used only if both above methods fail
   - Requires ANTHROPIC_API_KEY
   - Slowest, may not be accurate

The scheduler logs which method succeeded for each scrape job.

---

## Production Checklist

Before deploying TCG Radar to production:

### API Keys and Credentials

- [ ] JUSTTCG_API_KEY — Set and tested
- [ ] POKEMONTCG_API_KEY — Set and tested
- [ ] TELEGRAM_BOT_TOKEN — Set and bot can receive messages
- [ ] DISCORD_BOT_TOKEN — Set if Discord delivery enabled
- [ ] TWITTER_BEARER_TOKEN — Set if social monitoring enabled
- [ ] EXCHANGERATE_API_KEY — Set if live forex rates needed (or falling back to EUR_USD_RATE)
- [ ] ANTHROPIC_API_KEY — Set if vision fallback needed (Phase 3)

### Database

- [ ] DATABASE_URL — Points to production PostgreSQL instance
- [ ] PostgreSQL 15+ is running and accessible
- [ ] `alembic upgrade head` completed successfully
- [ ] All 7 migration files have been applied (check with `alembic current`)
- [ ] RLS policies are in place on signals table
- [ ] At least one subscriber created via `python scripts/add_user.py`

### Application Setup

- [ ] Python 3.11+ is installed
- [ ] `pip install -e ".[dev]"` completed
- [ ] `pytest tests/ -v` passes all 400+ tests
- [ ] If ENABLE_LAYER_3_SCRAPING=true:
  - [ ] `playwright install chromium` completed
  - [ ] PROXY_URL is configured
  - [ ] SCRAPE_MAX_PAGES_PER_HOUR is tuned for your proxy

### Feature Flags

- [ ] CUSTOMS_REGIME — Set to correct value for current date (pre_july_2026 or post_july_2026)
- [ ] ENABLE_LAYER_3_SCRAPING — Set to `true` or `false` based on requirements
- [ ] ENABLE_LAYER_35_SOCIAL — Set to `true` or `false` based on requirements
- [ ] ENABLE_BUNDLE_LOGIC — Set to `true` or `false` based on trading style

### Telegram Bot

- [ ] Telegram bot webhook is configured (if using webhooks instead of polling)
- [ ] Bot can send messages to your user_profiles.telegram_chat_id
- [ ] Message template and formatting are correct

### Monitoring and Logging

- [ ] Structured logging is configured (output goes to file or log aggregation service)
- [ ] Scheduler process has process supervisor (systemd, supervisord, or Docker)
- [ ] Alerting is set up for:
  - [ ] Scheduler crashes or hangs
  - [ ] Database connection failures
  - [ ] API rate limit exceptions
  - [ ] Telegram delivery failures

### Backup and Recovery

- [ ] Database is backed up daily
- [ ] Backup retention policy is defined (minimum 7 days)
- [ ] Restore procedure is tested at least once
- [ ] signal_audit table is retained indefinitely for dispute resolution

### Performance

- [ ] JustTCG polling cadence is tuned (default 6 hours)
- [ ] Signal scan cadence is tuned (default 30 minutes)
- [ ] Database indexes are in place:
  - [ ] market_prices(card_id, source)
  - [ ] signals(tenant_id, created_at)
  - [ ] signal_audit(signal_id)

### Security

- [ ] .env file is not committed to version control
- [ ] .env file has restricted permissions (chmod 600)
- [ ] No API keys are logged or printed
- [ ] Database user has least-privilege role (no superuser)
- [ ] HTTPS/TLS is used for all external API calls

---

## Monitoring and Troubleshooting

### Common Issues

**"Database connection refused"**
```bash
# Check if PostgreSQL is running
docker-compose logs postgres

# Restart if needed
docker-compose restart postgres

# Verify connection string in .env
echo $DATABASE_URL
```

**"Playwright Chromium not found"**
```bash
# Re-run installation
playwright install chromium

# Verify installation
ls ~/.cache/ms-playwright/chromium*/
```

**"Signal generation is slow"**
- Check database index on market_prices(card_id, source)
- Check if signal scan interval (SIGNAL_SCAN_INTERVAL_MINUTES) is too short
- Monitor CPU usage during signal scan

**"Cardmarket scraping blocked"**
- IP was likely detected
- Increase SCRAPE_DELAY_MIN_SECONDS and SCRAPE_DELAY_MAX_SECONDS
- Rotate to a different proxy
- Reduce SCRAPE_MAX_PAGES_PER_HOUR

**"Telegram messages not delivering"**
- Verify TELEGRAM_BOT_TOKEN is correct
- Verify user_profiles.telegram_chat_id is set
- Check Telegram bot logs: `curl https://api.telegram.org/bot<TOKEN>/getMe`

### Logging

All logs are structured (via `structlog`) and include:
- `card_id` — Card being processed
- `source` — API source (JustTCG, Cardmarket, etc.)
- `timestamp` — UTC datetime
- `event` — Human-readable event description

```bash
# View logs in real-time
tail -f tcgradar.log | grep signal_generated

# Filter by card_id
grep "sv1-25" tcgradar.log

# Count events by type
grep "event=" tcgradar.log | cut -d' ' -f2 | sort | uniq -c
```

---

## Updating and Redeployment

### Updating the Code

```bash
# Pull latest changes
git pull origin main

# Reinstall dependencies (in case pyproject.toml changed)
pip install -e ".[dev]"

# Run tests to verify
pytest tests/ -v

# Restart the scheduler
# (Kill existing process and start new one)
```

### Updating Configuration

```bash
# Edit .env
nano .env

# Restart scheduler (configuration is read at startup)
# No database migration needed unless CUSTOMS_REGIME changes
```

### Database Schema Changes

```bash
# New migration files are auto-detected in alembic/versions/
# Apply them:
alembic upgrade head

# Restart scheduler
```

### Minimal Downtime Deployment

For production:
1. Run migrations on database (usually <30 seconds)
2. Start new scheduler process with new code
3. Stop old scheduler process (gracefully wait for in-flight signals)
4. Verify new process is running and generating signals

---

## Support and Debugging

For issues, check:
1. `.env` — All required keys are set
2. `pytest tests/ -v` — Test suite passes
3. `alembic current` — All migrations applied
4. Database logs — `docker-compose logs postgres`
5. Application logs — Grep for error level entries

For detailed debugging:
- Read `TCG_RADAR_SPEC.md` (product spec)
- Read `CLAUDE.md` (engineering protocol)
- Read `docs/API.md` (internal API reference)
- Check test files for examples of expected behavior
