# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What DUKE Is

DUKE ("Doesn't Usually Know Either") is a multi-agent investment intelligence framework. It is not a trading bot — it compresses research, surfaces contradictions, and produces structured recommendation packets for human review before any capital is deployed.

## Running the Code

All modules use **Python stdlib only** — no `pip install` needed. (Data ingestion will require `requests`, `pandas`, and source-specific SDKs when built.)

Run modules from their own directory so relative imports resolve:

```bash
cd pipeline/01_screening && python3 screener.py
cd pipeline/03_processing && python3 synthesizer.py
cd pipeline/04_scoring    && python3 scorer.py
cd pipeline/07_output     && python3 decision_capture.py
```

There are no tests, no build system, and no package manifest — this is a pure-Python pipeline run directly.

## Architecture

The system processes tickers through numbered pipeline stages. Each stage has a defined input/output contract enforced by JSON schemas.

```
Raw Data → 01_screening → 02_research → 03_processing → 04_scoring → 05_debate → 06_synthesis → 07_output
                                                                                        ↓
                                                                               Human Review
```

**Stage 01 — Screening** (`pipeline/01_screening/`)
- Entry point: `screener.py` → `run_screening(raw_records, regime_indicators, sector_data)`
- Scores 6 signals per ticker (0–100): momentum, relative strength, volume anomaly, sector leadership, news velocity, earnings proximity
- `regime_classifier.py` detects market regime (6 types) and sets signal weights + score thresholds
- Missing data scores `None` — never coerced to zero; weights redistributed proportionally across present signals
- Outputs a ranked `ScreeningOutput` with `shortlist: List[ShortlistEntry]`, each annotated with reason codes and investigation flags
- Schema contracts: `schemas/input.json` (raw signal record), `schemas/output.json`

**Stage 02 — Research** (`pipeline/02_research/`)
- Prompt-driven; no Python modules
- AI researchers use `prompts/deep_researcher.md` and `prompts/earnings_call_analyst.md` to gather structured evidence

**Stage 03 — Processing** (`pipeline/03_processing/`)
- Entry point: `synthesizer.py` → `build_packet(...)` assembles an `EvidencePacket`
- `evidence_types.py` is the type contract between stages; every downstream field is defined here
- `contradiction_detector.py` runs O(n²) pairwise comparison over evidence items; items sharing a category with opposing BULLISH/BEARISH directions are flagged as contradictions, severity-ranked by source reliability
- `catalyst_mapper.py` builds and priority-sorts catalysts; binary events (uncertain outcome) are elevated above directional ones
- Schema contract: `schemas/output.json` (evidence packet)

**Stage 04 — Scoring** (`pipeline/04_scoring/`)
- Entry point: `scorer.py` → `score_packet(packet: dict) -> ScoringOutput`
- `evidence_scorer.py`: net evidence score = (bull_weight − bear_weight) / (bull_weight + bear_weight) × 100; NEUTRAL/BINARY items excluded from direction
- `confidence_scorer.py`: base = quality×0.60 + volume×0.40; penalties for contradictions, binary catalysts, stale fields, thin evidence; bonuses for multi-signal confluence and FCF+guidance
- `invalidation_checker.py`: evaluates TIC statuses; precedence FATAL > MAJOR > MONITORING > CLEAR
- Conviction thresholds (first match wins): ev≥55 + conf≥70 → HIGH, ev≥35 + conf≥55 → MEDIUM, ev≥15 + conf≥40 → LOW; FATAL → INVALIDATED
- Position sizing downgrades on MAJOR/FATAL or imminent binary catalyst (≤7 days)
- `score_types.py` is the type contract; `schemas/output.json` is the inter-layer schema

**Stage 05 — Debate** (`pipeline/05_debate/`)
- Four AI analyst roles driven by prompts in `prompts/`: `bull_analyst.md`, `bear_analyst.md`, `risk_officer.md`, `chief_analyst.md`
- `position_builder.py`: `build_bull_brief()` / `build_bear_brief()` — surfaces top-5 opposing evidence items (reliability ≥ 0.70) as `must_address_evidence`
- `contention_detector.py`: `detect_contentions()` — identifies CRITICAL (max rel ≥ 0.80) and MATERIAL (≥ 0.60) contentions from cited/contested overlaps
- `debate_scorer.py`: clamps adjustments (±15 score, ±10 conf); outcome logic — BULL_PREVAILS: net > +8, BEAR_PREVAILS: net < −8, INCONCLUSIVE: gap > 15 with |net| ≤ 8, BALANCED: otherwise
- `debate_recorder.py`: entry point `record_debate(packet, scoring, bull_pos, bear_pos) -> DebateRecord`
- Bull and Bear produce `learning_hooks` — falsifiable predictions checked at 90/180/365 days. Risk Officer produces `monitoring_plan`. Chief Analyst synthesizes all into a final recommendation.
- `debate_types.py` is the type contract; `schemas/output.json` is the inter-layer schema

**Stage 06 — Synthesis** (`pipeline/06_synthesis/`)
- Entry point: `synthesizer.py` → `synthesize(debate_record, risk_assessment) -> SynthesisOutput`
- Assembles the structured `chief_analyst_brief` dict the Chief Analyst agent receives: scores, both analyst positions with learning hooks, contentions sorted CRITICAL first, full risk assessment, and an explicit output format template
- `synthesis_types.py` is the type contract (also defines `ChiefAnalystOutput` — the parsed response from the Chief Analyst agent)
- `schemas/output.json` is the inter-layer schema

**Stage 07 — Output** (`pipeline/07_output/`)
- `formatter.py`: `format_recommendation(chief_analyst_output, synthesis_output) -> str` — ANSI terminal report covering all output fields
- `decision_capture.py`: `capture_decision(chief_analyst_output, synthesis_output) -> dict` — displays recommendation, sizing guidance (with downgrade logic for risk flags/weak fit), portfolio context from `data/raw/portfolio/latest.csv` if present, collects investor inputs, writes to `data/journal/`
- `journal.py`: `write_decision_record()`, `write_outcome_record()`, `write_postmortem_record()`, `read_journal()` — persistent journal in `data/journal/` with naming convention `DEC-{TICKER}-{YYYYMMDD}.json`, `OUT-{TICKER}-{DATE}-{DAYS}d.json`, `POST-{TICKER}-{DATE}.json`
- `schemas/output.json` defines the `DecisionRecord` written to the journal

## Key Design Invariants

**Schema contracts are the inter-layer API.** Do not modify a schema without checking all downstream consumers. `evidence_types.py` is the single source of truth for what Layer 3 can access — any field Layer 3 needs must be declared there.

**Evidence reliability hierarchy is enforced.** `SOURCE_RELIABILITY_DEFAULTS` in `evidence_types.py` assigns weights: SEC filings (0.95) down to social media (0.20). Contradiction severity is computed from the minimum reliability of the two conflicting sources.

**Regime classification drives all screening thresholds.** Score thresholds and shortlist caps vary by regime (e.g., `LIQUIDITY_CONTRACTION` requires ≥68 composite and caps at 8 tickers; `RISK_ON_MOMENTUM` requires ≥52 and allows 20). Rules fire in priority order; first match wins.

**Contradictions are first-class outputs.** `detect_contradictions()` mutates `EvidenceItem` objects in place (sets `contradiction_flag`, `contradiction_with`). Unresolved HIGH-severity contradictions apply uncertainty penalties in Layer 3.

**Learning hooks are the core feedback loop.** Bull and Bear analysts produce falsifiable, time-bounded predictions (`learning_hooks`). These are persisted in the journal `DecisionRecord` at entry and checked against outcome records at 90/180/365 days. The Risk Officer's `monitoring_plan` defines the review cadence. Treat `learning_hooks` as first-class outputs — not decorative fields.

**All inter-layer data passes as plain dicts.** Typed dataclasses (`ScoringOutput`, `DebateRecord`, `SynthesisOutput`, etc.) are internal to each stage. Layers communicate via JSON-compatible dicts to avoid cross-directory import issues.

## Role Assignments (Multi-Agent System)

| Role | Tool | Responsibility |
|---|---|---|
| Market Researcher | Perplexity + Grok | Gathers raw signal data for Stages 01–02 |
| Coder | Claude Code | Implements and runs all Python modules |
| Orchestrator | Claude Cowork | Coordinates analyst roles, assembles output |
| Chief / Bull / Bear / Risk Analysts | Claude Finance Agent | Synthesizes evidence, writes recommendation |

## Build Status

| Stage | Status |
|---|---|
| 01 Screening | Complete |
| 02 Research | Prompt-only (no Python) |
| 03 Processing | Complete |
| 04 Scoring | Complete |
| 05 Debate | Complete (Python + 4 analyst prompts) |
| 06 Synthesis | Complete |
| 07 Output | Complete (formatter, decision capture, journal) |
| Data ingestion | Pending |
