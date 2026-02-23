# Maturity & Rotation Engine Modules — Complete

**Date:** 2026-02-22  
**Status:** Production-Ready  
**Tests:** 48/48 passing

## Summary

Created two critical engine modules that were missing from the Signal Generator pipeline:
1. **Maturity Decay** — Models hype decay over time (Section 4.2.2)
2. **Rotation Risk** — Assesses rotation threats based on regulation marks (Section 7)

Now the generator can call real implementations instead of placeholders.

---

## 1. src/engine/maturity.py (135 lines)

Function: `calculate_maturity_decay(set_release_date: date, reference_date: date | None = None) -> Decimal`

### Decay Bands (per spec Section 4.2.2):
- **< 30 days:** 1.0 (FRESH — flag as HYPE WINDOW)
- **30-60 days:** 0.9 (YOUNG — minor decay)
- **60-90 days:** 0.8 (MATURING — hype fading)
- **> 90 days:** 0.7 (NORMALIZED — market equilibrium)

### Special Cases:
- **Future release dates:** Return 1.0 (no penalty)
- **Reprint rumors:** Additional -20% penalty if `reprint_rumored=True` AND set_age > 60 days
  - Result: base_decay × 0.8
  - Models market anticipation of reprints

### Example Timeline (Feb 27, 2026 30th Anniversary):
```
Feb 22: 1.0 (fresh, no release yet)
Mar 1-13: 1.0 (hype window)
Mar 14-Apr 12: 0.9 (young set, minor decay)
Apr 13-May 12: 0.8 (maturing, hype fading)
May 13+: 0.7 (normalized)
With reprint rumor + 60+ days: 0.7 × 0.8 = 0.56
```

### Usage in Generator:
```python
maturity_multiplier = calculate_maturity_decay(
    set_release_date=card_metadata.release_date,
    reference_date=datetime.utcnow().date()
)
# Apply to velocity: V_s *= maturity_multiplier
```

---

## 2. src/engine/rotation.py (216 lines)

Function: `check_rotation_risk(regulation_mark: str | None, legality_standard: str | None, reference_date: date | None = None) -> dict[str, Any]`

### Return Structure:
```python
{
    "at_risk": bool,                       # True if suppression advised
    "risk_level": str,                     # SAFE, WATCH, DANGER, ROTATED, UNKNOWN
    "months_until_rotation": int | None,   # Approximate months
    "rotation_date": date | None           # Expected rotation date
}
```

### Risk Levels:
- **SAFE:** >180 days (>6 months) until rotation, or no announced rotation (H mark)
- **WATCH:** 90-180 days (3-6 months) until rotation
- **DANGER:** <90 days (<3 months) until rotation
- **ROTATED:** Already rotated or legality_standard == "Banned"
- **UNKNOWN:** regulation_mark is None

### Regulation Mark Reference:
From Section 7 ROTATION_CALENDAR:
- **H** (current, Spring 2026): No announced rotation date → SAFE
- **G** (Spring 2025): Rotates April 10, 2026 → Currently DANGER (47 days, Feb 22, 2026)
- **F, E, D** (older): Not in calendar → Assumed ROTATED
- **I** (future): Not yet defined

### Current Situation (Feb 22, 2026):
- G-mark cards: DANGER (47 days to rotation on April 10)
- H-mark cards: SAFE (current legal, no rotation announced)
- F/E/D-mark cards: ROTATED (already out of standard legal)

### Secondary Function:
`get_mark_distance_from_current(regulation_mark: str | None) -> int | None`
- Returns distance from "H" in mark order: [D, E, F, G, H, I]
- H = 0, G = 1, F = 2, etc.
- Useful for legacy systems that categorize by mark distance

### Usage in Generator:
```python
rotation_risk = check_rotation_risk(
    regulation_mark=card_metadata.regulation_mark,
    legality_standard=card_metadata.legality,
    reference_date=datetime.utcnow().date()
)

if rotation_risk["at_risk"]:
    # Tag signal as DANGER/WATCH or suppress entirely
    signal["rotation_tag"] = rotation_risk["risk_level"]
    if rotation_risk["risk_level"] == "ROTATED":
        skip_signal = True
```

---

## Test Coverage

### test_maturity.py (21 tests, all passing):

**TestMaturityDecay class:**
1. Fresh set under 30 days → 1.0
2. Fresh set 1 day old → 1.0
3. Exactly 30 days boundary → 0.9 (not 1.0!)
4. 30-60 day band → 0.9
5. 45 days (middle) → 0.9
6. Exactly 60 days → 0.8
7. 60-90 day band → 0.8
8. 75 days (middle) → 0.8
9. Exactly 90 days → 0.7
10. Over 90 days → 0.7
11. 180+ days → 0.7
12. Future date → 1.0
13. Far-future date → 1.0
14. Default to today() → Works
15. 30th Anniversary scenario (Feb 27 launch)

**TestReprintRumorPenalty class:**
16. No rumor = base decay unchanged
17. Rumor under 60 days = no penalty
18. Rumor over 60 days = -20% (0.8 × 0.8 = 0.64)
19. Rumor at exactly 60 days = no penalty (> not >=)
20. Rumor at 61 days = penalty applied
21. Fresh set with rumor = no penalty yet

### test_rotation.py (27 tests, all passing):

**TestCheckRotationRisk class:**
1-2. Banned cards → ROTATED
3. None mark → UNKNOWN
4. H mark → SAFE
5. G mark >6 months away → SAFE
6. G mark 3-6 months away → WATCH
7. G mark <3 months away → DANGER
8-9. Boundary at 180 days
10-11. Boundary at 90 days
12. G after rotation date → ROTATED
13. G long past rotation → ROTATED
14. Unknown mark (F) → ROTATED
15. Default to today()
16-17. Realistic scenarios (Apr 30, Feb 22)

**TestMarkDistance class:**
18. H distance = 0
19. I distance = 0
20. G distance = 1
21. F distance = 2
22. E distance = 3
23. D distance = 4
24. None → None
25. Invalid → None
26. Mark order correct

**TestIntegration class:**
27. Full lifecycle of G-mark card (Feb 22 → Apr 11)
28. H mark always SAFE

---

## Code Quality

**All standards met:**
✓ Type hints on every function signature  
✓ structlog for all logging (decay_band, risk_level, days_until, etc.)  
✓ No magic numbers — all constants from src/config  
✓ Under 300 lines per file (135 and 216 lines)  
✓ Comprehensive docstrings  
✓ Decimal for financial values  
✓ Production-ready error handling  
✓ Testable with realistic date scenarios  

**Per CLAUDE.md:**
- Sonnet 4.5 model appropriate for rules engine logic ✓
- References spec sections explicitly ✓
- Integrates with existing config constants ✓
- No external dependencies beyond structlog ✓

---

## Integration with Signal Generator

Update generator.py to use real implementations:

```python
# BEFORE (placeholders):
maturity_multiplier = self._calculate_maturity_decay()
rotation_tag = self._check_rotation_risk(price.card_id)

# AFTER (real):
from src.engine.maturity import calculate_maturity_decay
from src.engine.rotation import check_rotation_risk

maturity_multiplier = calculate_maturity_decay(
    card_metadata.release_date,
    reference_date=datetime.utcnow().date()
)

rotation_result = check_rotation_risk(
    card_metadata.regulation_mark,
    card_metadata.legality_standard
)
rotation_tag = rotation_result["risk_level"]
```

---

## File Locations

- `src/engine/maturity.py` (135 lines)
- `src/engine/rotation.py` (216 lines)  
- `tests/test_maturity.py` (283 lines)
- `tests/test_rotation.py` (309 lines)

**Total:** 943 lines of module + test code

**Verification:**
```bash
pytest tests/test_maturity.py tests/test_rotation.py -v
# Result: 48 passed in 0.76s
```

---

## Next Steps

1. Update `src/signals/generator.py` to use real maturity/rotation modules
2. Create `src/engine/profit.py` (replaces simplified _calculate_net_profit)
3. Create `src/engine/velocity.py` (replaces simplified _calculate_velocity)
4. Wire up with pokemontcg.io API for card_metadata queries
5. Integration test with real Postgres DB

---

**Ready for code review and merge.**
