# Stage 01 Output Contract

**Stage:** 01 Screening  
**Entry point:** `pipeline/01_screening/screener.py` → `run_screening()`  
**Output type:** `ScreeningOutput` (dataclass, serialized via `.to_dict()`)

---

## ScreeningOutput

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `screening_id` | str | `"SCR-20260520-ABC1"` | `uuid.uuid4()` | PRESENT |
| `timestamp` | str (ISO8601) | `"2026-05-20T14:32:00Z"` | `datetime.now(utc)` | PRESENT |
| `market_regime` | str | `"RISK_ON_MOMENTUM"` | `classify_regime()` | PRESENT |
| `regime_confidence` | float | `0.82` | `classify_regime()` | PRESENT |
| `universe_size` | int | `50` | `len(raw_records)` | PRESENT |
| `candidates_evaluated` | int | `50` | loop counter | PRESENT |
| `threshold_applied` | float | `52.0` | regime profile | PRESENT |
| `shortlist` | list[ShortlistEntry] | see below | `run_screening()` | PRESENT |
| `shortlist_count` | int | `8` | `len(shortlist)` | PRESENT |
| `metadata` | dict | `{"elapsed_ms": 124}` | screener | PRESENT |

---

## ShortlistEntry

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `ticker` | str | `"NVDA"` | input record | PRESENT |
| `composite_score` | float | `74.3` | `_compute_composite()` | PRESENT |
| `regime_adjusted_score` | float | `71.1` | regime weight application | PRESENT |
| `signal_scores` | dict | `{"business_quality": 88.0, ...}` | `SignalScores` dataclass | PRESENT |
| `signal_weights_applied` | dict | `{"business_quality": 0.30, ...}` | archetype weight set | PRESENT |
| `regime_at_screening` | str | `"RISK_ON_MOMENTUM"` | `classify_regime()` | PRESENT |
| `screening_archetype` | str | `"long_term_compounder"` | archetype comparison | PRESENT |
| `reason_codes` | list[str] | `["RS_MARKET_LEADER", "FCF_POSITIVE"]` | `assign_reason_codes()` | PRESENT |
| `flags` | list[str] | `["BINARY_EVENT_IMMINENT"]` | signal scorer | PRESENT |
| `mispricing_hypothesis` | str | `"Trading at 15% discount to 3yr avg P/FCF..."` | `build_mispricing_hypothesis()` | PRESENT |
| `priority` | int | `1` | rank order | PRESENT |

---

## Signal Scores (within `signal_scores`)

| Signal | Range | Notes |
|---|---|---|
| `business_quality` | 0–100 | ROIC, margin durability, FCF conversion |
| `valuation_vs_growth` | 0–100 | PEG, EV/EBITDA vs growth rate |
| `historical_discount` | 0–100 or None | % off 3yr avg P/FCF; None if <3yr history |
| `earnings_quality` | 0–100 | Accruals ratio, revenue quality |
| `entry_vs_fundamentals` | 0–100 | Current price vs intrinsic range |
| `binary_event_risk` | 0–100 | Penalizes if earnings/FDA event ≤ 14 days |

None values propagate through — weights redistributed proportionally.

---

## Downstream Usage

- `screening_archetype` → carried into Stage 02 evidence packet (field: `screening_archetype`)
- `reason_codes` → passed to Stage 04 as `screening_reason_codes` (currently **MISSING** in Stage 02/03 output)
- `composite_score` → passed to Stage 04 as `screening_score` (currently **MISSING** in Stage 02/03 output)
- `signal_scores` → not passed downstream currently
- `price_data` from input record → optionally passed to Stage 06 `synthesize()` as `price_data` arg
