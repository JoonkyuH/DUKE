# Stage 05 Output Contract

**Stage:** 05 Debate  
**Entry point:** `pipeline/05_debate/debate_recorder.py` → `record_debate()`  
**Output type:** `DebateRecord` (dataclass, exported via `.to_dict()`)

---

## DebateRecord

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `debate_id` | str | `"DEB-NVDA-20260520-A3F1"` | `uuid.uuid4()` | PRESENT |
| `score_reference` | str | `"SCO-NVDA-20260520-..."` | `ScoringOutput.score_id` | PRESENT |
| `packet_reference` | str | `"PKT-NVDA-..."` | packet pass-through | PRESENT |
| `ticker` | str | `"NVDA"` | packet pass-through | PRESENT |
| `company_name` | str | `"NVIDIA Corporation"` | packet pass-through — `""` if missing upstream | PRESENT |
| `debated_at` | str (ISO8601) | `"2026-05-20T15:00:00Z"` | `datetime.now(utc)` | PRESENT |
| `bull_position` | AnalystPosition | see below | Bull analyst agent output | PRESENT |
| `bear_position` | AnalystPosition | see below | Bear analyst agent output | PRESENT |
| `contentions` | list[Contention] | see below | `contention_detector.detect_contentions()` | PRESENT |
| `base_evidence_score` | float | `0.0` (bug) | `ScoringOutput.evidence_score` | PRESENT |
| `base_confidence_score` | float | `42.5` | `ScoringOutput.confidence_score` | PRESENT |
| `debate_evidence_score` | float | `5.0` | base + net bull/bear adjustment | PRESENT |
| `debate_confidence_score` | float | `47.5` | base + net adjustment | PRESENT |
| `net_score_adjustment` | float | `5.0` | bull adj + bear adj | PRESENT |
| `outcome` | DebateOutcome | `"balanced"` | `debate_scorer.classify_outcome()` | PRESENT |
| `original_conviction` | str | `"insufficient"` | `ScoringOutput.conviction` pass-through | PRESENT |
| `original_recommendation` | str | `"watch"` | `ScoringOutput.recommendation` pass-through | PRESENT |
| `metadata` | dict | `{"raised_risks_count": 2}` | debate_recorder | PRESENT |

---

## AnalystPosition

Produced by Bull and Bear AI analyst agents. Defined by `debate_types.AnalystPosition` dataclass.

| Field | Type | Example | Status |
|---|---|---|---|
| `analyst_role` | str | `"bull"` / `"bear"` | PRESENT in dataclass |
| `summary` | str | `"NVDA is positioned to..."` | PRESENT in dataclass |
| `key_arguments` | list[str] | `["Data center momentum...", ...]` | PRESENT in dataclass |
| `evidence_cited` | list[str] | `["EV-001", "EV-003"]` | PRESENT in dataclass |
| `contested_items` | list[str] | `["EV-007"]` | PRESENT in dataclass |
| `raised_risks` | list[str] | `["AMD Milan competitor announced"]` | PRESENT in dataclass |
| `score_adjustment` | float | `+8.0` | PRESENT in dataclass |
| `confidence_adjustment` | float | `+5.0` | PRESENT in dataclass |
| `learning_hooks` | list[dict] | `[{"prediction": "...", "check_at_days": 90}]` | **MISSING from dataclass** — read by Stage 06/07 but not declared |
| `valuation_challenge` | dict | bear-specific challenge block | PRESENT in brief template but not in dataclass |

---

## Contention

Produced by `contention_detector.detect_contentions()`.

| Field | Type | Example | Status |
|---|---|---|---|
| `contention_id` | str | `"CON-D-001"` | PRESENT |
| `category` | str | `"guidance"` | PRESENT |
| `bull_claim` | str | `"Revenue guidance was raised..."` | PRESENT |
| `bear_claim` | str | `"Guidance relies on one customer..."` | PRESENT |
| `evidence_ids` | list[str] | `["EV-001", "EV-007"]` | PRESENT |
| `severity` | ContentionSeverity | `"critical"` / `"material"` / `"minor"` | PRESENT |
| `adjudication` | str or None | `None` (set by Chief Analyst in Stage 06) | PRESENT |

Severity rules: CRITICAL if max evidence reliability ≥ 0.80; MATERIAL if ≥ 0.60.

---

## Debate Outcome Classification

| Condition | Outcome |
|---|---|
| net score adjustment > +8 | BULL_PREVAILS |
| net score adjustment < −8 | BEAR_PREVAILS |
| gap between bull/bear > 15 and \|net\| ≤ 8 | INCONCLUSIVE |
| otherwise | BALANCED |

---

## Downstream Usage

`DebateRecord.to_dict()` is consumed by:
- `pipeline/06_synthesis/synthesizer.synthesize(debate_record, risk_assessment)`
  - Reads: `ticker`, `company_name`, `debate_id`, `contentions`, `bull_position`, `bear_position`, `outcome`, `base_*_score`, `debate_*_score`, `original_conviction`, `original_recommendation`
  - Also reads `bull_position["learning_hooks"]` and `bear_position["learning_hooks"]` — **will be empty or absent** until `AnalystPosition` dataclass is updated
