# Stage 04 Output Contract

**Stage:** 04 Scoring  
**Entry point:** `pipeline/04_scoring/scorer.py` → `score_packet(packet) -> ScoringOutput`  
**Output type:** `ScoringOutput` (dataclass, exported via `.to_dict()`)

---

## ScoringOutput

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `score_id` | str | `"SCO-NVDA-20260520-A3F1"` | `uuid.uuid4()` | PRESENT |
| `packet_reference` | str | `"PKT-NVDA-20260520"` | `packet.get("packet_id")` — defaults `""` if missing | PRESENT |
| `ticker` | str | `"NVDA"` | packet pass-through | PRESENT |
| `company_name` | str | `"NVIDIA Corporation"` | packet pass-through — defaults `""` if missing | PRESENT |
| `scored_at` | str (ISO8601) | `"2026-05-20T14:32:00Z"` | `datetime.now(utc)` | PRESENT |
| `evidence_score` | float | `0.0` (bug — see direction mismatch) | `evidence_scorer.score_evidence()` | PRESENT |
| `confidence_score` | float | `42.5` | `confidence_scorer.score_confidence()` | PRESENT |
| `conviction` | ConvictionLevel | `"insufficient"` | threshold rules | PRESENT |
| `recommendation` | Recommendation | `"watch"` | conviction → recommendation map | PRESENT |
| `position_sizing` | PositionSizing | `"none"` | conviction + invalidation map | PRESENT |
| `evidence_breakdown` | EvidenceScoreBreakdown | see below | `evidence_scorer` | PRESENT |
| `confidence_breakdown` | ConfidencePenaltyBreakdown | see below | `confidence_scorer` | PRESENT |
| `invalidation_report` | InvalidationReport | see below | `invalidation_checker` | PRESENT |
| `primary_risks` | list[str] | `["Competition from AMD"]` | `risk_factors` pass-through | PRESENT |
| `screening_score` | float | `0.0` (missing upstream) | `packet.get("screening_score", 0.0)` | PRESENT |
| `screening_reason_codes` | list[str] | `[]` (missing upstream) | `packet.get("screening_reason_codes", [])` | PRESENT |
| `evidence_score_note` | str | `"Net score driven by 0 bullish..."` | `evidence_scorer` | PRESENT |
| `confidence_score_note` | str | `"Base 42.5; thin evidence −15"` | `confidence_scorer` | PRESENT |
| `metadata` | dict | `{}` | scorer | PRESENT |

---

## EvidenceScoreBreakdown

| Field | Type | Notes | Status |
|---|---|---|---|
| `bull_weight` | float | Sum of reliability for BULLISH items | PRESENT |
| `bear_weight` | float | Sum of reliability for BEARISH items | PRESENT |
| `neutral_weight` | float | Sum of reliability for NEUTRAL items | PRESENT |
| `binary_weight` | float | Sum for BINARY items | PRESENT |
| `total_weight` | float | Sum of all | PRESENT |
| `net_score` | float | `(bull-bear)/(bull+bear)*100` | PRESENT — **currently always 0.0 due to case mismatch** |
| `directional_count` | int | Count of BULLISH + BEARISH items | PRESENT |
| `high_reliability_count` | int | Items with reliability ≥ 0.70 | PRESENT |

---

## ConfidencePenaltyBreakdown

| Field | Type | Notes | Status |
|---|---|---|---|
| `base_confidence` | float | `avg_reliability×100×0.60 + min(n/15,1)×100×0.40` | PRESENT |
| `contradiction_penalty` | float | 12 per HIGH, 5 per MEDIUM; cap 40 | PRESENT |
| `binary_catalyst_penalty` | float | 8 per HIGH-impact BINARY catalyst; cap 24 | PRESENT |
| `stale_data_penalty` | float | 4 per stale field; cap 16 — **0 always (data_freshness missing)** | PRESENT |
| `thin_evidence_penalty` | float | 15 if directional items < 6 | PRESENT |
| `total_penalty` | float | sum of all penalties | PRESENT |
| `bonuses` | float | MULTI_SIGNAL_CONFLUENCE +5, RS_MARKET_LEADER +3, etc. | PRESENT |
| `final_confidence` | float | base − penalty + bonuses, clamped 0–100 | PRESENT |

---

## InvalidationReport

| Field | Type | Notes | Status |
|---|---|---|---|
| `status` | InvalidationStatus | `"clear"` / `"monitoring"` / `"major"` / `"fatal"` | PRESENT |
| `triggered_conditions` | list[str] | condition_ids with `current_status == "triggered"` | PRESENT |
| `monitoring_conditions` | list[str] | condition_ids approaching trigger | PRESENT |
| `fatal_triggered` | bool | `true` if any FATAL TIC is triggered | PRESENT |
| `major_triggered` | bool | `true` if any MAJOR TIC is triggered | PRESENT |
| `notes` | str | plain-English summary | PRESENT |

Status: always `"clear"` currently because `thesis_invalidation_conditions` is missing from upstream.

---

## Conviction Thresholds (first match wins)

| Evidence Score | Confidence Score | ConvictionLevel |
|---|---|---|
| ≥ 55.0 | ≥ 70.0 | HIGH |
| ≥ 35.0 | ≥ 55.0 | MEDIUM |
| ≥ 15.0 | ≥ 40.0 | LOW |
| < 30.0 confidence floor | — | INSUFFICIENT |
| FATAL TIC triggered | — | → INVALIDATED recommendation |

---

## Downstream Usage

This `ScoringOutput` dict is consumed by:
- `pipeline/05_debate/position_builder.py` → `build_bull_brief(packet, scoring)` and `build_bear_brief()`
  - Reads: `evidence_score`, `confidence_score`, `conviction`, `recommendation`, `position_sizing`, `screening_score`, `screening_reason_codes`
- `pipeline/05_debate/debate_recorder.py` → `record_debate()`
  - Reads: `score_id`, `evidence_score`, `confidence_score`, `conviction`, `recommendation`
