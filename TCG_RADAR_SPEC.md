# TCG Radar — Source of Truth

> **Project:** TCG Radar — Pokémon Card Market Intelligence Engine
> **Status:** Pre-MVP / Architecture Finalized
> **Last Updated:** February 22, 2026
> **Owner:** Operates from Southeast Asia. No physical card handling. No fulfillment partner.

---

## 1. What We Are Building

A **market intelligence platform** for Pokémon TCG resellers that detects profitable cross-platform price spreads, scores them for risk and effort, and delivers actionable signals to paying subscribers.

**We are NOT building a speed-based arbitrage sniper.** Tier-1 chase cards (Charizard, Umbreon, etc.) have a listing survival time of ~15 seconds on open marketplaces. We cannot and will not compete in that game.

**We ARE building a long-tail intelligence engine.** There are 60,000+ unique Pokémon cards. ~500 are watched by every bot and reseller. The other 59,500 are where persistent, low-competition spreads exist — often lasting 24-72 hours.

---

## 2. Core Thesis

Price inefficiencies between TCGPlayer (US/USD) and Cardmarket (EU/EUR) persist on long-tail cards because:

- Nobody is running automated arbitrage on low-hype cards.
- Event-driven spikes (tournament results, rotation, new set reveals) propagate unevenly across regions.
- EU players hold rotated cards longer (Expanded format); US players fire-sell them.
- Regional demand differences create durable spreads.

Our edge is **intelligence breadth** (scanning the entire catalog) and **event prediction** (detecting which cards will move before the price APIs update).

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    LAYER 1: BASELINE SCANNER             │
│  JustTCG API → Full catalog prices (TCGPlayer + CM)      │
│  pokemontcg.io → Card metadata, regulation marks, legality│
│  Storage: PostgreSQL                                      │
│  Cadence: Per JustTCG plan (6hr standard, faster on Pro)  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    LAYER 2: RULES ENGINE                  │
│  Filters applied BEFORE any signal is generated:          │
│  - **Variant ID Validation** (cross-platform card match)  │
│  - Velocity Score (liquidity gate)                        │
│  - Trend Direction (falling knife filter)                 │
│  - Rotation Calendar (regulation mark overlay)            │
│  - Seller Quality Floor (rating ≥97%, sales ≥100)        │
│  - Effective Buy Price (listing + shipping, not raw price)│
│  - Fee-Adjusted Profit (user-specific profile)            │
│  - Headache Score / Labor-to-Loot ratio                   │
│  ALL deterministic. No AI. No tokens burned.              │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                LAYER 3: EVENT PIPELINE                    │
│  Monitors:                                                │
│  - Limitless TCG (tournament results, decklists)          │
│  - Pokémon official site (rotation, bans, new sets)       │
│                                                           │
│  On event detected:                                       │
│  1. Extract affected card names from structured data      │
│  2. Map synergy cards via co-occurrence matrix             │
│  3. Trigger targeted Playwright scrape (10-20 pages only) │
│  4. Compare fresh prices against JustTCG baseline          │
│                                                           │
│  This gives us 4-6 hour lead over API-only tools.         │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│          LAYER 3.5: EARLY WARNING (Social Listening)     │
│  Monitors: Twitter/X, Reddit, Discord (public servers)   │
│  NOT optional. The "information meta" starts here         │
│  2+ hours before structured data hits Limitless TCG.      │
│                                                           │
│  Method: Keyword frequency spike detection.               │
│  When a card name suddenly trends (>5x baseline mention   │
│  rate in a 30-min window), this layer:                    │
│  1. Flags the card as "HIGH ACTIVITY"                     │
│  2. Forces Layer 1 to increase poll cadence for that ID   │
│  3. Triggers Layer 3 targeted scrape immediately          │
│                                                           │
│  This is NOT sentiment analysis. No AI needed.            │
│  It's a simple frequency counter on known card names.     │
│  Cheap, fast, and gives us 2hr lead over Limitless-only.  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                LAYER 4: SIGNAL GENERATION                 │
│  Composite Score = Spread × Velocity × Trend Direction    │
│  Signal includes:                                         │
│  - Card name, set, regulation mark                        │
│  - Fee-adjusted profit (personalized to user profile)     │
│  - Velocity Score + Trend indicator                       │
│  - Headache Score tier (1/2/3)                            │
│  - Effective Buy Price (with seller stats)                │
│  - Deep link to Cardmarket listing                        │
│  - Risk warnings (rotation, liquidation, low liquidity)   │
│                                                           │
│  Delivery: Telegram bot (MVP), Discord (Phase 2)          │
│  Routing: Exclusivity rotation among paying subscribers   │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Key Formulas

### 4.1 Real Profit

```
P_real = (P_target × (1 - F_selling)) - (P_buy_effective × (1 + F_import)) - S_total - C_adj - D_customs
```

- `P_target` = Expected sell price on target platform (adjusted by Condition Mapping, Section 4.6)
- `F_selling` = Seller fee — **tiered function, NOT flat percentage** (see 4.1.1)
- `P_buy_effective` = Listing price + shipping to user's country (NOT raw listing price)
- `F_import` = Import duty/VAT estimate (conservative, user-configurable)
- `S_total` = Total shipping cost (both legs if applicable; amortized per card if Bundle Logic applies, Section 4.5)
- `C_adj` = Currency conversion spread (2% buffer on EUR/USD)
- `D_customs` = Flat customs duty per item (see 4.1.2 — EU July 2026 rule)

**If `P_real < 0.10 × P_buy_effective`, the signal is noise. Do not send.**

#### 4.1.1 TCGPlayer Seller Fee (Feb 10, 2026 Update)

The marketplace commission fee cap increased from $50 to $75. `F_selling` is now:

```
F_selling = min(P_target × 0.1075, 75) + 0.30
```

- 10.75% of sale price, capped at $75, plus $0.30 fixed transaction fee
- This means cards above ~$698 hit the cap. Cards above $500 are taxed more heavily than pre-Feb 2026.
- For eBay: `F_selling = P_target × 0.1325` (no cap change)
- For Cardmarket professional sellers: `F_selling = P_target × 0.05` (approximate, varies by volume tier)

**The user's profile (Section 8) determines which fee schedule applies. Always use their actual seller level.**

#### 4.1.2 EU Customs "July 1st Cliff" (CRITICAL — Effective July 1, 2026)

The EU is removing the €150 de minimis duty-free threshold for low-value e-commerce imports.

**Before July 1, 2026:** Imports under €150 enter the EU duty-free.
**After July 1, 2026:** A flat **€3 customs duty per item** applies regardless of declared value.

**Impact on the Radar:**

This kills per-item cross-border arbitrage on low-value cards. A user buying 20 separate €5 cards from different US sellers gets hit with €60 in flat duties — destroying every margin.

**Implementation rules:**

- After July 1, 2026: Add `D_customs = €3 × item_count` to every EU-bound signal
- **Bundle Logic (Section 4.5) becomes MANDATORY for EU users**, not optional. Consolidated shipments from a single seller = one customs declaration = one €3 fee instead of twenty
- Signals to EU users for sub-€20 single-card purchases from non-EU sellers must be suppressed unless `SDS >= 3` (bundle of 3+ cards from same seller)
- Add "Forwarder Consolidation" flag: prioritize sellers located near US export hubs (Oregon, Delaware — no state sales tax) where consolidation forwarding services operate

**Forwarder Fee Constants (when Forwarder Consolidation flag is active):**

Forwarders in Oregon/Delaware save 8-10% US sales tax, but they are not free. `S_total` must include these when the forwarder flag is on:

```
F_receiving    = $3.50   # per-package receiving fee (typical range $2-$5)
F_consolidation = $7.50  # per-box consolidation fee (typical range $5-$10)
F_insurance    = P_buy_effective × 0.025  # 2.5% of declared value (typical range 2-3%)
F_forwarder    = F_receiving + F_consolidation + F_insurance

# Amortized across bundle:
S_forwarder_per_card = (F_receiving + F_consolidation) / SDS + F_insurance_per_card
# Note: insurance is per-card value, not per-package — cannot be amortized
```

**The Insurance Deadzone:** Cards in the $50-$150 range are in a deadzone — too expensive to ship uninsured (risk of $50-$150 loss), but the 2.5% insurance premium ($1.25-$3.75) meaningfully erodes thin margins. The Rules Engine must include `F_insurance` in `P_real` whenever the forwarder flag is active AND `P_buy_effective > $30`. Below $30, most users accept the risk uninsured.

These are user-configurable constants in the profile (Section 8) since different forwarders charge differently. Defaults are set to the **pessimistic midpoint** of 2026 market rates.

**Critical margin check:** If a user is flipping a $15 card and the forwarder adds $11 in fees before shipping even starts, the signal is dead. The Rules Engine must calculate `P_real` inclusive of `S_forwarder_per_card` and suppress if negative.

**Before July 1, 2026:** Apply current de minimis rules. After: switch to flat duty model. This should be a **date-triggered config flag**, not a code change.

**The system must include a `CUSTOMS_REGIME` config variable:**
```
CUSTOMS_REGIME = "pre_july_2026"  # switches to "post_july_2026" on 2026-07-01
```

### 4.2 Velocity Score

```
V_s = (Sales_30d / Active_Listings) × Confidence_Factor × Maturity_Decay
```

- `V_s > 1.5` → "Liquid Gold" — route to premium tier
- `0.5 < V_s < 1.5` → "Standard Flip" — route to mid tier
- `V_s < 0.5` → "Bagholder Risk" — only send as investment alert, never as arbitrage signal

#### 4.2.1 Staleness Penalty (Ghost Listings)

**Problem:** JustTCG and other API sources cache prices. Long-tail cards on TCGPlayer suffer from "Ghost Listings" — items that have sold but remain in the API cache for hours. A signal based on stale data sends users to buy a card that no longer exists at that price.

```
Staleness_Penalty:
  Data age < 1 hour:    1.0 (fresh — full confidence)
  Data age 1-2 hours:   0.95
  Data age 2-4 hours:   0.85 (apply -15% penalty)
  Data age > 4 hours:   0.70 (low confidence — flag as "STALE DATA, VERIFY MANUALLY")
```

**Implementation:** Check `market_prices.last_updated` against `now()`. Apply penalty as multiplier on `V_s`. When staleness exceeds 4 hours, the signal should trigger a Layer 3 targeted Playwright scrape for ground truth before being sent to the user. The API price is treated as a hypothesis; the live scrape confirms or kills the signal.

```
V_s = (Sales_30d / Active_Listings) × Confidence_Factor × Maturity_Decay × Staleness_Penalty
```

#### 4.2.2 Maturity Penalty (Hype Decay)

New sets and anniversary products have artificially inflated velocity during their hype window. This decays predictably.

```
Maturity_Decay:
  Set age < 30 days:   1.0 (no penalty — but flag as "HYPE WINDOW, HIGH VOLATILITY")
  Set age 30-60 days:  0.9 (minor decay)
  Set age 60-90 days:  0.8 (hype fading)
  Set age > 90 days:   0.7 (normalized market)

If reprint_rumored = true AND set_age > 60 days:
  Apply additional -20% decay (multiply by 0.8)
```

**Current alert (Feb 2026):** The Pokémon 30th Anniversary peak is February 27, 2026. Ascended Heroes cards will have artificially high `V_s` through March. By mid-April (~45 days post-launch), expect a ~30% liquidity dry-up consistent with historical anniversary set patterns. The Maturity Penalty must be active before this date.

**Implementation:** Set release dates are available via pokemontcg.io API (`set.releaseDate`). Calculate `set_age = today - set.releaseDate`. Apply decay multiplier. The `reprint_rumored` flag is manual — set by admin when credible reprint announcements or leaks surface.

### 4.3 Trend-Adjusted Velocity (Falling Knife Filter)

```
If V_s > 1.0 AND price_7d_trend < -10%/day → FLAG: "Post-Rotation Liquidation"
```

Classification matrix:

| Velocity | Price Trend | Signal Type |
|----------|-------------|-------------|
| High | Stable/Rising | ✅ Genuine arbitrage |
| High | Falling | ⛔ Liquidation — suppress signal |
| Low | Rising | ⚠️ Speculative spike — caution flag |
| Low | Falling | 🚫 Dead card — ignore |

### 4.4 Headache Score (Labor-to-Loot)

```
H = Net_Profit / Number_of_Transactions
```

- `H > 15` → Tier 1 signal (one card, easy money)
- `5 < H < 15` → Tier 2 signal (a few cards, decent)
- `H < 5` → Tier 3 signal (bulk deal, high labor)

Users configure their minimum Headache Score threshold.

### 4.5 Seller Density Score (Bundle Logic)

**Problem:** Shipping a single $10 long-tail card from EU to US costs $12-$18 with tracking. This kills any per-card spread on cards under ~$25 unless the user buys multiple cards from the same seller, amortizing shipping across the bundle.

```
SDS = Count of high-velocity cards in stock from a single Cardmarket seller
      that appear on the user's watchlist or match active signal criteria
```

- `SDS >= 5` → **"Bundle Alert"** — signal highlights the seller, not just one card. Message: "Seller X has 7 cards from your radar. Combined spread after shared shipping: $XX profit."
- `SDS = 2-4` → Include in signal but note: "Partial bundle. Check seller for additional cards."
- `SDS = 1` → **Apply single-card shipping cost to profit calculation.** If `P_real` goes negative after full shipping, suppress signal entirely.

**Implementation:** When Layer 2 detects a spread on a long-tail card (under $25), before generating a signal, query the seller's full available stock against the user's watchlist and current active spread list. Aggregate shipping cost across the bundle. Recalculate `P_real` using `S_total = S_single_shipment / SDS` (shared shipping per card).

**This is critical for the long-tail strategy.** Without bundle logic, most sub-$25 card signals will be unprofitable after shipping and the tool becomes useless for exactly the market segment we're targeting.

### 4.6 Condition Mapping Layer (Cross-Platform Grade Translation)

**Problem:** "Near Mint" means different things on different platforms. Cardmarket uses a more granular scale (Mint / Near Mint / Excellent / Good / Light Played / Played / Poor). TCGPlayer uses (Near Mint / Lightly Played / Moderately Played / Heavily Played / Damaged). A Cardmarket "Excellent" card is frequently rejected as "Lightly Played" on TCGPlayer, leading to returns and "Item Not As Described" disputes.

**Mandatory pessimistic mapping (Cardmarket → TCGPlayer):**

| Cardmarket Grade | Maps To (TCGPlayer) | Price Adjustment |
|------------------|---------------------|------------------|
| Mint | Near Mint | None |
| Near Mint | Near Mint | None |
| Excellent | **Lightly Played** | **Apply -15% price penalty to P_target** |
| Good | Moderately Played | Apply -25% price penalty to P_target |
| Light Played | Moderately Played | Apply -25% price penalty to P_target |
| Played | Heavily Played | Apply -40% price penalty to P_target |
| Poor | Damaged | Do not generate signal |

**Rule:** When calculating `P_real`, always use the TCGPlayer-equivalent condition price for `P_target`, not the NM price. If a Cardmarket listing is "Excellent," the sell price estimate must be the TCGPlayer LP price, not the NM price.

**If this mapping is not enforced, users will face high return rates and trust in the platform collapses.**

### 4.7 Variant ID Validation (Cross-Platform Card Identity)

**Problem:** Some Pokémon cards are released in English on both US and EU markets but with different set codes, promo stamps, or regional exclusivity (e.g., GameStop exclusive promo vs. standard print, Build & Battle promo vs. booster pull). The JustTCG API may surface a "spread" between two listings that are actually *different versions of the same card* with legitimately different prices.

**Example:** A "Charizard ex" promo with a GameStop stamp listed at $15 on TCGPlayer vs. a standard "Charizard ex" at €25 on Cardmarket is not a $12 arbitrage opportunity — they're different products with different collector demand.

**Rule (FIRST check in Layer 2, before any other filter):**

When Layer 1 detects a spread, before calculating `P_real` or any other score:

1. Extract the `pokemontcg.io` card ID from both sides of the spread
2. Verify the IDs match exactly (same set code, same card number, same variant)
3. If IDs don't match or can't be resolved → **suppress signal, flag as "VARIANT MISMATCH"**
4. If the JustTCG record doesn't include enough granularity to distinguish variants, trigger a Layer 3 targeted scrape to visually confirm the listings are the same card

**Implementation:**

```
# Canonical ID format from pokemontcg.io: "{set_code}-{card_number}"
# Example: "sv1-25" = Scarlet & Violet base set, card #25

def validate_variant(tcgplayer_id, cardmarket_id):
    if tcgplayer_id != cardmarket_id:
        return "VARIANT_MISMATCH"  # suppress signal
    return "MATCH"  # proceed to Layer 2 filters
```

Known mismatch categories to watch for:
- Promo stamps (GameStop, Pokémon Center, Build & Battle)
- Regional exclusive prints
- Reverse holo vs. standard holo (different SKUs, different prices)
- First edition / unlimited (older sets)
- Japanese vs. English prints with same card art

**This check must run FIRST in Layer 2. A false spread from a variant mismatch poisons every downstream calculation.**

---

## 5. Data Sources

### Primary APIs (Legitimate, Authorized)

| Source | Purpose | Access |
|--------|---------|--------|
| **JustTCG API** | Cross-market prices (TCGPlayer USD + Cardmarket EUR), graded values, price history | RapidAPI key, free tier available |
| **pokemontcg.io** | Card metadata, regulation marks, legality, set info, TCGPlayer/Cardmarket base prices | Free API key |
| **PokeTrace API** | WebSocket real-time price updates, eBay sold data, PSA/BGS/CGC graded values | API key, free tier |
| **eBay Browse API** | US market price discovery, sold listings | OAuth, requires eBay developer approval |

### Secondary / Event Sources

| Source | Purpose | Method | Layer |
|--------|---------|--------|-------|
| **Limitless TCG** | Tournament results, decklists | Structured data scrape or RSS | Layer 3 |
| **Pokémon official site** | Rotation dates, ban lists, new set announcements | Scrape/RSS | Layer 3 |
| **Twitter/X** | Early hype detection, card name frequency spikes | Keyword frequency monitoring (>5x baseline = trigger) | **Layer 3.5** |
| **Reddit** (r/pkmntcg, r/pokemontcg) | Community sentiment, early meta discussion | Keyword frequency monitoring | **Layer 3.5** |
| **Discord** (public TCG servers) | Fastest source of tournament chatter | Keyword frequency monitoring | **Layer 3.5** |

### Dead Ends (DO NOT USE)

| Source | Reason |
|--------|--------|
| **TCGPlayer API (direct)** | No longer granting new API access as of 2025 |
| **Cardmarket API (direct)** | Restricted access; TOS prohibits competitive use of scraped data |

---

## 6. Scraping Architecture (Cardmarket Targeted Checks)

### When to Scrape
Only when Layer 3 Event Pipeline triggers. Never continuous. Never catalog-wide. Target: 10-20 specific product pages per event.

### Extraction Priority Order

1. **Network Interception via `page.route`** (ALWAYS preferred): Use Playwright's `page.route('**/api/**', ...)` to intercept Cardmarket's internal API calls. When a product page loads, the browser fetches listing data via XHR/Fetch. Intercept the raw JSON payload from the server. This is **100x more stable than DOM scraping** — it bypasses all UI changes, Shadow DOM, Web Components, and obfuscation. The server response format changes far less frequently than the front-end markup. This should be the default and only method unless Cardmarket changes their internal API architecture.
2. **Deep CSS Selectors** (backup only): Use Playwright's `>>` piercing combinator for Shadow DOM. Example: `page.locator('card-listing >> .price-value')`. Note: As of late 2025, major TCG sites use Open and Closed Shadow Roots. Standard selectors — even with `>>` — may fail on Closed roots. Only use this if network interception is unavailable.
3. **Screenshot + Vision** (emergency fallback): AI reads price from a static screenshot. Slowest, costs tokens, but unkillable regardless of DOM structure. Reserve for cases where both methods above have failed.

**Critical note from Gemini review:** Do NOT rely on CSS selectors as a primary method. DOM structures change frequently. Network interception is the correct default. If Claude Code is writing the scraping module, `page.route` interception must be implemented first, with CSS selectors as fallback only.

### Data Points Extracted Per Listing

- Price (number)
- Seller rating (percentage)
- Seller sale count (number)
- Card condition — **raw platform value** (Cardmarket enum: MT/NM/EXC/GD/LP/PL/PO)
- Card condition — **mapped to TCGPlayer equivalent** (see Section 4.6 Condition Mapping Layer)
- Shipping cost to user's target region (number)
- Effective Buy Price = price + shipping
- **Seller stock list** (other cards from same seller — required for Bundle Logic, Section 4.5)

### Anti-Detection

- Docker container with clean browser fingerprint
- Residential proxy rotation
- Random delays: 2-8 seconds between actions
- Max 20-30 page visits per hour
- Session cookies maintained like a real user
- Randomized viewport sizes and user agents

### Security (CRITICAL)

**CVE-2026-25253 (OpenClaw RCE, CVSS 8.8):** Affects all OpenClaw versions before 2026.1.29. Remote code execution via WebSocket token exfiltration.

**Mandatory rules:**
- The AI agent NEVER receives live DOM content or free-text seller descriptions.
- The AI agent ONLY receives: structured data (numbers/enums from CSS selectors or network interception) OR static screenshots.
- This is a "read-only vision sandbox." The AI can look at images but never interacts with or parses raw page HTML.
- If using OpenClaw, minimum version 2026.1.29.
- For our constrained use case, a plain Playwright script with CSS selectors is preferred over a full AI agent.

---

## 7. Rotation Calendar

Hard-coded, updated manually when Pokémon announces changes.

| Regulation Mark | Sets Included | Rotation Date | Status |
|-----------------|---------------|---------------|--------|
| G | SV Base → Paldean Fates | April 10, 2026 | ⚠️ DEATH SPIRAL — suppress arbitrage signals 6 weeks prior |
| H | Temporal Forces → current | Not yet announced | ✅ Standard legal |

**Implementation:** pokemontcg.io API returns `regulationMark` per card. Cross-reference against this table. Any G-mark card between now and April 10, 2026 gets automatic `ROTATION_WARNING` flag. Signals suppressed unless spread exceeds 40%.

---

## 8. User Profile System

Each subscriber has a profile that personalizes every signal:

- **Country** → determines import duties, VAT rate, shipping estimates
- **Seller level** → TCGPlayer Level 1-4, eBay standard/Top Rated, Cardmarket private/professional
- **Preferred platforms** → which platforms they sell on (affects fee calculation)
- **Minimum profit threshold** → below this, no signal sent
- **Minimum Headache Score** → below this tier, no signal sent
- **Card category preferences** → vintage, modern competitive, Japanese, sealed product
- **Currency** → display preference (USD/EUR)

---

## 9. Synergy Spike Detection

**Purpose:** When a new card is revealed or wins a tournament, identify the *support cards* (long tail) that will spike, not just the obvious headliner.

**Method:**
1. Maintain a co-occurrence matrix from historical Limitless TCG decklists.
2. When event detected, extract card names from structured decklist data.
3. Query co-occurrence matrix: "Which existing cards most frequently appear alongside cards of this type/archetype?"
4. Output a ranked list of 10-20 synergy targets.
5. Trigger Layer 3 targeted price checks on those cards.

**Data seeding:** Requires importing 6+ months of Limitless TCG decklists before this feature is reliable. Phase 2 feature.

---

## 10. Revenue Model

| Tier | Price | Signals | Features |
|------|-------|---------|----------|
| **Free** | $0 | Weekly digest (top 10 spreads, 24-48hr delayed) | Educational, funnel to paid |
| **Trader** | $25/mo | Daily signals, personalized fees, Velocity Scores | Core offering |
| **Pro** | $75/mo | Real-time signals, event-driven alerts, API access, portfolio tracking | Power users |
| **Shop** | $200/mo | Bulk repricing intelligence, unlimited signals, priority rotation | LGS / high-volume sellers |

**Signal Routing:** Signals are not broadcast to all users. They route through an exclusivity rotation. Higher-tier users get first-pick priority. Users who don't act on signals drop in rotation priority. Category preferences reduce competition per signal to ~3-8 users.

---

## 11. Build Phases

### Phase 1: MVP (Weeks 1-6)

- **Weeks 1-2:** JustTCG API + pokemontcg.io integration. PostgreSQL database. Basic spread calculator with fee adjustment.
- **Weeks 3-4:** Rules engine (Velocity Score, trend direction, rotation calendar, seller quality floor, Effective Buy Price, Headache Score).
- **Weeks 5-6:** Telegram bot for signal delivery. Basic user profiles. Manual testing against real market data.

**MVP validates:** Do actionable long-tail spreads exist at sufficient frequency? Do users find the signals useful?

### Phase 2: Event Intelligence (Weeks 7-12)

- **Layer 3.5 Social Listening** (Twitter/X, Reddit, Discord keyword frequency monitoring). Simple frequency counter — no AI, no sentiment analysis. This is an early priority because it provides the 2-hour lead over Limitless-only tools.
- Limitless TCG monitoring and decklist parsing.
- Targeted Playwright scraping for event-affected cards.
- Synergy spike detection (co-occurrence matrix).
- Paid tier system with exclusivity rotation.
- Discord bot delivery.

### Phase 3: Scale (Months 4-6)

- Additional TCGs (Magic: The Gathering, Yu-Gi-Oh!, One Piece TCG).
- API access for Pro/Shop tier subscribers.
- Dashboard / web interface.
- Mobile push notifications.

---

## 12. Known Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| JustTCG price data is 6hrs stale | Miss event-driven spikes | Event pipeline with targeted scraping fills the gap |
| Cardmarket changes DOM structure | Scraping breaks | Three-layer fallback: network interception → CSS → vision |
| Shadow DOM / Web Components | CSS selectors return null | Playwright deep selectors (`>>`) or network interception bypass DOM entirely |
| Bot bait listings (honeypot traps) | User accounts banned | Seller quality floor (≥97% rating, ≥100 sales) filters out bait listings |
| Post-rotation fire sales misread as deals | Users buy depreciating cards | Rotation calendar + trend-adjusted velocity filter |
| Signal decay from too many subscribers | Signals become unactionable | Exclusivity rotation + category segmentation limits competition to 3-8 users per signal |
| CVE-2026-25253 (OpenClaw RCE) | System compromise via prompt injection | Vision sandbox only; AI never receives DOM/free-text; use Playwright scripts, not full AI agents |
| Fee structure changes (TCGPlayer Feb 2026 update) | Profit calculations become wrong | Fee database is a configurable lookup table, updated when platforms announce changes |
| EUR/USD volatility | Currency conversion eats margin | 2% buffer on all forex calculations; use real-time rate, not stale |
| Single-card shipping kills long-tail margins | $12-18 shipping on a $10 card = no profit | Bundle Logic (Section 4.5): Seller Density Score aggregates multiple cards per seller, amortizing shipping. Suppress single-card signals under $25 if shipping makes P_real negative |
| Condition grade mismatch across platforms | Cardmarket "Excellent" ≠ TCGPlayer "Near Mint" → returns and disputes | Condition Mapping Layer (Section 4.6): Pessimistic mapping with price penalties. "Excellent" always treated as LP (-15%) |
| DOM scraping breaks on Shadow DOM / Web Components | CSS selectors return null on Closed Shadow Roots | Network interception via `page.route` is the default method; DOM scraping is fallback only (Section 6) |
| EU July 2026 customs cliff | €3 flat duty per item kills per-card cross-border margins | Bundle Logic mandatory for EU users post-July; suppress single-card sub-€20 signals; `CUSTOMS_REGIME` config flag (Section 4.1.2) |
| 30th Anniversary hype decay | Users buy into crashing market 45+ days post-launch | Maturity Penalty decays V_s by set age; reprint rumor flag applies additional -20% (Section 4.2.1) |
| TCGPlayer Feb 2026 fee cap increase ($50→$75) | Grail card margins shrink | F_selling is now a tiered function with cap: `min(P_target × 0.1075, 75) + 0.30` (Section 4.1.1) |
| Signal sniffing / timing attacks between tenants | Sophisticated user infers competitors' signals from DB timestamps | Decoupled Signal Tables with tenant-level RLS + audit log (Section 14) |
| Ghost listings in API cache | User tries to buy a card that's already sold | Staleness Penalty on V_s (Section 4.2.1); auto-trigger Layer 3 live scrape when data > 4hrs old |
| Exclusivity cascade race condition | Two users get same signal due to message delivery latency | 10-second cooldown buffer between expiry and cascade; `cascade_count` limit of 5 (Section 14) |
| Forwarder fees eating margins on low-value cards | $11+ forwarder overhead kills sub-$25 card profits | Forwarder fee constants in S_total; user-configurable; Rules Engine suppresses if P_real goes negative after forwarder fees (Section 4.1.2) |
| Regional variant ID mismatch | False spread from comparing different card versions (promo vs standard) | Variant ID Validation runs FIRST in Layer 2; exact pokemontcg.io ID match required; mismatches suppressed (Section 4.7) |

---

## 13. Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Database | PostgreSQL |
| Price APIs | JustTCG, pokemontcg.io, PokeTrace |
| Browser automation | Playwright (headless Chromium) |
| Containerization | Docker |
| Signal delivery | Telegram Bot API (MVP), Discord (Phase 2) |
| Hosting | VPS (event pipeline + scraping), can be lightweight for MVP |
| AI (when needed) | Claude API or local model for vision verification only |

---

## 14. Database Architecture & Signal Security

### The Problem: Signal Sniffing

In a multi-tenant SaaS where exclusivity windows are the product, standard Row-Level Security is not enough. If User A and User B both target the same card, a sophisticated User B could monitor timestamps on shared tables to infer when a deal was found — even without seeing User A's specific signals.

### Solution: Decoupled Signal Tables

**Layer A — Global Market Data (shared, read-only for all):**

```sql
-- Raw price data from APIs. No signal logic. No tenant data.
CREATE TABLE market_prices (
    card_id         TEXT NOT NULL,
    source          TEXT NOT NULL,  -- 'justtcg', 'pokemontcg', 'poketrace'
    price_usd       DECIMAL(10,2),
    price_eur       DECIMAL(10,2),
    condition       TEXT,
    last_updated    TIMESTAMP DEFAULT now(),
    PRIMARY KEY (card_id, source)
);
-- No RLS needed. This is public market data.
```

**Layer B — Tenant-Specific Signal Buffer (private per user):**

```sql
-- Each user has their own signal queue. No cross-tenant visibility.
CREATE TABLE signals (
    signal_id       UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES users(id),
    card_id         TEXT NOT NULL,
    signal_type     TEXT NOT NULL,  -- 'arbitrage', 'event_driven', 'bundle', 'investment'
    spread_pct      DECIMAL(5,2),
    p_real          DECIMAL(10,2),  -- fee-adjusted profit for THIS user
    velocity_score  DECIMAL(5,2),
    headache_tier   INT,
    condition_mapped TEXT,          -- TCGPlayer-equivalent condition
    seller_density  INT,            -- SDS for bundle logic
    risk_flags      TEXT[],         -- ['ROTATION_WARNING', 'HYPE_DECAY', 'UNVERIFIED']
    deep_link       TEXT,
    created_at      TIMESTAMP DEFAULT now(),
    expires_at      TIMESTAMP,      -- exclusivity window end
    acted_on        BOOLEAN DEFAULT false
);

-- RLS Policy: Users can ONLY see their own signals
ALTER TABLE signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON signals
    FOR SELECT TO authenticated
    USING (tenant_id = current_user_id());
CREATE POLICY tenant_insert ON signals
    FOR INSERT TO service_role
    WITH CHECK (true);  -- only backend can insert
```

**Layer C — Audit Log (append-only, admin access only):**

```sql
-- Reconstructs exactly what the bot saw when a signal was generated.
-- Used for dispute resolution ("your signal was a false positive").
CREATE TABLE signal_audit (
    audit_id        UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    signal_id       UUID NOT NULL REFERENCES signals(signal_id),
    snapshot_data   JSONB NOT NULL,  -- full market state at signal time
    source_prices   JSONB NOT NULL,  -- raw API/scrape values used
    fee_calc        JSONB NOT NULL,  -- full fee breakdown for this user
    created_at      TIMESTAMP DEFAULT now()
);
-- No RLS. Admin/service role access only. Never exposed to users.
```

### Key Rules

- The **signal generation engine** (backend) writes to all three layers.
- **Users only query Layer B** (their own signals) through the Telegram/Discord bot or future web dashboard.
- **Layer A timestamps** do not leak signal timing because market prices update on a fixed cadence (JustTCG poll cycle), not when signals are generated.
- **Layer C** is the source of truth for disputes. If a user claims a verified signal was wrong, pull the `signal_audit` row and show exactly what data the system had.
- **Exclusivity windows** are enforced via `expires_at` on the signals table. The backend assigns signals to users in rotation order and sets the expiry. If `acted_on` remains false after expiry, the signal cascades to the next user in rotation.

#### Exclusivity Cascade: Cooldown Buffer

**Problem:** If the backend cascades a signal to User B at the exact millisecond `expires_at` passes for User A, message delivery latency (Telegram API: 200-800ms typical, up to 2-3s under load) can cause both users to receive the notification and attempt to buy simultaneously. This breaks the exclusivity promise.

**Fix:** Implement a **10-second cooldown buffer** between signal expiry for User A and visibility for User B.

```
cascade_available_at = expires_at + INTERVAL '10 seconds'
```

The backend cascade job runs on a 5-second polling interval. When checking for expired signals:

```sql
-- Only cascade signals that have passed the cooldown buffer
SELECT * FROM signals
WHERE acted_on = false
  AND expires_at + INTERVAL '10 seconds' < now()
  AND cascade_count < max_cascade_limit;
```

Additionally, add `cascade_count` (INT, default 0) to the signals table. Increment on each cascade. Set a `max_cascade_limit` (default: 5) — if a signal bounces through 5 users without action, it either gets demoted to the free tier digest or is discarded. A signal nobody acts on is not a good signal.

---

## 15. What This Document Is For

This is the **single source of truth** for the TCG Radar project. When Claude Code has a question about:

- What are we building? → Section 1-2
- How does the architecture work? → Section 3
- How do we calculate profit? → Section 4 (incl. 4.1.1 fee tiers, 4.1.2 customs cliff + forwarder fees, 4.2.1 staleness penalty, 4.2.2 maturity penalty)
- How do bundle signals work? → Section 4.5
- How do condition grades map cross-platform? → Section 4.6
- How do we verify cards match across platforms? → Section 4.7
- Where does the data come from? → Section 5
- How do we scrape safely? → Section 6
- What's the rotation situation? → Section 7
- How do signals get personalized? → Section 8
- What's the business model? → Section 10
- What should I build next? → Section 11
- What could go wrong? → Section 12
- What's the tech stack? → Section 13
- How is the database structured? → Section 14

**Do not deviate from this spec without explicit discussion and approval.**
