# Stage 03 Output Contract

**Stage:** 03 Evidence Processing / Refinery  
**Entry point:** `pipeline/03_evidence_processing/run.py` → `python3 run.py TICKER`  
**Core function:** `refinery.py` → `build_analyst_brief(packet)`  
**Input:** `data/raw/{TICKER}_evidence_{YYYYMMDD}.json`  
**Output file:** `data/processed/{TICKER}_analyst_brief_{YYYYMMDD}.json`

No LLM calls — fully deterministic scoring and budget enforcement.

---

## Top-Level Analyst Brief

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `ticker` | str | `"NVDA"` | packet pass-through | PRESENT |
| `screening_archetype` | str | `"long_term_compounder"` | packet pass-through | PRESENT |
| `generated_at` | str (ISO8601) | `"2026-05-20T14:32:00Z"` | `datetime.now(utc)` | PRESENT |
| `fiscal_period` | str | `"FY2026 Q1"` | derived from packet fy + fq | PRESENT |
| `scoring_version` | str | `"1.0.0"` | from `scoring_weights.yaml` | PRESENT |
| `coverage_report` | dict | see below | `refinery.py` | PRESENT |
| `management_quotes` | list[ScoredItem] | max 8 items | `ranker.rank_and_budget()` | PRESENT |
| `filing_quotes` | list[ScoredItem] | max 8 items | `ranker.rank_and_budget()` | PRESENT |
| `external_bull_evidence` | list[ScoredItem] | max 4 items | `ranker.rank_and_budget()` | PRESENT |
| `external_bear_evidence` | list[ScoredItem] | max 4 items | `ranker.rank_and_budget()` | PRESENT |
| `uncertainties` | list[ScoredItem] | max 3 items | `ranker.rank_and_budget()` | PRESENT |
| `source_limitations` | list[dict] | always included | `_build_source_limitations()` | PRESENT |
| `metadata` | dict | see below | `refinery.py` | PRESENT |

---

## Coverage Report

| Field | Type | Example | Status |
|---|---|---|---|
| `transcript_status` | str | `"full_transcript"` / `"prepared_material_only"` / `"not_available"` | PRESENT |
| `has_q_and_a` | bool | `true` | PRESENT |
| `management_quotes_available` | int | `23` | PRESENT |
| `filing_quotes_available` | int | `47` | PRESENT |
| `external_bull_candidates` | int | `6` | PRESENT |
| `external_bear_candidates` | int | `3` | PRESENT |
| `coverage_warnings` | list[str] | `["No bear candidates found"]` | PRESENT |
| `evidence_quality_signal` | str | `"strong"` / `"moderate"` / `"weak"` | PRESENT |

Quality thresholds: `strong` = mgmt≥5 AND filing≥10 AND (bull≥2 OR bear≥2); `weak` = mgmt==0 OR filing<5.

---

## Scored Evidence Item (items in the 5 evidence buckets)

All items from Stage 02 pass through with `_score` injected by `scorer.score_evidence_item()`.

| Field | Type | Example | Status |
|---|---|---|---|
| `_score` | float | `0.847` | injected by `scorer.py` | PRESENT |
| `quote_text` | str | `"We expect revenue of..."` | Stage 02 pass-through | PRESENT |
| `quote_type` | str | `"direct"` | Stage 02 pass-through | PRESENT |
| `speaker` | str | `"Jensen Huang"` | Stage 02 pass-through | PRESENT |
| `speaker_confidence` | float | `0.95` | Stage 02 pass-through | PRESENT |
| `category` | str | `"guidance"` | Stage 02 pass-through | PRESENT |
| `category_confidence` | float | `0.92` | Stage 02 pass-through | PRESENT |
| `category_source` | str | `"llm_assigned"` | Stage 02 pass-through | PRESENT |
| `direction` | str | `"BULLISH"` | Stage 02 pass-through — **UPPERCASE** | PRESENT |
| `significance` | str | `"HIGH"` | Stage 02 pass-through | PRESENT |
| `item_class` | str | `"management_quote"` | Stage 02 pass-through | PRESENT |
| `source_priority` | str | `"primary_sec"` | Stage 02 pass-through | PRESENT |
| `reliability` | float | `0.95` | Stage 02 pass-through | PRESENT |
| `source_url` | str | `"https://..."` | Stage 02 pass-through | PRESENT |
| `ticker` | str | `"NVDA"` | Stage 02 pass-through | PRESENT |
| `filing_type` | str | `"10-K"` | Stage 02 pass-through (filing_quote) | PRESENT |
| `filing_section` | str | `"item_1a_risk_factors"` | Stage 02 pass-through (filing_quote) | PRESENT |
| `filing_section_label` | str | `"Risk Factors"` | Stage 02 pass-through (filing_quote) | PRESENT |
| `filing_date` | str | `"2025-01-20"` | Stage 02 pass-through (filing_quote) | PRESENT |
| `accession` | str | `"0001045810-25-..."` | Stage 02 pass-through (filing_quote) | PRESENT |
| `evidence_id` | str | — | **not added by Stage 03** | MISSING |

---

## Scoring Formula

```
score = (reliability × 0.30)
      + (extraction_confidence × 0.20)
      + (category_weight × 0.20)
      + (recency × 0.15)
      + (query_type_overlap × 0.10)
      + (contradiction_bonus × 0.05)

score *= source_priority_multiplier

if category_source == "llm_assigned" and category_confidence < 0.70:
    score *= 0.85
```

Category weights: guidance=1.00, risk_factors=0.95, tone_shift=0.90, competitive_positioning=0.85, margin_commentary=0.80, demand_commentary=0.75  
Source multipliers: primary_sec=1.00, official_company_material=0.95, external_discovery=0.70  
Recency: ≤30d=1.0, ≤90d=0.8, ≤180d=0.6, older/None=0.4  

---

## Evidence Budgets (enforced by `ranker.py`)

| Bucket | Cap |
|---|---|
| `management_quotes` | 8 |
| `filing_quotes` | 8 |
| `external_bull_evidence` | 4 |
| `external_bear_evidence` | 4 |
| `uncertainties` | 3 |

---

## Source Limitation Item

| Field | Type | Example | Status |
|---|---|---|---|
| `limitation_type` | str | `"transcript_coverage"` / `"filing_gap"` / `"external_coverage"` | PRESENT |
| `description` | str | `"No 10-Q was acquired..."` | PRESENT |
| `impact` | str | `"Quarterly cash-flow discussion may be missing"` | PRESENT |

---

## Metadata Block

| Field | Type | Status |
|---|---|---|
| `total_evidence_considered` | int | PRESENT |
| `total_evidence_in_brief` | int | PRESENT |
| `evidence_excluded_by_budget` | int | PRESENT |
| `scoring_version` | str | PRESENT |
