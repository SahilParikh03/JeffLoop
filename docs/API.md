# API.md — TCG Radar Internal API Reference

This document describes the internal data models, query interfaces, and notification hooks for TCG Radar's signal system. This is an internal API for developers and power users; there is no public REST API in Phase 1.

---

## Signal Data Schema

The `signals` table stores generated trading opportunities. All rows are tenant-isolated via Row-Level Security (RLS). Every query must filter by `tenant_id`.

### Table Structure

```sql
CREATE TABLE signals (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,           -- RLS partition key
    card_id VARCHAR NOT NULL,          -- Format: {set}-{number} (e.g., sv1-25)
    signal_type VARCHAR NOT NULL,      -- arbitrage | event_driven | bundle | investment
    net_profit_usd DECIMAL(10, 2),     -- P_real after all fees
    buy_price_eur DECIMAL(10, 2),      -- Effective buy price with shipping & condition
    sell_price_usd DECIMAL(10, 2),     -- Target sell price on TCGPlayer/eBay
    velocity_score DECIMAL(4, 2),      -- V_s (0.5-1.5 standard, >1.5 liquid, <0.5 risky)
    headache_score DECIMAL(4, 2),      -- Labor-to-Loot ratio (>15 easy, <5 hard)
    seller_density_score INT,          -- SDS: cards from same seller (1-10+)
    platform VARCHAR,                  -- cardmarket | tcgplayer
    deep_link_buy VARCHAR,             -- Direct URL to buy listing
    deep_link_sell VARCHAR,            -- Direct URL to create sell listing
    risk_flags TEXT[],                 -- Array of risk flags
    created_at TIMESTAMPTZ,            -- Signal generation time (UTC)
    expires_at TIMESTAMPTZ,            -- Exclusivity window end
    delivered_to TEXT[],               -- User IDs who received this signal
    created_by_version VARCHAR         -- Audit: system version that created signal
);

CREATE POLICY signals_isolation ON signals
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

### Field Descriptions

**id** (UUID)
- Unique signal identifier
- Generated at creation time
- Immutable

**tenant_id** (UUID)
- User/tenant identifier for RLS isolation
- Every row is scoped to a single tenant
- Row-Level Security is enforced at database level
- No tenant can see another tenant's signals

**card_id** (VARCHAR)
- Unique card identifier in format: `{set}-{number}`
- Examples: `sv1-25`, `sv2-100`, `sv3-010`
- Matches pokemontcg.io card ID format
- Used to join with card_metadata for full card info

**signal_type** (VARCHAR)
- Classification of the opportunity:
  - `arbitrage` — Classic buy-low-sell-high spread
  - `event_driven` — Triggered by tournament results or meta shift
  - `bundle` — Multi-card opportunity from same seller
  - `investment` — Speculative hold with future profit potential (Phase 3)

**net_profit_usd** (DECIMAL)
- P_real: net profit in USD after all fees
- Includes: platform fees, condition penalty, customs duty (if applicable), forwarder fees, insurance
- Excludes: taxes, storage costs, labor (captured in headache_score)
- Always >= 0 (negative spreads are not signaled)
- Sorted descending for "most profitable first" signal ranking

**buy_price_eur** (DECIMAL)
- Effective buy price in EUR per card
- Includes: Cardmarket listing price + shipping + condition penalty
- Does not include forwarder fees (those are in the fee calculation, not here)
- Used for user reference (showing cost basis)

**sell_price_usd** (DECIMAL)
- Target sell price in USD on TCGPlayer or eBay
- Condition-adjusted (mapped from Cardmarket grade)
- Does not include seller fees (those are in the fee calculation)
- Used for user reference (showing target price)

**velocity_score** (DECIMAL)
- V_s: sales velocity tier from PokeTrace or calculated from price_history
- Tiers:
  - `> 1.5` — Liquid gold (high velocity, quick sell)
  - `0.5 - 1.5` — Standard (normal velocity)
  - `< 0.5` — Bagholder risk (slow-moving card)
- Calculated as: `sales_30d / active_listings` from PokeTrace
- Fallback: calculated from price_history if PokeTrace unavailable
- Used to assess liquidity risk in the spreadsheet

**headache_score** (DECIMAL)
- H: Labor-to-Loot ratio
- Formula: `(shipping_time_hours + listing_time_hours) / net_profit_usd`
- Tiers:
  - `H > 15` — Tier 1 (easy money, minimal labor per dollar)
  - `5 < H <= 15` — Tier 2 (moderate labor)
  - `H <= 5` — Tier 3 (labor-intensive, <$1 per hour equivalent)
- User can set `min_headache_score` to filter out labor-heavy deals
- Example: if net_profit_usd=50 and estimated labor is 3 hours, then H = 3/50 = 0.06 (Tier 1)

**seller_density_score** (INT)
- SDS: count of target cards from the same seller
- Range: 1 to 10+ (uncapped)
- SDS=1 means single-card opportunity from this seller
- SDS=5+ triggers bundle-type signals
- Used to identify multi-card shipping consolidation opportunities
- Calculated in src/engine/bundle.py

**platform** (VARCHAR)
- Source platform for the buy listing:
  - `cardmarket` — Cardmarket EU seller
  - `tcgplayer` — TCGPlayer US seller (future)
- Indicates which deep_link_buy URL points to

**deep_link_buy** (VARCHAR)
- Direct URL to the Cardmarket/TCGPlayer buy listing
- Format: full HTTPS URL with card ID and seller details
- Clickable in Telegram/Discord notification
- If seller delists before signal delivery, URL becomes 404
- Built by src/signals/deep_link.py

**deep_link_sell** (VARCHAR)
- Direct URL to start a sell listing on user's target platform
- Format: `https://www.tcgplayer.com/product/<id>/sell` (example)
- Prefilled with card ID, user fills in condition/quantity/price
- Built by src/signals/deep_link.py

**risk_flags** (TEXT[])
- Array of risk flags (PostgreSQL text array)
- Indicates cautions or issues with this signal
- See Risk Flags section below
- Example: `['ROTATION_RISK', 'STALE_LISTING', 'LOW_VELOCITY']`
- User can filter/suppress signals by risk flag

**created_at** (TIMESTAMPTZ)
- UTC timestamp when signal was generated
- Format: ISO 8601 with timezone offset
- Used for signal age calculation and cooldown logic
- Immutable after creation

**expires_at** (TIMESTAMPTZ)
- UTC timestamp when signal's exclusivity window ends
- Signals are exclusive to the first user in rotation until this time
- Typically 2-3 hours after creation
- After expiry, signal may be re-rotated to other users
- Used by cascade logic to manage user priority

**delivered_to** (TEXT[])
- PostgreSQL text array of user IDs who have received this signal
- Populated after signal delivery to Telegram/Discord
- Used to prevent duplicate delivery to the same user
- Example: `['user-123', 'user-456']`

**created_by_version** (VARCHAR)
- System version that created this signal
- Example: `v1.2.3-phase2-build42`
- Used for debugging and audit trail
- Helps identify if a signal was created by old vs. new code

---

## Querying Signals (Tenant Isolation)

All signal queries require tenant isolation via RLS. The database enforces this at the row level — no tenant can read another tenant's data even if they craft a manual SQL query.

### Setting the Tenant Context

Before querying, set the tenant context in your session:

```sql
-- PostgreSQL session
SET app.tenant_id = 'your-tenant-uuid-here';

-- Now all queries are automatically filtered by this tenant
SELECT * FROM signals;  -- Only sees signals for your tenant
```

### Common Query Patterns

**Get your active signals (not yet expired), sorted by profit**

```sql
SET app.tenant_id = 'your-tenant-uuid-here';

SELECT
    id,
    card_id,
    signal_type,
    net_profit_usd,
    headache_score,
    velocity_score,
    deep_link_buy,
    created_at,
    expires_at
FROM signals
WHERE expires_at > NOW()
ORDER BY net_profit_usd DESC
LIMIT 20;
```

**Get signals by type**

```sql
SET app.tenant_id = 'your-tenant-uuid-here';

SELECT * FROM signals
WHERE signal_type = 'bundle'
  AND expires_at > NOW()
ORDER BY net_profit_usd DESC;
```

**Get signals without specific risk flag**

```sql
SET app.tenant_id = 'your-tenant-uuid-here';

SELECT * FROM signals
WHERE NOT (risk_flags @> ARRAY['ROTATION_RISK'])
  AND expires_at > NOW()
ORDER BY net_profit_usd DESC;
```

**Get signals delivered to you**

```sql
SET app.tenant_id = 'your-tenant-uuid-here';

SELECT * FROM signals
WHERE 'your-user-id' = ANY(delivered_to)
ORDER BY created_at DESC;
```

**Get signal audit trail (why a signal was/wasn't created)**

```sql
SET app.tenant_id = 'your-tenant-uuid-here';

SELECT
    sa.signal_id,
    sa.card_id,
    sa.filter_reason,
    sa.raw_spread,
    sa.P_real,
    sa.created_at
FROM signal_audit sa
WHERE sa.tenant_id = current_setting('app.tenant_id')::uuid
ORDER BY sa.created_at DESC
LIMIT 100;
```

---

## User Profile Fields

The `user_profiles` table stores per-tenant configuration that affects signal generation. Each user has one profile row.

### Critical Fields (Affect Signal Calculation)

**seller_platform** (VARCHAR)
- Primary resale platform: `tcgplayer`, `ebay`, or `cardmarket_pro`
- Determines which fee formula is applied (P_real calculation)
- Default: `tcgplayer` (US-based, TCGPlayer fees apply)
- Must match the user's actual resale platform for accurate profit calculation

**country** (VARCHAR)
- ISO country code (e.g., `US`, `DE`, `GB`, `AU`)
- Affects customs regime calculation and de minimis rules
- Example: US buyers importing from EU cardmarket get favorable de minimis rates
- Used to select correct duty/customs formula in src/engine/fees.py

**forwarder_receiving_fee** (DECIMAL)
- Per-card receiving fee at US forwarder in USD
- Typical range: $2.50-$4.00 per card
- Overrides DEFAULT_FORWARDER_RECEIVING_FEE config
- Example: if user's forwarder charges $3.50/card, set to 3.50
- Added to buy_price_eur when calculating effective cost

**forwarder_consolidation_fee** (DECIMAL)
- Per-shipment consolidation fee from forwarder in USD
- Typical range: $5.00-$10.00 per shipment
- Overrides DEFAULT_FORWARDER_CONSOLIDATION_FEE config
- Example: if user batches 5 cards = $7.50 consolidation / 5 = $1.50 per card
- Amortized across all cards in a single forwarder shipment

**insurance_rate** (DECIMAL)
- Insurance rate as decimal (2.5% = 0.025)
- Overrides DEFAULT_INSURANCE_RATE config
- Applied only to cards in insurance_deadzone ($50-$150)
- If user opts out of insurance, set to 0.0
- Affects fee_insurance calculation in src/engine/fees.py

**min_profit_threshold** (DECIMAL)
- Minimum P_real (net profit USD) to generate a signal
- Overrides DEFAULT_MIN_PROFIT_THRESHOLD config
- Example: if set to 10.00, signals with P_real < $10 are suppressed
- Filters out low-margin opportunities

**min_headache_score** (DECIMAL)
- Minimum acceptable headache score (Labor-to-Loot ratio)
- Overrides DEFAULT_MIN_HEADACHE_SCORE config
- Example: if set to 8, signals with H < 8 (labor-intensive) are suppressed
- Lets users avoid time-consuming deals

**discord_channel_id** (VARCHAR)
- Discord channel snowflake ID for signal delivery (Phase 2+)
- Example: `1234567890123456789`
- If null or empty: Discord delivery is skipped; Telegram used instead
- Set via user profile update (HTTP API in Phase 3)

**telegram_chat_id** (VARCHAR)
- Telegram chat ID for signal delivery
- Numeric ID (negative for group chats)
- Example: `123456789` (personal chat) or `-1001234567890` (group chat)
- Must be set for Telegram delivery to work
- User receives this from @BotFather when setting up bot

**excluded_sets** (TEXT[])
- PostgreSQL text array of set codes to exclude
- Example: `['sv4pt', 'sv5', 'sv6']` (exclude future rotation)
- Signals for cards in these sets are suppressed
- Useful for excluding sets you don't want to resell
- Read in src/engine/rotation.py during rotation_risk check

**condition_floor** (VARCHAR)
- Minimum acceptable card condition
- Values: `MT` (Mint), `NM` (Near Mint), `EXC` (Excellent), `GD` (Good), `LP` (Lightly Played)
- Example: if set to `NM`, cards graded lower than NM are skipped
- Cardmarket grades are mapped to TCGPlayer equivalents (pessimistic)
- Read in src/signals/generator.py before signal creation

---

## Notification Hooks: Telegram and Discord

Signals are delivered to users via two notification channels: Telegram (Phase 1) and Discord (Phase 2+).

### Telegram Delivery (src/signals/telegram.py)

**What it does:** Sends formatted text message to user's Telegram chat with signal details.

**Configuration:**
- TELEGRAM_BOT_TOKEN — Required, set in .env
- user_profiles.telegram_chat_id — Required per user

**Message Format:**
```
TCG Radar Signal: sv1-25 Charizard
━━━━━━━━━━━━━━━━━━
Type: arbitrage | Profit: $47.50 USD
Buy: €28.99 (Cardmarket)
Sell: $45.00 (TCGPlayer NM)
Velocity: 1.8 (Liquid Gold)
Headache: 3.2 (Easy Money)
Bundle: 2 cards from seller
Risk: None
━━━━━━━━━━━━━━━━━━
Buy: [direct link]
Sell: [direct link]
Expires: 2026-02-23 14:30 UTC
```

**Delivery Logic:**
1. Signal is generated in src/signals/generator.py
2. Scheduler checks signal cascade logic (expiry, cooldown)
3. If ready to deliver, TelegramNotifier.send_signal() is called
4. Message is sent via httpx to Telegram Bot API
5. On success, signal.delivered_to list is updated with user_id

**Error Handling:**
- If Telegram API returns 429 (rate limit), message is queued for retry
- If user's chat_id is invalid (user blocked bot), error is logged
- If TELEGRAM_BOT_TOKEN is missing, delivery is skipped with warning

**Rate Limits:**
- Telegram Bot API: ~30 messages/second per bot
- If you have 1000+ users getting simultaneous signals, batch delivery over 30+ seconds

**Testing Telegram Delivery:**
```python
# In tests/test_generator.py
def test_telegram_delivery_on_signal_generation():
    # Signal is generated
    signal = generator.generate_signals(...)

    # TelegramNotifier is called with signal details
    assert telegram_notifier.send_signal.called
    assert signal.delivered_to == ['user-123']
```

### Discord Delivery (src/signals/delivery.py)

**What it does:** Sends rich embed message to user's Discord channel with signal details and color-coding.

**Configuration:**
- DISCORD_BOT_TOKEN — Required, set in .env
- user_profiles.discord_channel_id — Required per user

**Embed Format:**
```
Title: sv1-25 Charizard [ARBITRAGE]
Color: Green (arbitrage) | Red (event_driven) | Blue (bundle)
Fields:
  Profit: $47.50 USD
  Buy: €28.99 (Cardmarket NM)
  Sell: $45.00 (TCGPlayer NM)
  Velocity: 1.8 (Liquid Gold)
  Headache: 3.2 (Easy)
  Bundle: 2 from seller
  Risks: None
Buttons:
  [Buy Link]
  [Sell Link]
Footer: Expires 2026-02-23 14:30 UTC
```

**Delivery Logic:**
1. Signal is generated
2. DiscordNotifier.send_signal() constructs embed via httpx POST
3. Message is sent to Discord webhook endpoint
4. On success, signal.delivered_to is updated

**Signal Type Color Coding:**
- `arbitrage` — Green (#00FF00)
- `event_driven` — Red (#FF0000)
- `bundle` — Blue (#0000FF)
- `investment` — Yellow (#FFFF00)

**Error Handling:**
- If Discord webhook returns 404 (invalid channel_id), error is logged
- If DISCORD_BOT_TOKEN is missing, delivery is skipped with warning
- Partial failures (some users succeed, some fail) are logged per user

**Testing Discord Delivery:**
```python
# In tests/test_delivery.py
def test_discord_embed_construction():
    signal = Signal(...)
    embed = construct_discord_embed(signal)

    assert embed['title'] == 'sv1-25 Charizard'
    assert embed['color'] == 0x00FF00  # Green for arbitrage
```

---

## Rate Limits and Polling Cadences

The scheduler maintains internal polling rates for all data sources. These are configured in `src/config.py` as named constants.

### Data Source Polling

**JUSTTCG_POLL_INTERVAL_HOURS**
- Default: `6` hours
- Frequency: JustTCG API is polled every 6 hours for updated prices
- Rationale: Cardmarket updates slowly; 6-hour cadence captures real swings without API spam
- If interval is too short: API rate limit hit, system backs off
- If interval is too long: Stale data, missed opportunities

**POKEMONTCG_REFRESH_INTERVAL_HOURS**
- Default: `24` hours
- Frequency: pokemontcg.io card metadata is refreshed daily
- Rationale: Card data (regulation marks, variant IDs) changes infrequently
- Includes: regulation marks, reprint status, set rotation calendar

**POKETRACE_POLL_INTERVAL_HOURS**
- Default: `12` hours
- Frequency: PokeTrace velocity data is polled every 12 hours
- Rationale: Velocity (sales/30d) changes gradually; 12-hour cadence is sufficient
- Falls back to price_history calculation if PokeTrace unavailable

**SIGNAL_SCAN_INTERVAL_MINUTES**
- Default: `30` minutes
- Frequency: Rules engine runs signal scan every 30 minutes
- Rationale: Balances responsiveness vs. computational load
- Scans all cards in market_prices table against all filter rules
- If interval too short: CPU overload, database contention
- If interval too long: Delayed signals, missed time-sensitive opportunities

**SOCIAL_SPIKE_POLL_INTERVAL_MINUTES**
- Default: `30` minutes
- Frequency: Social spike detection monitors Reddit/Twitter every 30 minutes
- Rationale: Keyword spikes emerge over hours, not minutes
- Monitors: Pokémon TCG community keywords, tournament mentions, meta shifts
- Triggers: Targeted Cardmarket scraping when spike detected

**LIMITLESS_POLL_INTERVAL_MINUTES**
- Default: `60` minutes
- Frequency: Limitless TCG tournament results are checked every 60 minutes
- Rationale: Tournaments occur sporadically; 1-hour cadence captures new results
- Triggers: Build co-occurrence matrix, identify meta support cards
- Helps identify synergy-driven card spikes

### Signal Exclusivity and Cascade

**CASCADE_COOLDOWN_SECONDS**
- Default: `10` seconds
- Cooldown between delivering the same signal to consecutive users in rotation
- Rationale: Telegram API latency can cause duplicate delivery within <1 second
- Implementation: In src/signals/cascade.py, check `NOW() - signal.created_at > 10 seconds` before rotating to next user
- Too short: Risk of duplicate delivery to same user
- Too long: Later users in rotation miss opportunity (opportunity expires)

**SIGNAL_EXCLUSIVITY_WINDOW_MINUTES**
- Default: `180` minutes (3 hours)
- Duration that signal is exclusive to first user in rotation
- After expiry, signal can be re-rotated to other users
- Rationale: Early rotated users get priority; later users get "cold" signals (higher risk of delisted or filled)

### Scaling Considerations

If you exceed these rates:

**High volume users (>100 signals/day):**
- Increase SIGNAL_SCAN_INTERVAL_MINUTES to 60 (reduces CPU load)
- Increase JUSTTCG_POLL_INTERVAL_HOURS to 12 (reduces data freshness but API calls)
- Add database connection pooling (SQLAlchemy async pool size)

**High concurrency (>1000 users):**
- Shard signals table by tenant_id
- Use read replicas for signal queries
- Cache market_prices in Redis to avoid DB hits per scan

---

## Risk Flags

Risk flags are stored in the `signals.risk_flags` array. Each flag is a string that indicates a caution or issue with the signal. Users can filter signals by risk flag.

### Complete Risk Flag Reference

**ROTATION_RISK**
- Meaning: Card's regulation mark is within 42 days of rotation
- Source: src/engine/rotation.py, check `get_mark_distance_from_current()`
- Impact: Card may lose value on rotation; buy decision is riskier
- Threshold: Distance < 42 days
- User action: Either accept rotation risk (high profit) or skip (safe)
- Duration: Flag is added 42 days before rotation, cleared on rotation date

**DEATH_SPIRAL**
- Meaning: Card is in active rotation suppression window (spread < 40% of normal)
- Source: src/engine/rotation.py, rotation_suppression_window_days before/after rotation
- Impact: Price is artificially low due to rotation fear; may rebound post-rotation
- Rationale: If rotation risk is real but spread is wide, profit potential may offset risk
- User action: For highest risk tolerance, accept DEATH_SPIRAL if P_real is very high

**FALLING_KNIFE**
- Meaning: Price trend slope < -10% per day (actively falling)
- Source: src/engine/trend.py, classify_trend() returns "FALLING_KNIFE"
- Impact: Card is in a downward trend; may fall further before stabilizing
- Calculation: 7-day least-squares regression from price_history
- User action: Skip if you want to avoid downward-trending cards

**STALE_LISTING**
- Meaning: Listing is >4 hours old (not updated recently)
- Source: src/engine/velocity.py, staleness_penalty applied if market_prices.last_updated < NOW() - 4 hours
- Impact: Velocity score is penalized -20%; card may have sold already
- Detection: Cardmarket shows last_updated timestamp, compared to current time
- User action: May trigger Layer 3 scraping to verify listing is still active

**INSURANCE_DEADZONE**
- Meaning: Card value is $50-$150 (insurance is economically questionable)
- Source: src/engine/fees.py, insurance_deadzone check in calculate_platform_fees()
- Impact: Insurance cost is high relative to profit; might not be worthwhile
- Recommendation: Skip insurance for these cards or negotiate group insurance
- Threshold: $50 < card_value < $150
- User action: Consider self-insuring or using bulk insurance pool

**LOW_VELOCITY**
- Meaning: V_s < 0.5 (bagholder risk tier, slow-moving card)
- Source: src/engine/velocity.py
- Impact: Card may not sell before market conditions change
- Tier: V_s < 0.5 is "bagholder risk," typically niche or older sets
- User action: Avoid unless you have patience to hold 3+ months

**SINGLE_CARD_SHIPPING**
- Meaning: SDS=1 (single card from seller) and card value < $25
- Source: src/engine/bundle.py, shipping_suppression check
- Impact: Full shipping cost eats into margin significantly
- Example: $10 card + $15 shipping = $25 cost, hard to flip for profit
- User action: Skip unless you can bundle with other purchases
- Mitigation: Wait until seller lists multiple target cards

**MATURITY_DECAY**
- Meaning: Set is >60 days old, hype has dissipated
- Source: src/engine/maturity.py, apply_maturity_penalty_with_reprint_rumor()
- Impact: Velocity score is penalized -25%; market interest has declined
- Rationale: New sets have higher velocity; old sets show slower turnover
- Timeline: Flag appears 60+ days after set release
- User action: Accept lower velocity or avoid older sets

**CONDITION_PENALTY**
- Meaning: Card condition is below target TCGPlayer grade
- Source: src/engine/effective_price.py, condition_adjusted_sell_price()
- Impact: Sell price is reduced; example Cardmarket "EXC" = TCGPlayer "LP" with -15% penalty
- User action: Account for lower sell price when calculating profit

---

## Error Codes (Signal Audit Log)

The `signal_audit` table captures rejection reason codes when a card is filtered out and no signal is created. These codes help debug why a card was/wasn't signaled.

### Signal Audit Table Structure

```sql
CREATE TABLE signal_audit (
    id UUID PRIMARY KEY,
    signal_id UUID,                    -- NULL if card was filtered (not signaled)
    tenant_id UUID NOT NULL,
    card_id VARCHAR NOT NULL,
    filter_reason VARCHAR,             -- Reason code if card was rejected
    raw_spread DECIMAL(10, 2),         -- P_real before any filtering
    P_real DECIMAL(10, 2),             -- P_real after filtering (if signaled)
    user_profile_applied JSON,         -- User config at time of calculation
    created_at TIMESTAMPTZ,
    CONSTRAINT fk_signal FOREIGN KEY (signal_id) REFERENCES signals(id)
);
```

### Filter Reason Codes

All codes are stored in `signal_audit.filter_reason` when a card is rejected.

**VARIANT_MISMATCH**
- Meaning: Card ID did not match expected variant (promo vs. standard mismatch)
- Source: src/engine/variant_check.py, validate_variant() returns false
- Details: pokemontcg.io and Cardmarket use different variant encodings; mismatch = wrong card
- Action: Check card_metadata.variant_id against Cardmarket listing variant
- Recovery: If mismatch is a false positive, investigate card_metadata for incorrect encoding

**SELLER_QUALITY_FAIL**
- Meaning: Seller rating < user's min_seller_rating (default 97%) or sales < min_seller_sales (default 100)
- Source: src/engine/seller_quality.py, check_seller_quality()
- Details: Low-quality sellers have higher chargeback/scam risk
- Action: Skip this listing, find another seller for the same card
- User override: Reduce user_profiles.min_seller_rating to accept lower-rated sellers

**CONDITION_REJECT**
- Meaning: Card condition is below user's condition_floor setting
- Source: src/signals/generator.py, condition filter before signal creation
- Details: User set condition_floor='NM' but listing is 'LP' (Lightly Played)
- Action: Find another listing in acceptable condition, or lower condition_floor
- User override: Reduce user_profiles.condition_floor to accept lower conditions

**PROFIT_THRESHOLD_MISS**
- Meaning: P_real (net profit USD) < user's min_profit_threshold
- Source: src/signals/generator.py, profit filter
- Details: Card spread is too small to meet minimum profitability requirement
- Example: If min_profit_threshold=$10 and card P_real=$7.50, rejected
- Action: Either increase min_profit_threshold (accept lower margins) or wait for price movement
- User override: Reduce user_profiles.min_profit_threshold

**VELOCITY_FLOOR_MISS**
- Meaning: V_s < 0.5 (bagholder risk tier, slow-moving card)
- Source: src/engine/velocity.py
- Details: Card has low sales velocity; may not sell quickly
- Impact: Even with good spread, slow velocity = capital tied up longer
- User override: If you're okay holding 3+ months, manually accept this card
- Mitigation: Wait for velocity to improve (seasonal demand spikes)

**ROTATION_SUPPRESSED**
- Meaning: Card is in rotation death spiral (price suppressed 42 days before rotation)
- Source: src/engine/rotation.py, rotation_risk check returns DEATH_SPIRAL
- Details: Spread is insufficient to overcome rotation risk (< 40% of normal)
- Action: Either accept rotation risk (manual signal) or wait for post-rotation stabilization
- User override: Set user_profiles.excluded_sets to exclude cards near rotation

**HEADACHE_FLOOR_MISS**
- Meaning: Headache score < user's min_headache_score
- Source: src/engine/headache.py, calculate_headache_score()
- Details: Card requires too much labor relative to profit (H < 5 = Tier 3, hard labor)
- Example: If min_headache_score=8 and card H=3.2, rejected
- Action: Accept lower headache score (more labor) or increase min_headache_score (fewer signals)
- User override: Reduce user_profiles.min_headache_score

**BUNDLE_SHIPPING_SUPPRESS**
- Meaning: SDS=1 (single-card from seller) and card < $25 value
- Source: src/engine/bundle.py, shipping_suppression logic
- Details: Full single-card shipping cost kills margin
- Example: $10 card + $15 EU shipping = $25 cost, hard to flip
- Action: Wait for seller to list more cards (SDS > 1) to amortize shipping
- Workaround: Manually bundle with other purchases, or find a different seller

**RATE_LIMITED**
- Meaning: Card rejected due to scraper rate limit (Cardmarket blocking scrape attempts)
- Source: src/scraper/runner.py, rate limit detection
- Details: IP was throttled after too many scrape requests; fallback to older data
- Action: Slow down scraping cadence, use proxy rotation, or wait 1 hour
- Recovery: Rate limit is temporary; card will re-enter on next scan cycle

---

## Example Workflow: Signal Generation to Delivery

### Full Lifecycle

1. **Polling** (every 6 hours)
   - JustTCG API is called for latest prices
   - Data is stored in market_prices table
   - price_history is appended with new entry

2. **Metadata Refresh** (every 24 hours)
   - pokemontcg.io API is called for card metadata, regulation marks
   - card_metadata table is updated
   - Variant IDs are refreshed

3. **Signal Scan** (every 30 minutes)
   - src/signals/generator.py iterates all cards in market_prices
   - For each (card, seller) pair:
     1. src/engine/variant_check.py — validate variant (FIRST)
     2. src/engine/velocity.py — check V_s >= 0.5
     3. src/engine/trend.py — exclude falling knife
     4. src/engine/rotation.py — check rotation risk
     5. src/engine/seller_quality.py — check rating/sales
     6. src/engine/effective_price.py — calculate buy/sell prices with condition
     7. src/engine/fees.py — calculate all platform fees
     8. src/engine/headache.py — calculate Labor-to-Loot ratio
     9. src/engine/bundle.py — calculate Seller Density Score
     10. src/engine/profit.py — calculate P_real
   - If all filters pass and P_real > threshold, signal is created
   - If any filter fails, audit row is created with reason code

4. **Cascade & Rotation** (continuously)
   - src/signals/cascade.py checks if signal should be delivered
   - src/signals/rotation.py selects next user in priority rotation
   - 10-second cooldown prevents duplicate delivery

5. **Delivery** (immediately after cascade)
   - TelegramNotifier sends formatted message to user's telegram_chat_id
   - DiscordNotifier sends rich embed to user's discord_channel_id
   - signal.delivered_to array is updated

6. **Audit** (at each step)
   - signal_audit table records every decision
   - Used for debugging, user disputes, system improvements

### Query Signal Audit Trail

```sql
SET app.tenant_id = 'your-tenant-uuid';

-- Find all sv1-25 (Charizard) audit entries for past 24 hours
SELECT
    filter_reason,
    COUNT(*) as count,
    AVG(raw_spread) as avg_spread
FROM signal_audit
WHERE card_id = 'sv1-25'
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY filter_reason
ORDER BY count DESC;

-- Result example:
-- filter_reason         | count | avg_spread
-- ----------------------+-------+------------
-- PROFIT_THRESHOLD_MISS |    12 |       4.50
-- (null)                |     3 |      47.20   <- These 3 became signals!
-- ROTATION_SUPPRESSED   |     2 |      35.10
```

---

## Debugging and Support

### Common Audit Outcomes

**High PROFIT_THRESHOLD_MISS rate:**
- Card spreads are too tight for user's profit minimum
- Solution: Lower user_profiles.min_profit_threshold, or wait for better spreads

**High SELLER_QUALITY_FAIL rate:**
- Few sellers meet quality threshold
- Solution: Lower user_profiles.min_seller_rating, or increase market diversity

**High ROTATION_SUPPRESSED rate:**
- Many cards are near rotation
- Solution: Accept rotation risk (manually, or increase spread threshold), or focus on non-rotating sets

**High HEADACHE_FLOOR_MISS rate:**
- Cards require significant labor relative to profit
- Solution: Lower user_profiles.min_headache_score, or focus on higher-profit opportunities

### Querying for Debugging

**Find the last signal created for a card**

```sql
SET app.tenant_id = 'your-tenant-uuid';

SELECT * FROM signals
WHERE card_id = 'sv1-25'
ORDER BY created_at DESC
LIMIT 1;
```

**Find why a card was never signaled**

```sql
SET app.tenant_id = 'your-tenant-uuid';

SELECT
    filter_reason,
    COUNT(*) as times_rejected,
    MAX(created_at) as most_recent
FROM signal_audit
WHERE card_id = 'sv1-25'
  AND signal_id IS NULL  -- NULL signal_id means it was rejected
GROUP BY filter_reason
ORDER BY times_rejected DESC;
```

**Find signals delivered in last 24 hours**

```sql
SET app.tenant_id = 'your-tenant-uuid';

SELECT
    card_id,
    signal_type,
    net_profit_usd,
    created_at,
    delivered_to
FROM signals
WHERE created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

---

## Rate Limits and API Quotas

### External API Rate Limits

**JustTCG API**
- Typical limit: 1000 requests/day or equivalent
- TCG Radar usage: ~4 requests/6 hours = ~16/day (well under limit)
- Backoff: If 429 (rate limit), retry after 1 hour

**pokemontcg.io API**
- Typical limit: 500 requests/day
- TCG Radar usage: ~1 request/24 hours = ~1/day (well under limit)
- Backoff: If rate limited, use cached data until limit resets

**Twitter API v2**
- Typical limit: 300 requests/15 minutes (per app)
- TCG Radar usage: ~2 requests/30 minutes = ~96/day (well under limit for paid tier)
- Backoff: If 429, exponential backoff

### Internal Rate Limits

**Database Connections**
- SQLAlchemy async pool size: 10 connections
- Adjust if you have >100 concurrent users
- Connection timeout: 30 seconds

**Telegram Bot**
- Limit: ~30 messages/second globally across all bots
- TCG Radar usage: ~1 message/second average (burst to 5/second during signal rush)
- Mitigation: Batch signals over 30+ seconds if >100 users

---

## Data Retention and Cleanup

### Retention Policy

**signals table**
- Retention: Keep indefinitely (signals are historical records of opportunities)
- Cleanup: None; signals are never deleted
- Growth: ~100-500 signals/day per user = ~100k rows/year for active users
- Index: signals(tenant_id, created_at) for efficient pagination

**signal_audit table**
- Retention: Keep indefinitely (audit trail for disputes and debugging)
- Cleanup: None; audit is never deleted
- Growth: ~10k audit rows/day per user (every candidate card is audited)
- Index: signal_audit(signal_id) for signal tracing

**price_history table**
- Retention: Keep indefinitely (used for 7-day trend calculation)
- Cleanup: None; price history is never deleted
- Growth: ~10 rows/card/day per data source = millions of rows/year
- Index: price_history(card_id, source, recorded_at) for trend queries
- Performance: Periodically VACUUM and ANALYZE to maintain query performance

---

## API Deprecation Notice

This is an internal API document for Phase 1-2. There is no public REST API or GraphQL endpoint. In Phase 3, a public API will be added for:
- User authentication
- Signal pagination and filtering
- User profile updates
- Notification webhook management

Until then, access to signals is internal (via database queries with proper RLS tenant isolation).
