# Stage 04 Input Contract

**Stage:** 04 Scoring  
**Entry point:** `pipeline/04_scoring/scorer.py` → `score_packet(packet: dict)`  
**Expected input schema:** `pipeline/04_scoring/schemas/input.json` (references Stage 03 processing output)

Stage 04 receives a single packet dict. In the current pipeline design this is the **Stage 03 evidence packet** (not the analyst brief). The fields below are what `score_packet()` actually reads via `packet.get(...)`.

---

## Fields Read by `score_packet()`

| Field | Type | Example | Stage That Produces It | Status |
|---|---|---|---|---|
| `ticker` | str | `"NVDA"` | Stage 02 | PRESENT |
| `company_name` | str | `"NVIDIA Corporation"` | Stage 02 | MISSING — not in Stage 02 output |
| `packet_id` | str | `"PKT-NVDA-20260520"` | Stage 02 | MISSING — not in Stage 02 output |
| `evidence_items` | list[dict] | see Stage 02 contract | Stage 02 | PRESENT |
| `contradictions` | list[dict] | `[]` | Stage 02 | PRESENT (empty placeholder) |
| `catalyst_map` | list[dict] | `[{"event": "earnings", ...}]` | Stage 02 | MISSING |
| `thesis_invalidation_conditions` | list[dict] | `[{"condition_id": "TIC-001", ...}]` | Stage 02 | MISSING |
| `risk_factors` | list[dict] | `[{"factor": "competition", ...}]` | Stage 02 | MISSING |
| `data_freshness` | dict | `{"stale_fields": ["fundamentals"]}` | Stage 02 | MISSING |
| `fundamentals` | dict | `{"revenue_ttm": 80.3, "pe_ratio": 42.1}` | Stage 02 | MISSING |
| `screening_reason_codes` | list[str] | `["RS_MARKET_LEADER"]` | Stage 01 | MISSING — dropped after Stage 01 |
| `screening_score` | float | `74.3` | Stage 01 | MISSING — dropped after Stage 01 |

---

## How Stage 04 Also Consumes Stage 01 Output

`score_packet()` returns a `ScoringOutput` that carries `screening_score` and `screening_reason_codes` through from the packet. These values originate in Stage 01 (`ShortlistEntry.composite_score` and `.reason_codes`) and are intended to be injected into the evidence packet before Stage 04 runs.

Current state: both fields are absent from Stage 02/03 output. `score_packet()` defaults them to `0.0` and `[]`.

---

## `data_availability` Block Pattern

When upstream data is unavailable, the caller constructing the packet should include this block so Stage 04 can skip optional scoring components gracefully rather than defaulting silently:

```json
{
  "data_availability": {
    "fundamentals":                     "available | not_available",
    "catalyst_map":                     "available | not_available",
    "thesis_invalidation_conditions":   "available | not_available",
    "data_freshness":                   "available | not_available",
    "screening_score":                  "available | not_available"
  }
}
```

When `not_available`, `score_packet()` should zero out the corresponding penalty/bonus component rather than applying a penalty for data the pipeline never had. This block is **not yet consumed** by Stage 04 — it is a design target.

---

## Critical Mismatch: Direction Case

`evidence_scorer.score_evidence()` checks:
```python
if item.get("direction") in ("bullish", "bearish"):
```

Stage 02 emits `direction` in UPPERCASE: `"BULLISH"` / `"BEARISH"` / `"NEUTRAL"`.

**Effect:** Every evidence item resolves to NEUTRAL. `net_score` = 0.0 for all tickers.  
**Fix required:** Normalize `direction` to lowercase before Stage 04, or fix `evidence_scorer.py` to be case-insensitive.

---

## Critical Mismatch: Evidence Fields for Stage 05

`position_builder._format_evidence()` reads these fields from each `evidence_items` entry:

| Field | Present in Stage 02 output? |
|---|---|
| `evidence_id` | NO |
| `content` | NO |
| `source` | NO |
| `reliability` | YES |
| `category` | YES |
| `date` | NO (closest: `filing_date` for filing_quote) |
| `quote` | NO (closest: `quote_text`) |

All six `None` returns propagate into the brief the analyst agent receives.
