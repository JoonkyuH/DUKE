# DUKE ("Doesn't Usually Know Either") — Investment Intelligence Framework

A multi-agent investment analysis system built around structured evidence,
explicit uncertainty, and disciplined human review.

DUKE is not a trading bot. It does not execute trades, manage positions,
or make investment decisions. It compresses research, surfaces contradictions,
and produces structured recommendation packets that a human reviews before
any capital is deployed.

---

## Architecture

DUKE processes investment opportunities through three analytical layers,
each with a defined input contract and output schema.

```
Raw Data Sources
(TradingView · NewsAPI · SEC EDGAR · Perplexity · Grok)
        │
        ▼
┌─────────────────────────────────┐
│  LAYER 1 — Initial Screening    │  Scores 6 signals per ticker.
│  layer1_screening/              │  Outputs: 5–20 ticker shortlist.
└─────────────────────────────────┘
        │  5–20 ticker shortlist
        ▼
┌─────────────────────────────────┐
│  LAYER 2 — Deep Research        │  Builds structured evidence packet.
│  layer2_research/               │  Outputs: Evidence packet per ticker.
└─────────────────────────────────┘
        │  Evidence packet per ticker
        ▼
┌─────────────────────────────────┐
│  LAYER 3 — Scoring & Assessment │  Weights evidence, scores confidence,
│  layer3_scoring/ (in progress)  │  checks invalidation conditions,
└─────────────────────────────────┘  assesses portfolio fit.
        │  Recommendation packet
        ▼
  Human Review & Decision
```

---

## Role Assignments

| Role               | Tool                  | Responsibility                                      |
|--------------------|-----------------------|-----------------------------------------------------|
| Market Researcher  | Perplexity + Grok     | Gathers raw signal data for Layer 1 and Layer 2     |
| Coder              | Claude Code           | Implements, tests, and runs all Python modules      |
| Orchestrator       | Claude Cowork         | Coordinates analyst roles and assembles output      |
| Chief Analyst      | Claude Finance Agent  | Synthesizes evidence and writes final recommendation|
| Bull Analyst       | Claude Finance Agent  | Constructs strongest possible bullish case          |
| Bear Analyst       | Claude Finance Agent  | Constructs strongest possible bearish case          |
| Risk Officer       | Claude Finance Agent  | Evaluates risk factors and invalidation conditions  |
| Architecture Critic| ChatGPT               | Reviews system design decisions                     |

---

## Repository Structure

```
DUKE/
├── layer1_screening/
│   ├── screening/
│   │   ├── screener.py              # Entry point: run_screening()
│   │   ├── signal_scorer.py         # Six signal scoring functions (0–100)
│   │   ├── regime_classifier.py     # Market regime detection + weight profiles
│   │   └── reason_codes.py          # Reason codes and investigation flags
│   ├── schemas/
│   │   ├── raw_signal_record.json   # Input schema (one record per ticker)
│   │   └── screening_output.json    # Output schema (ticker shortlist)
│   ├── prompts/
│   │   └── market_researcher.md     # System prompt: Market Researcher role
│   └── README.md
│
├── layer2_research/
│   ├── research/
│   │   ├── evidence_types.py        # All enums and dataclasses
│   │   ├── contradiction_detector.py# Detects evidence conflicts
│   │   ├── catalyst_mapper.py       # Structures and prioritizes catalysts
│   │   └── synthesizer.py           # Entry point: build_packet()
│   ├── schemas/
│   │   └── evidence_packet.json     # Master schema (Layer 2→3 contract)
│   ├── prompts/
│   │   ├── deep_researcher.md       # System prompt: Deep Researcher role
│   │   └── earnings_call_analyst.md # System prompt: Transcript analysis
│   └── README.md
│
└── layer3_scoring/                  # IN PROGRESS
    └── ...
```

---

## Design Principles

**Explicit uncertainty over false confidence.**
Every score carries the data it was computed from. Missing data is `null`,
not zero. The system would rather output a low-confidence packet than a
high-confidence one built on gaps.

**Contradictions are features, not bugs.**
The contradiction detector surfaces conflicts between evidence items before
any analyst role sees the packet. Unresolved HIGH-severity contradictions
apply uncertainty penalties in Layer 3.

**Evidence hierarchy is enforced, not suggested.**
SEC filings (0.95 reliability) and social media (0.20 reliability) produce
fundamentally different evidence weights. The system does not treat them equally.

**Human review is the last and most important layer.**
The system produces recommendation packets. It does not size positions,
execute trades, or override the investor's judgment.

---

## Build Status

| Layer               | Status         | Notes                                      |
|---------------------|----------------|--------------------------------------------|
| Layer 1 — Screening | ✅ Complete    | Schemas, scoring logic, regime classifier  |
| Layer 2 — Research  | ✅ Complete    | Evidence packet, contradiction detection   |
| Layer 3 — Scoring   | 🔄 In progress | Evidence weighting, confidence, risk score |
| Data ingestion      | ⏳ Pending     | Requires Mac mini + Claude Code            |
| Analyst prompts     | ⏳ Pending     | Bull, Bear, Chief, Risk Officer roles      |
| Output format       | ⏳ Pending     | Human-readable recommendation packet      |
| Journal / postmortem| ⏳ Pending     | Feedback loop for system improvement       |

---

## For Claude Code

When you pull this repo, read this file first, then each layer's README
before touching any code. The schemas define the data contracts between layers —
do not modify a schema without checking all downstream consumers.

Entry points:
- Layer 1: `layer1_screening/screening/screener.py` → `run_screening()`
- Layer 2: `layer2_research/research/synthesizer.py` → `build_packet()`
- Layer 3: `layer3_scoring/scorer.py` → `score_packet()` (not yet built)

Python stdlib only through Layer 2. Layer 3 will require `jsonschema`.
Data ingestion modules will require `requests`, `pandas`, and source-specific SDKs.
