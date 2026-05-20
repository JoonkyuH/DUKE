# Stage 07 Input Contract

**Stage:** 07 Output  
**Entry point:** `pipeline/07_output/decision_capture.py` → `capture_decision(chief_analyst_output, synthesis_output)`  
**Formatter:** `pipeline/07_output/formatter.py` → `format_recommendation(chief_analyst_output, synthesis_output)`

Stage 07 receives two inputs: the `ChiefAnalystOutput` dict (AI agent response parsed from the chief_analyst prompt) and the `SynthesisOutput` dict from Stage 06.

---

## From `chief_analyst_output` (`ChiefAnalystOutput` dict)

Fields read by `decision_capture.py` and `formatter.py`:

| Field | Path | Type | Example | Status |
|---|---|---|---|---|
| `recommendation` | `chief_analyst_output["recommendation"]` | str | `"moderate_conviction_enter"` | from agent |
| `philosophy_fit` | `chief_analyst_output["philosophy_fit"]` | str | `"strong"` | from agent |
| `risk_officer_flags` | `chief_analyst_output["risk_officer_flags"]` | list[str] | `["TIC-001 approaching"]` | from agent |
| `blocking_issues` | `chief_analyst_output["blocking_issues"]` | list[str] | `[]` | from agent |
| `final_evidence_score` | `chief_analyst_output["final_evidence_score"]` | float | `47.0` | from agent |
| `final_confidence_score` | `chief_analyst_output["final_confidence_score"]` | float | `61.0` | from agent |
| `executive_summary` | `chief_analyst_output["executive_summary"]` | str | `"NVDA demonstrates..."` | from agent |
| `what_would_change_this` | `chief_analyst_output["what_would_change_this"]` | str | `"AMD competitive win at hyperscaler..."` | from agent |
| `monitoring_priorities` | `chief_analyst_output["monitoring_priorities"]` | list[dict] | see below | from agent |
| `investment_archetype_confirmed` | `chief_analyst_output["investment_archetype_confirmed"]` | str | `"long_term_compounder"` | from agent |
| `bull_case_assessment` | `chief_analyst_output["bull_case_assessment"]` | str | used by formatter | from agent |
| `bear_case_assessment` | `chief_analyst_output["bear_case_assessment"]` | str | used by formatter | from agent |
| `critical_contention_adjudications` | `chief_analyst_output["critical_contention_adjudications"]` | list[dict] | used by formatter | from agent |
| `philosophy_fit_notes` | `chief_analyst_output["philosophy_fit_notes"]` | str | used by formatter | from agent |

---

## From `synthesis_output` (`SynthesisOutput` dict)

| Field | Path | Type | Status |
|---|---|---|---|
| `ticker` | `synthesis_output["ticker"]` | str | PRESENT |
| `company_name` | `synthesis_output["company_name"]` | str | PRESENT — `""` if missing upstream |
| `synthesis_id` | `synthesis_output["synthesis_id"]` | str | PRESENT |
| `debate_reference` | `synthesis_output["debate_reference"]` | str | PRESENT |
| `debate_outcome` | `synthesis_output["debate_outcome"]` | str | PRESENT |
| `overall_risk_assessment` | `synthesis_output["overall_risk_assessment"]` | str | PRESENT |

---

## `learning_hooks` Extraction Path

`_extract_learning_hooks(syn)` in `decision_capture.py` reads:

```python
bull_hooks = syn["chief_analyst_brief"]["bull_position"]["learning_hooks"]
bear_hooks = syn["chief_analyst_brief"]["bear_position"]["learning_hooks"]
```

- `syn["chief_analyst_brief"]` → present in `SynthesisOutput`
- `bull_position["learning_hooks"]` → always `[]` currently (not in `AnalystPosition` dataclass)

To get real `learning_hooks` into the journal, the Bull/Bear agents must return them and `AnalystPosition` must declare the field so it survives the dataclass → dict serialization path.

---

## DecisionRecord (written to `data/journal/DEC-{TICKER}-{YYYYMMDD}.json`)

Defined by `pipeline/07_output/schemas/output.json`. Fields marked required by the schema:

| Field | Type | Status |
|---|---|---|
| `ticker` | str | from synthesis_output |
| `date` | str (YYYY-MM-DD) | `datetime.now()` |
| `decided_at` | str (ISO8601) | `datetime.now()` |
| `analyst_recommendation` | str | from chief_analyst_output |
| `action` | str | investor input |
| `conviction_1_to_10` | int | derived from final scores |
| `learning_hooks` | list[dict] | extracted from brief — currently always `[]` |

Schema uses `"additionalProperties": false` — any field not declared in `output.json` will fail validation if the journal writer uses the schema to validate before writing.

---

## `monitoring_priorities` Item Shape

Each item in `chief_analyst_output["monitoring_priorities"]` conforms to:

| Field | Type | Example |
|---|---|---|
| `priority` | int | `1` |
| `description` | str | `"Monitor AMD data center share gain quarterly"` |
| `source` | str | `"TIC-001"` / `"learning_hook"` / `"risk_factor"` / `"risk_officer"` |
| `frequency` | str | `"weekly"` / `"monthly"` / `"quarterly"` |
