"""
synthesizer.py
Assembles all Layer 2 research components into a complete EvidencePacket.

Entry point: build_packet()

This module handles structural assembly only:
  - Runs contradiction detection across evidence items
  - Sorts catalysts by priority
  - Computes evidence count breakdown
  - Generates packet ID and metadata

Narrative synthesis (bull_case, bear_case, key_questions) must be provided
by the AI researcher. The synthesizer does not generate prose.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from evidence_types import (
    EvidencePacket,
    EvidenceItem,
    Catalyst,
    Contradiction,
    ThesisInvalidationCondition,
    RiskFactor,
    Fundamentals,
    BusinessQuality,
    TechnicalState,
    EvidenceSummary,
    DataFreshness,
    EvidenceDirection,
)
from contradiction_detector import detect_contradictions, summarize_contradictions
from catalyst_mapper import sort_catalysts


def build_packet(
    # Identity
    ticker:                 str,
    company_name:           str,
    sector:                 str,
    screening_reference:    str,
    screening_score:        float,
    screening_reason_codes: List[str],
    screening_flags:        List[str],

    # Structured research
    fundamentals:           Fundamentals,
    business_quality:       BusinessQuality,
    technical_state:        TechnicalState,

    # Catalysts and evidence
    catalysts:              List[Catalyst],
    evidence_items:         List[EvidenceItem],
    thesis_invalidation_conditions: List[ThesisInvalidationCondition],
    risk_factors:           List[RiskFactor],

    # AI-generated narrative synthesis
    bull_case:              str,
    bear_case:              str,
    key_questions:          List[str],

    # Optional
    data_freshness:         Optional[DataFreshness] = None,
) -> EvidencePacket:
    """
    Build and return a complete EvidencePacket.

    Automatically:
      - Runs contradiction detection (mutates evidence_items in place)
      - Sorts catalysts by priority
      - Counts evidence by direction
      - Generates packet ID

    Args:
        bull_case:       2–4 sentence synthesis of bullish evidence (from AI researcher)
        bear_case:       2–4 sentence synthesis of bearish evidence (from AI researcher)
        key_questions:   Unresolved questions for the Layer 3 analyst roles

    Returns:
        A fully assembled EvidencePacket ready for Layer 3.
    """

    # ── Run contradiction detection ───────────
    contradictions = detect_contradictions(evidence_items)

    # ── Sort catalysts ────────────────────────
    sorted_catalysts = sort_catalysts(catalysts)

    # ── Evidence count breakdown ──────────────
    ev_count = {
        "bullish": sum(1 for e in evidence_items
                       if e.direction == EvidenceDirection.BULLISH),
        "bearish": sum(1 for e in evidence_items
                       if e.direction == EvidenceDirection.BEARISH),
        "neutral": sum(1 for e in evidence_items
                       if e.direction == EvidenceDirection.NEUTRAL),
        "binary":  sum(1 for e in evidence_items
                       if e.direction == EvidenceDirection.BINARY),
    }

    summary = EvidenceSummary(
        bull_case=bull_case,
        bear_case=bear_case,
        key_questions=key_questions,
        evidence_count=ev_count,
    )

    contradiction_summary = summarize_contradictions(contradictions)

    # ── Assemble packet ───────────────────────
    return EvidencePacket(
        packet_id=_make_packet_id(ticker),
        ticker=ticker,
        company_name=company_name,
        sector=sector,
        generated_at=datetime.now(timezone.utc).isoformat(),
        screening_reference=screening_reference,
        screening_score=round(screening_score, 2),
        screening_reason_codes=screening_reason_codes,
        screening_flags=screening_flags,

        fundamentals=fundamentals,
        business_quality=business_quality,
        technical_state=technical_state,

        catalyst_map=sorted_catalysts,
        evidence_items=evidence_items,
        contradictions=contradictions,
        thesis_invalidation_conditions=thesis_invalidation_conditions,
        risk_factors=risk_factors,

        summary=summary,
        data_freshness=data_freshness or DataFreshness(),

        metadata={
            "contradiction_summary":   contradiction_summary,
            "evidence_item_count":     len(evidence_items),
            "catalyst_count":          len(sorted_catalysts),
            "risk_factor_count":       len(risk_factors),
            "tic_count":               len(thesis_invalidation_conditions),
            "high_severity_unresolved_contradictions":
                contradiction_summary.get("high", 0),
        },
    )


def _make_packet_id(ticker: str) -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"EP-{ticker}-{ts}-{rand}"
