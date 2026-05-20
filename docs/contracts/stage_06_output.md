# Stage 06 Output Contract

**Stage:** 06 Synthesis  
**Entry point:** `pipeline/06_synthesis/synthesizer.py` → `synthesize() -> SynthesisOutput`  
**Output type:** `SynthesisOutput` (dataclass, exported via `.to_dict()`)

Stage 06 assembles the structured brief the Chief Analyst agent receives, then wraps it in `SynthesisOutput`. The Chief Analyst's AI response (`ChiefAnalystOutput`) is a separate downstream artifact produced after Stage 06.

---

## SynthesisOutput

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `synthesis_id` | str | `"SYN-NVDA-20260520-A3F1"` | `_make_synthesis_id()` | PRESENT |
| `debate_reference` | str | `"DEB-NVDA-..."` | `DebateRecord.debate_id` | PRESENT |
| `ticker` | str | `"NVDA"` | debate_record pass-through | PRESENT |
| `company_name` | str | `"NVIDIA Corporation"` | debate_record pass-through | PRESENT |
| `synthesized_at` | str (ISO8601) | `"2026-05-20T16:00:00Z"` | `datetime.now(utc)` | PRESENT |
| `chief_analyst_brief` | dict | see below | `_build_brief()` | PRESENT |
| `debate_evidence_score` | float | `5.0` | debate_record pass-through | PRESENT |
| `debate_confidence_score` | float | `47.5` | debate_record pass-through | PRESENT |
| `debate_outcome` | str | `"balanced"` | debate_record pass-through | PRESENT |
| `overall_risk_assessment` | str | `"adequate"` | risk_assessment pass-through | PRESENT |
| `ready_for_chief_analyst` | bool | `true` | risk_assessment pass-through | PRESENT |
| `blocking_issues` | list[str] | `[]` | risk_assessment pass-through | PRESENT |
| `metadata` | dict | see below | `synthesizer.py` | PRESENT |

---

## `chief_analyst_brief` Structure

This dict is the actual prompt context fed to the Chief Analyst AI agent.

| Key | Type | Notes | Status |
|---|---|---|---|
| `role` | str | `"chief_analyst"` | PRESENT |
| `instruction` | str | synthesis instruction text | PRESENT |
| `ticker` | str | | PRESENT |
| `company_name` | str | | PRESENT |
| `scores.base_evidence_score` | float | | PRESENT |
| `scores.base_confidence_score` | float | | PRESENT |
| `scores.debate_evidence_score` | float | | PRESENT |
| `scores.debate_confidence_score` | float | | PRESENT |
| `scores.original_conviction` | str | | PRESENT |
| `scores.original_recommendation` | str | | PRESENT |
| `debate_outcome` | str | | PRESENT |
| `bull_position.summary` | str | | PRESENT |
| `bull_position.key_arguments` | list[str] | | PRESENT |
| `bull_position.evidence_cited` | list[str] | | PRESENT |
| `bull_position.contested_items` | list[str] | | PRESENT |
| `bull_position.raised_risks` | list[str] | | PRESENT |
| `bull_position.learning_hooks` | list[dict] | `[]` always — field not in AnalystPosition dataclass | PRESENT (always empty) |
| `bull_position.score_adjustment` | float | | PRESENT |
| `bull_position.confidence_adjustment` | float | | PRESENT |
| `bear_position.*` | same structure | + `valuation_challenge` key | PRESENT |
| `contentions` | list[Contention] | sorted CRITICAL first | PRESENT |
| `risk_assessment.overall_risk_assessment` | str | | PRESENT |
| `risk_assessment.ready_for_chief_analyst` | bool | | PRESENT |
| `risk_assessment.blocking_issues` | list[str] | | PRESENT |
| `risk_assessment.tic_assessment` | list[dict] | | PRESENT |
| `risk_assessment.tic_coverage_gaps` | list[str] | | PRESENT |
| `risk_assessment.risk_factor_assessment` | list[dict] | | PRESENT |
| `risk_assessment.missing_risk_factors` | list[str] | | PRESENT |
| `risk_assessment.binary_event_assessment` | list[dict] | | PRESENT |
| `risk_assessment.monitoring_plan` | dict | | PRESENT |
| `output_format` | dict | explicit JSON template for agent | PRESENT |
| `market_technical_context` | dict | only if `price_data` provided | CONDITIONAL |

---

## `metadata` Block (SynthesisOutput)

| Field | Type | Status |
|---|---|---|
| `contention_count` | int | PRESENT |
| `critical_contentions` | int | PRESENT |
| `material_contentions` | int | PRESENT |
| `raised_risks_count` | int | PRESENT |
| `evidence_score_note` | str | PRESENT |
| `confidence_score_note` | str | PRESENT |

---

## ChiefAnalystOutput (downstream — not produced by `synthesize()`)

After Stage 06 is complete, the Chief Analyst AI agent receives `chief_analyst_brief` and returns a `ChiefAnalystOutput`. This is parsed separately. Fields defined in `synthesis_types.ChiefAnalystOutput`:

| Field | Type | Status |
|---|---|---|
| `analyst_role` | str | from agent |
| `recommendation` | str | `strong_conviction_enter \| moderate_conviction_enter \| watch \| pass \| blocked` |
| `investment_archetype_confirmed` | str | `long_term_compounder \| deep_value \| does_not_fit` |
| `final_evidence_score` | float | |
| `final_confidence_score` | float | |
| `executive_summary` | str | |
| `bull_case_assessment` | str | |
| `bear_case_assessment` | str | |
| `critical_contention_adjudications` | list[ContentionAdjudication] | |
| `philosophy_fit` | str | `strong \| adequate \| weak \| does_not_fit` |
| `philosophy_fit_notes` | str | |
| `risk_officer_flags` | list[str] | |
| `monitoring_priorities` | list[MonitoringPriority] | |
| `what_would_change_this` | str | |
| `blocking_issues` | list[str] | |
| `metadata` | dict | |
