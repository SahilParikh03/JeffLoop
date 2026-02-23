# TCG Radar — Phase 3 Complete

**Date:** 2026-02-23
**Tests:** 418 passing (401 Phase 1+2 + 17 Phase 3)
**All CI checks:** ruff, mypy, pytest

---

## Phase 3 Deliverables

### 1. Real-Time Forex API (src/utils/forex.py)
- `get_current_forex_rate()` converted from sync to `async`
- 15-minute in-memory cache (`_forex_cache` module-level dict)
- Live API: `GET {EXCHANGERATE_API_URL}/{EXCHANGERATE_API_KEY}/latest/EUR`
- 2% pessimistic buffer applied to raw rate (`raw × 0.98`)
- Graceful fallback to `settings.EUR_USD_RATE` on any error or missing key
- `src/signals/generator.py` updated: `await get_current_forex_rate()`
- 5 new tests in `TestGetCurrentForexRateLiveAPI` (cache hit, cache miss, API error, empty key, buffered rate)

### 2. Twitter/X Adapter (src/events/social_listener.py)
- `TwitterAdapter` class added, implements `PlatformAdapter` protocol
- Twitter API v2 recent search: `https://api.twitter.com/2/tweets/search/recent`
- Gated behind `settings.TWITTER_BEARER_TOKEN` — returns `[]` if empty
- `subreddit="twitter"` for drop-in compatibility with `SocialListener.scan_for_spikes()`
- Per-keyword API calls, graceful per-keyword error handling
- 7 new tests in `TestTwitterAdapterFetchMentions`

### 3. Vision Fallback — Claude Vision (src/scraper/vision_fallback.py)
- Phase 3 stub replaced with full Claude Vision implementation
- Base64 screenshot → `anthropic.AsyncAnthropic.messages.create` with image block
- SECURITY: Only image bytes sent — NO DOM text (CVE-2026-25253 boundary preserved)
- Uses `settings.VISION_MODEL_ID` and `settings.ANTHROPIC_API_KEY`
- Returns `ScraperResult(scrape_method="vision")` on success
- Graceful: API key guard, JSON parse error catch, all fields null-safe
- `anthropic>=0.40.0` added to `[project] dependencies` in pyproject.toml
- 5 new tests in `TestVisionFallback`

### 4. CI/CD Pipeline (.github/workflows/ci.yml)
- Pure Python GitHub Actions workflow (no Node.js/bun/npm)
- Steps: checkout → Python 3.11 setup → pip install → ruff lint → mypy → pytest → codecov
- All API keys as empty env vars (tests use mocks)
- Triggers on push/PR to main

### 5. Type Checking (pyproject.toml)
- `mypy>=1.0` added to dev dependencies
- `[tool.mypy]` section: `disallow_untyped_defs = true`, `check_untyped_defs = true`, `warn_return_any = true`
- `strict = false`, `ignore_missing_imports = true`
- Excludes `tests/` and `alembic/`
- All source files already compliant — no code changes required

### 6. Documentation (docs/)
- `docs/DEPLOYMENT.md` — prerequisites, quick start, env vars reference, migration procedure, feature flags, scraping setup, production checklist
- `docs/API.md` — signal schema, RLS query patterns, user profile fields, Telegram/Discord delivery, rate limits, risk flags, error codes

---

## pyproject.toml Final State
```toml
[project] dependencies: added anthropic>=0.40.0
[project.optional-dependencies] dev: added mypy>=1.0
[tool.mypy]: new section with type checking config
```

---

## Cross-Cutting Fix
`src/signals/generator.py` line 128: `get_current_forex_rate()` → `await get_current_forex_rate()`
(Required because the function became async in Phase 3.)

---

## Test Count by Phase
| Phase | Tests Added | Running Total |
|-------|------------|---------------|
| Phase 1 | 260 | 260 |
| Phase 2 | 141 | 401 |
| Phase 3 | 17 | 418 |
