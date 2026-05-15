# Layer 2 — Deep Research Synthesis

## What This Layer Does
Takes each ticker from the Layer 1 shortlist and builds a complete,
structured evidence packet. This packet is the document Layer 3 operates on.

The quality of Layer 3 analysis is entirely dependent on what Layer 2 produces.

## Files

```
layer2_research/
├── schemas/
│   └── evidence_packet.json         — Master evidence packet schema (Layer 2→3 contract)
│
├── research/
│   ├── evidence_types.py            — All enums, dataclasses, type definitions
│   ├── contradiction_detector.py    — Detects conflicts between evidence items
│   ├── catalyst_mapper.py           — Structures and prioritizes catalysts
│   └── synthesizer.py               — Assembles complete packet (entry point: build_packet)
│
└── prompts/
    ├── deep_researcher.md           — Master research protocol (Perplexity + Grok)
    └── earnings_call_analyst.md     — Specialized transcript analysis prompt
```

## The Evidence Item — The Atomic Unit

Every claim in the system must be traceable to an EvidenceItem with:
- What it says (content)
- Where it came from (source, source_type)
- How reliable that source is (reliability, 0–1)
- Which direction it points (bullish / bearish / neutral / binary)
- What category of the thesis it relates to

No unsourced assertions. No implicit assumptions.

## Source Reliability Hierarchy

| Source Type               | Default Reliability |
|---------------------------|---------------------|
| SEC filings               | 0.95                |
| Earnings call transcripts | 0.85                |
| Management / IR direct    | 0.80                |
| Tier-1 financial press    | 0.75                |
| Macro / Fed data          | 0.70                |
| Technical analysis        | 0.70                |
| Sell-side analyst reports | 0.65                |
| Industry / trade press    | 0.50                |
| Perplexity synthesis      | 0.55                |
| Grok / sentiment          | 0.40                |
| Social media / blogs      | 0.20                |

## Contradiction Detection

The contradiction detector runs automatically in `synthesizer.build_packet()`.

A contradiction is detected when:
1. Two evidence items share the same EvidenceCategory
2. One is BULLISH, the other is BEARISH
3. Both have reliability ≥ 0.30

Severity:
- HIGH: both reliability ≥ 0.70 — must be resolved before Layer 3 proceeds
- MEDIUM: one ≥ 0.50 — requires explanation
- LOW: both < 0.50 — noted but does not block

## Evidence Minimums (enforced by schema)
- Total evidence items: minimum 12, maximum 40
- Bearish items: minimum 3 (a bear case that can't find 3 items is not researched)
- Thesis invalidation conditions: minimum 3, maximum 7
- Risk factors: minimum 3, maximum 7

## The Evidence Summary
The bull_case and bear_case in the summary are AI-generated narrative.
They must be:
- Evidence-based: every claim traceable to an EvidenceItem with reliability ≥ 0.65
- Equal in rigor: asymmetric effort between bull and bear = confirmation bias
- 2–4 sentences each: not a paragraph, not a bullet list

## Layer 3 Input Contract
Layer 3 receives the complete EvidencePacket and uses:
- fundamentals: for financial quality scoring
- contradictions: for uncertainty penalties
- thesis_invalidation_conditions: for risk score
- catalyst_map: for binary event penalties
- business_quality: for moat and management scoring
- summary: as context for analyst role prompts

## Usage (once Claude Code environment is ready)

```python
from research.synthesizer import build_packet
from research.evidence_types import (
    Fundamentals, BusinessQuality, TechnicalState,
    EvidenceItem, Catalyst, ThesisInvalidationCondition,
    RiskFactor, DataFreshness, SourceType, EvidenceDirection,
    EvidenceCategory
)

packet = build_packet(
    ticker="NVDA",
    company_name="NVIDIA Corporation",
    sector="XLK",
    screening_reference="SCR-20250514-0930-A3F1",
    screening_score=81.4,
    screening_reason_codes=["MOMENTUM_BREAKOUT", "RS_MARKET_LEADER"],
    screening_flags=[],
    fundamentals=my_fundamentals,
    business_quality=my_biz_quality,
    technical_state=my_technical,
    catalysts=my_catalysts,
    evidence_items=my_evidence,
    thesis_invalidation_conditions=my_tics,
    risk_factors=my_risks,
    bull_case="...",
    bear_case="...",
    key_questions=["...", "...", "..."],
)
```
