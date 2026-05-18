"""
debate_recorder.py
Entry point for the Layer 5 debate recording pass.

Takes the EvidencePacket (Layer 3), ScoringOutput (Layer 4), and the structured
positions from the Bull and Bear analyst roles, then produces a complete
DebateRecord for Layer 6 synthesis.

Entry point: record_debate(packet, scoring, bull_pos, bear_pos) -> DebateRecord

Sequence:
  1. Parse and validate analyst positions from raw dicts
  2. Auto-detect contentions from overlapping evidence citations
  3. Compute debate-adjusted scores and classify outcome
  4. Assemble and return DebateRecord
"""

import uuid
from datetime import datetime, timezone

from debate_types import AnalystPosition, AnalystRole, DebateRecord
from contention_detector import detect_contentions
from debate_scorer import compute_debate_scores


def record_debate(
    packet:   dict,
    scoring:  dict,
    bull_pos: dict,
    bear_pos: dict,
) -> DebateRecord:
    """
    Record and score a bull vs bear debate for a single ticker.

    Args:
        packet:   EvidencePacket dict (pipeline/03_processing/schemas/output.json)
        scoring:  ScoringOutput dict  (pipeline/04_scoring/schemas/output.json)
        bull_pos: Bull analyst position dict, produced by the Bull Analyst role
                  using the brief from position_builder.build_bull_brief()
        bear_pos: Bear analyst position dict, produced by the Bear Analyst role
                  using the brief from position_builder.build_bear_brief()

    Returns:
        DebateRecord ready for Layer 6 synthesis.
    """
    ticker       = packet.get("ticker", "UNKNOWN")
    company_name = packet.get("company_name", "")
    packet_id    = packet.get("packet_id", "")
    score_id     = scoring.get("score_id", "")

    evidence_items = packet.get("evidence_items", [])

    # ── Step 1: Parse analyst positions ───────────────────────────────────────
    bull = _parse_position(bull_pos, AnalystRole.BULL)
    bear = _parse_position(bear_pos, AnalystRole.BEAR)

    # ── Step 2: Detect contentions ─────────────────────────────────────────────
    contentions = detect_contentions(evidence_items, bull_pos, bear_pos)

    # ── Step 3: Compute debate-adjusted scores ─────────────────────────────────
    base_ev   = float(scoring.get("evidence_score",   0.0))
    base_conf = float(scoring.get("confidence_score", 0.0))

    scores = compute_debate_scores(
        base_evidence_score=base_ev,
        base_confidence_score=base_conf,
        bull_score_adj=bull.score_adjustment,
        bull_conf_adj=bull.confidence_adjustment,
        bear_score_adj=bear.score_adjustment,
        bear_conf_adj=bear.confidence_adjustment,
    )

    # ── Step 4: Assemble DebateRecord ──────────────────────────────────────────
    return DebateRecord(
        debate_id=_make_debate_id(ticker),
        score_reference=score_id,
        packet_reference=packet_id,
        ticker=ticker,
        company_name=company_name,
        debated_at=datetime.now(timezone.utc).isoformat(),

        bull_position=bull,
        bear_position=bear,
        contentions=contentions,

        base_evidence_score=round(base_ev, 1),
        base_confidence_score=round(base_conf, 1),
        debate_evidence_score=scores["debate_evidence_score"],
        debate_confidence_score=scores["debate_confidence_score"],
        net_score_adjustment=scores["net_score_adjustment"],
        outcome=scores["outcome"],

        original_conviction=scoring.get("conviction", ""),
        original_recommendation=scoring.get("recommendation", ""),

        metadata={
            "net_conf_adjustment":  scores["net_conf_adjustment"],
            "contention_count":     len(contentions),
            "critical_contentions": sum(1 for c in contentions if c.severity.value == "critical"),
            "material_contentions": sum(1 for c in contentions if c.severity.value == "material"),
            "bull_evidence_cited":  len(bull.evidence_cited),
            "bear_evidence_cited":  len(bear.evidence_cited),
            "bull_contested":       len(bull.contested_items),
            "bear_contested":       len(bear.contested_items),
            "raised_risks_count":   len(bull.raised_risks) + len(bear.raised_risks),
        },
    )


def _parse_position(pos: dict, role: AnalystRole) -> AnalystPosition:
    """Parse a raw analyst position dict into an AnalystPosition, with safe defaults."""
    return AnalystPosition(
        analyst_role=role,
        summary=str(pos.get("summary", "")),
        key_arguments=list(pos.get("key_arguments", [])),
        evidence_cited=list(pos.get("evidence_cited", [])),
        contested_items=list(pos.get("contested_items", [])),
        raised_risks=list(pos.get("raised_risks", [])),
        score_adjustment=float(pos.get("score_adjustment", 0.0)),
        confidence_adjustment=float(pos.get("confidence_adjustment", 0.0)),
    )


def _make_debate_id(ticker: str) -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"DB-{ticker}-{ts}-{rand}"
