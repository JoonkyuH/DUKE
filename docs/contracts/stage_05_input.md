# Stage 05 Input Contract

**Stage:** 05 Debate  
**Entry point:** `pipeline/05_debate/debate_recorder.py` → `record_debate(packet, scoring, bull_pos, bear_pos)`  
**Brief builders:** `position_builder.build_bull_brief(packet, scoring)` and `build_bear_brief(packet, scoring)`

Stage 05 receives two inputs: the **evidence packet** (same format Stage 04 consumed) and the **ScoringOutput** dict from Stage 04.

---

## From the Evidence Packet (`packet`)

Fields read by `position_builder.py`:

| Field | Path | Stage That Produces It | Status |
|---|---|---|---|
| `ticker` | `packet["ticker"]` | Stage 02 | PRESENT |
| `company_name` | `packet["company_name"]` | Stage 02 | MISSING |
| `sector` | `packet["sector"]` | Stage 02 | MISSING |
| `evidence_items` | `packet["evidence_items"]` | Stage 02 | PRESENT |
| `evidence_items[*].direction` | per-item field | Stage 02 | PRESENT — **UPPERCASE** (must match lowercase filter) |
| `evidence_items[*].reliability` | per-item field | Stage 02 | PRESENT |
| `evidence_items[*].evidence_id` | per-item field | Stage 02 | MISSING — `_format_evidence()` returns None |
| `evidence_items[*].content` | per-item field | Stage 02 | MISSING — `_format_evidence()` returns None |
| `evidence_items[*].source` | per-item field | Stage 02 | MISSING — `_format_evidence()` returns None |
| `evidence_items[*].category` | per-item field | Stage 02 | PRESENT |
| `evidence_items[*].date` | per-item field | Stage 02 | MISSING (closest: `filing_date`) |
| `evidence_items[*].quote` | per-item field | Stage 02 | MISSING (closest: `quote_text`) |
| `catalyst_map` | `packet["catalyst_map"]` | Stage 02 | MISSING — defaults to `[]` |
| `thesis_invalidation_conditions` | `packet["thesis_invalidation_conditions"]` | Stage 02 | MISSING — defaults to `[]` |
| `risk_factors` | `packet["risk_factors"]` | Stage 02 | MISSING — defaults to `[]` |
| `contradictions` | `packet["contradictions"]` | Stage 02 | PRESENT (empty `[]`) |
| `summary.key_questions` | `packet["summary"]["key_questions"]` | Stage 02 | MISSING — KeyError if accessed |
| `screening_flags` | `packet["screening_flags"]` | Stage 02 | MISSING — defaults to `[]` |

**Direction filter bug:** `position_builder.py` filters with `e.get("direction") == "bullish"` (lowercase). Stage 02 emits `"BULLISH"`. Every bull/bear item list will be empty until normalized.

---

## From the ScoringOutput Dict (`scoring`)

Fields read by `position_builder.py` and `debate_recorder.py`:

| Field | Stage That Produces It | Status |
|---|---|---|
| `evidence_score` | Stage 04 | PRESENT |
| `confidence_score` | Stage 04 | PRESENT |
| `conviction` | Stage 04 | PRESENT |
| `recommendation` | Stage 04 | PRESENT |
| `position_sizing` | Stage 04 | PRESENT |
| `screening_score` | Stage 04 (pass-through) | PRESENT — but value is `0.0` due to upstream gap |
| `screening_reason_codes` | Stage 04 (pass-through) | PRESENT — but value is `[]` due to upstream gap |
| `score_id` | Stage 04 | PRESENT |

---

## Risk Officer Input (for `record_debate`)

The Risk Officer analyst's structured output is also an input to Stage 05. It is produced by the AI agent after receiving the bear brief and TIC list. Expected fields:

| Field | Type | Status |
|---|---|---|
| `overall_risk_assessment` | str | from prompt output |
| `ready_for_chief_analyst` | bool | from prompt output |
| `blocking_issues` | list[str] | from prompt output |
| `tic_assessment` | list[dict] | from prompt output |
| `tic_coverage_gaps` | list[str] | from prompt output |
| `risk_factor_assessment` | list[dict] | from prompt output |
| `missing_risk_factors` | list[str] | from prompt output |
| `binary_event_assessment` | list[dict] | from prompt output |
| `monitoring_plan` | dict | from prompt output |

---

## AnalystPosition — Expected Output from Bull/Bear Agents

Bull and Bear agents receive the brief dict and return a structured `AnalystPosition`. The dataclass in `debate_types.py` defines the contract:

| Field | Type | Notes | Status |
|---|---|---|---|
| `analyst_role` | AnalystRole | `"bull"` or `"bear"` | PRESENT in dataclass |
| `summary` | str | 3–5 sentence case | PRESENT in dataclass |
| `key_arguments` | list[str] | top 3–5 arguments | PRESENT in dataclass |
| `evidence_cited` | list[str] | evidence_ids cited | PRESENT in dataclass |
| `contested_items` | list[str] | opposing evidence_ids disputed | PRESENT in dataclass |
| `raised_risks` | list[str] | new risks not in packet | PRESENT in dataclass |
| `score_adjustment` | float | [-15, +15] | PRESENT in dataclass |
| `confidence_adjustment` | float | [-10, +10] | PRESENT in dataclass |
| `learning_hooks` | list[dict] | falsifiable predictions — read by Stage 06/07 | **MISSING from dataclass** |

> **`learning_hooks` gap:** `synthesizer.py` reads `bull.get("learning_hooks", [])` and `bear.get("learning_hooks", [])`. `decision_capture.py` reads `syn["chief_analyst_brief"]["bull_position"]["learning_hooks"]`. The `AnalystPosition` dataclass does not define this field — it will only exist if the AI agent returns it and the caller passes it through as a raw dict rather than instantiating the dataclass.
