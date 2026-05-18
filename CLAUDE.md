# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What DUKE Is

DUKE ("Doesn't Usually Know Either") is a multi-agent investment intelligence framework. It is not a trading bot — it compresses research, surfaces contradictions, and produces structured recommendation packets for human review before any capital is deployed.

## Running the Code

All modules through Layer 3 use **Python stdlib only** — no `pip install` needed. Layer 3 will require `jsonschema`; data ingestion will require `requests`, `pandas`, and source-specific SDKs.

Run modules from their own directory so relative imports resolve:

```bash
# Layer 1 screening
cd pipeline/01_screening
python screener.py

# Layer 2/3 processing
cd pipeline/03_processing
python synthesizer.py
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
- Prompt-driven; no Python modules yet
- AI researchers use `prompts/deep_researcher.md` and `prompts/earnings_call_analyst.md` to gather structured evidence

**Stage 03 — Processing** (`pipeline/03_processing/`)
- Entry point: `synthesizer.py` → `build_packet(...)` assembles an `EvidencePacket`
- `evidence_types.py` is the type contract between stages; every downstream field is defined here
- `contradiction_detector.py` runs O(n²) pairwise comparison over evidence items; items sharing a category with opposing BULLISH/BEARISH directions are flagged as contradictions, severity-ranked by source reliability
- `catalyst_mapper.py` builds and priority-sorts catalysts; binary events (uncertain outcome) are elevated above directional ones
- Schema contract: `schemas/output.json` (evidence packet)

**Stages 04–07** — in progress (scoring, debate, synthesis, output)

## Key Design Invariants

**Schema contracts are the inter-layer API.** Do not modify a schema without checking all downstream consumers. `evidence_types.py` is the single source of truth for what Layer 3 can access — any field Layer 3 needs must be declared there.

**Evidence reliability hierarchy is enforced.** `SOURCE_RELIABILITY_DEFAULTS` in `evidence_types.py` assigns weights: SEC filings (0.95) down to social media (0.20). Contradiction severity is computed from the minimum reliability of the two conflicting sources.

**Regime classification drives all screening thresholds.** Score thresholds and shortlist caps vary by regime (e.g., `LIQUIDITY_CONTRACTION` requires ≥68 composite and caps at 8 tickers; `RISK_ON_MOMENTUM` requires ≥52 and allows 20). Rules fire in priority order; first match wins.

**Contradictions are first-class outputs.** `detect_contradictions()` mutates `EvidenceItem` objects in place (sets `contradiction_flag`, `contradiction_with`). Unresolved HIGH-severity contradictions apply uncertainty penalties in Layer 3.

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
| 02 Research | Prompt-only (no Python yet) |
| 03 Processing | Complete |
| 04–07 Scoring, Debate, Synthesis, Output | In progress |
| Data ingestion | Pending (Mac mini + Claude Code) |
