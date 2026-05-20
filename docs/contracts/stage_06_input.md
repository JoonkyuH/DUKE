# Stage 06 Input Contract

**Stage:** 06 Synthesis  
**Entry point:** `pipeline/06_synthesis/synthesizer.py` → `synthesize(debate_record, risk_assessment, price_data=None)`

Stage 06 receives three inputs: the `DebateRecord` dict (Stage 05 output), the `risk_assessment` dict (Risk Officer agent output, also Stage 05), and optional `price_data` (from Stage 01 input record).

---

## From `debate_record` (Stage 05 output)

| Field | Path | Status |
|---|---|---|
| `ticker` | `debate_record["ticker"]` | PRESENT |
| `company_name` | `debate_record["company_name"]` | PRESENT — `""` if missing upstream |
| `debate_id` | `debate_record["debate_id"]` | PRESENT |
| `outcome` | `debate_record["outcome"]` | PRESENT |
| `base_evidence_score` | `debate_record["base_evidence_score"]` | PRESENT |
| `base_confidence_score` | `debate_record["base_confidence_score"]` | PRESENT |
| `debate_evidence_score` | `debate_record["debate_evidence_score"]` | PRESENT |
| `debate_confidence_score` | `debate_record["debate_confidence_score"]` | PRESENT |
| `original_conviction` | `debate_record["original_conviction"]` | PRESENT |
| `original_recommendation` | `debate_record["original_recommendation"]` | PRESENT |
| `contentions` | `debate_record["contentions"]` | PRESENT |
| `bull_position` | `debate_record["bull_position"]` | PRESENT |
| `bull_position["summary"]` | nested | PRESENT |
| `bull_position["key_arguments"]` | nested | PRESENT |
| `bull_position["evidence_cited"]` | nested | PRESENT |
| `bull_position["contested_items"]` | nested | PRESENT |
| `bull_position["raised_risks"]` | nested | PRESENT |
| `bull_position["learning_hooks"]` | nested | **MISSING** — not in AnalystPosition dataclass |
| `bull_position["score_adjustment"]` | nested | PRESENT |
| `bull_position["confidence_adjustment"]` | nested | PRESENT |
| `bear_position["*"]` | nested | same as bull fields above |
| `bear_position["valuation_challenge"]` | nested | PRESENT in brief template, not in dataclass |
| `metadata["raised_risks_count"]` | nested | PRESENT |
| `metadata["evidence_score_note"]` | nested | PRESENT |
| `metadata["confidence_score_note"]` | nested | PRESENT |

---

## From `risk_assessment` (Risk Officer agent output)

This dict is the structured JSON returned by the Risk Officer AI agent from their prompt in `pipeline/05_debate/prompts/risk_officer.md`.

| Field | Type | Status |
|---|---|---|
| `overall_risk_assessment` | str | from agent |
| `ready_for_chief_analyst` | bool | from agent |
| `blocking_issues` | list[str] | from agent |
| `tic_assessment` | list[dict] | from agent |
| `tic_coverage_gaps` | list[str] | from agent |
| `risk_factor_assessment` | list[dict] | from agent |
| `missing_risk_factors` | list[str] | from agent |
| `binary_event_assessment` | list[dict] | from agent |
| `monitoring_plan` | dict | from agent |

---

## From `price_data` (optional — Stage 01 input record)

When provided, Stage 06 computes a `market_technical_context` block and injects it into the `chief_analyst_brief`. Pass `None` to omit this section.

| Field | Type | Notes | Status |
|---|---|---|---|
| `current_price` | float | required — if None, entire context block is omitted | optional |
| `ma_50` | float | 50-day moving average | optional |
| `ma_200` | float | 200-day moving average | optional |
| `rsi_14` | float | 14-day RSI | optional |
| `volume_ratio` | float | current vol / avg vol | optional |
| `above_ma_50` | bool | pre-computed boolean | optional |
| `above_ma_200` | bool | pre-computed boolean | optional |
| `week_52_high` | float | 52-week high | optional |
| `week_52_low` | float | 52-week low | optional |

`price_data` is the merged `price_data + extended_data` from the Stage 01 input record. It is not currently passed through the pipeline — would need to be stored separately alongside the evidence packet and threaded through.
