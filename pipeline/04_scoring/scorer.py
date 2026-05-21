"""
scorer.py
Entry point for the Layer 4 scoring pass.

Takes a complete EvidencePacket (as a dict conforming to the evidence_packet schema)
and produces a ScoringOutput with conviction, recommendation, and position sizing.

Entry point: score_packet(packet: dict) -> ScoringOutput

Scoring sequence:
  1. Check thesis invalidation conditions — FATAL short-circuits to INVALIDATED
  2. Score evidence: net directional balance [-100, 100]
  3. Score confidence: quality + penalties + bonuses [0, 100]
  4. Determine conviction level from (evidence_score, confidence_score)
  5. Map conviction → recommendation
  6. Map conviction + invalidation + imminent binary catalysts → position sizing
  7. Extract primary risks for human review
  8. Assemble ScoringOutput
"""

import uuid
from datetime import datetime, timezone
from typing import List

from score_types import (
    ScoringOutput,
    ConvictionLevel,
    Recommendation,
    PositionSizing,
    InvalidationStatus,
    InvalidationReport,
)
from evidence_scorer import score_evidence
from confidence_scorer import score_confidence
from invalidation_checker import check_invalidation


# ─────────────────────────────────────────────
# CONVICTION THRESHOLDS
# Rules are evaluated in order; first match wins.
#
# Bear path (added v1.1.0): evidence_score < -15 is evaluated using
# abs(evidence_score) against _BEAR_RULES thresholds — symmetric to bull.
# Neutral band: -15 ≤ evidence_score < +15 → WATCH.
# ─────────────────────────────────────────────

# Bull path + neutral band: standard >= comparison on evidence_score
_BULL_WATCH_RULES = [
    # (evidence_score_min, confidence_score_min, ConvictionLevel)
    (55.0,  70.0, ConvictionLevel.HIGH),
    (35.0,  55.0, ConvictionLevel.MEDIUM),
    (15.0,  40.0, ConvictionLevel.LOW),
    (-15.0, 40.0, ConvictionLevel.WATCH),   # neutral band: -15 ≤ ev < +15
]

# Bear path: evaluated as abs(evidence_score) >= threshold (strongest first)
_BEAR_RULES = [
    # (abs_evidence_score_min, confidence_score_min, ConvictionLevel)
    (55.0, 70.0, ConvictionLevel.HIGH_BEAR),
    (35.0, 55.0, ConvictionLevel.MEDIUM_BEAR),
    (15.0, 40.0, ConvictionLevel.LOW_BEAR),
]

# If confidence is below this floor, cap conviction at INSUFFICIENT regardless of evidence score.
_CONFIDENCE_FLOOR = 30.0


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def score_packet(packet: dict) -> ScoringOutput:
    """
    Score a complete EvidencePacket dict (conforming to the evidence_packet schema).

    Args:
        packet: Dict matching pipeline/03_processing/schemas/output.json

    Returns:
        ScoringOutput ready for Layer 5 debate and Layer 6 synthesis.
    """
    ticker        = packet.get("ticker", "UNKNOWN")
    company_name  = packet.get("company_name", "")
    packet_id     = packet.get("packet_id", "")

    evidence_items = packet.get("evidence_items", [])
    contradictions = packet.get("contradictions", [])
    catalyst_map   = packet.get("catalyst_map", [])
    tics           = packet.get("thesis_invalidation_conditions", [])
    risk_factors   = packet.get("risk_factors", [])
    data_freshness = packet.get("data_freshness", {})
    fundamentals   = packet.get("fundamentals", {})
    reason_codes   = packet.get("screening_reason_codes", [])
    screening_score= float(packet.get("screening_score", 0.0))

    # ── Step 1: Invalidation check ─────────────────────────────────────────────
    inv_report = check_invalidation(tics)

    # ── Step 2: Evidence score ─────────────────────────────────────────────────
    ev_breakdown = score_evidence(evidence_items)

    # ── Step 3: Confidence score ───────────────────────────────────────────────
    conf_breakdown = score_confidence(
        evidence_items=evidence_items,
        contradictions=contradictions,
        catalyst_map=catalyst_map,
        data_freshness=data_freshness,
        screening_reason_codes=reason_codes,
        fundamentals=fundamentals,
    )

    evidence_score   = ev_breakdown.net_score
    confidence_score = conf_breakdown.final_confidence

    # ── Step 4: Conviction ─────────────────────────────────────────────────────
    if inv_report.status == InvalidationStatus.FATAL:
        conviction = ConvictionLevel.INSUFFICIENT
    else:
        conviction = _determine_conviction(evidence_score, confidence_score)

    # ── Step 5: Recommendation ─────────────────────────────────────────────────
    recommendation = _determine_recommendation(
        conviction, evidence_score, inv_report.status
    )

    # ── Step 6: Position sizing ────────────────────────────────────────────────
    position_sizing = _determine_position_sizing(
        conviction, inv_report, catalyst_map
    )

    # ── Step 7: Primary risks ──────────────────────────────────────────────────
    primary_risks = _extract_primary_risks(risk_factors)

    return ScoringOutput(
        score_id=_make_score_id(ticker),
        packet_reference=packet_id,
        ticker=ticker,
        company_name=company_name,
        scored_at=datetime.now(timezone.utc).isoformat(),
        evidence_score=evidence_score,
        confidence_score=confidence_score,
        conviction=conviction,
        recommendation=recommendation,
        position_sizing=position_sizing,
        evidence_breakdown=ev_breakdown,
        confidence_breakdown=conf_breakdown,
        invalidation_report=inv_report,
        primary_risks=primary_risks,
        screening_score=screening_score,
        screening_reason_codes=reason_codes,
        evidence_score_note=_make_evidence_note(ev_breakdown),
        confidence_score_note=_make_confidence_note(conf_breakdown),
        metadata={
            "evidence_item_count": len(evidence_items),
            "contradiction_count": len(contradictions),
            "catalyst_count":      len(catalyst_map),
            "tic_count":           len(tics),
            "risk_factor_count":   len(risk_factors),
        },
    )


# ─────────────────────────────────────────────
# CONVICTION
# ─────────────────────────────────────────────

def _determine_conviction(
    evidence_score:  float,
    confidence_score: float,
) -> ConvictionLevel:
    if confidence_score < _CONFIDENCE_FLOOR:
        return ConvictionLevel.INSUFFICIENT

    # Bull path and neutral band (standard >= comparison)
    for ev_min, conf_min, level in _BULL_WATCH_RULES:
        if evidence_score >= ev_min and confidence_score >= conf_min:
            return level

    # Bear path: evidence_score < -15; evaluate abs value against bear thresholds
    abs_ev = abs(evidence_score)
    for ev_min, conf_min, level in _BEAR_RULES:
        if abs_ev >= ev_min and confidence_score >= conf_min:
            return level

    return ConvictionLevel.INSUFFICIENT


# ─────────────────────────────────────────────
# RECOMMENDATION
# ─────────────────────────────────────────────

_CONVICTION_TO_RECOMMENDATION = {
    ConvictionLevel.HIGH:         Recommendation.STRONG_CONVICTION_ENTER,
    ConvictionLevel.MEDIUM:       Recommendation.MODERATE_CONVICTION_ENTER,
    ConvictionLevel.LOW:          Recommendation.WATCH_POSITIVE,
    ConvictionLevel.WATCH:        Recommendation.WATCH_NEUTRAL,
    ConvictionLevel.LOW_BEAR:     Recommendation.WATCH_NEGATIVE,
    ConvictionLevel.MEDIUM_BEAR:  Recommendation.AVOID,
    ConvictionLevel.HIGH_BEAR:    Recommendation.STRONG_AVOID,
    ConvictionLevel.INSUFFICIENT: Recommendation.INSUFFICIENT_DATA,
}


def _determine_recommendation(
    conviction:          ConvictionLevel,
    evidence_score:      float,
    invalidation_status: InvalidationStatus,
) -> Recommendation:
    if invalidation_status == InvalidationStatus.FATAL:
        return Recommendation.INVALIDATED

    return _CONVICTION_TO_RECOMMENDATION.get(conviction, Recommendation.INSUFFICIENT_DATA)


# ─────────────────────────────────────────────
# POSITION SIZING
# ─────────────────────────────────────────────

_SIZE_ORDER = [
    PositionSizing.FULL,
    PositionSizing.HALF,
    PositionSizing.QUARTER,
    PositionSizing.PILOT,
    PositionSizing.NONE,
]

_BASE_SIZING = {
    # Bull path
    ConvictionLevel.HIGH:         PositionSizing.FULL,
    ConvictionLevel.MEDIUM:       PositionSizing.HALF,
    ConvictionLevel.LOW:          PositionSizing.QUARTER,
    # Neutral / bear / fallback — no long position
    ConvictionLevel.WATCH:        PositionSizing.NONE,
    ConvictionLevel.LOW_BEAR:     PositionSizing.NONE,
    ConvictionLevel.MEDIUM_BEAR:  PositionSizing.NONE,
    ConvictionLevel.HIGH_BEAR:    PositionSizing.NONE,
    ConvictionLevel.INSUFFICIENT: PositionSizing.NONE,
}


def _downgrade(sizing: PositionSizing) -> PositionSizing:
    idx = _SIZE_ORDER.index(sizing)
    return _SIZE_ORDER[min(idx + 1, len(_SIZE_ORDER) - 1)]


def _determine_position_sizing(
    conviction:   ConvictionLevel,
    inv_report:   InvalidationReport,
    catalyst_map: List[dict],
) -> PositionSizing:
    sizing = _BASE_SIZING[conviction]

    # Active FATAL or MAJOR invalidation: reduce exposure
    if inv_report.status in (InvalidationStatus.FATAL, InvalidationStatus.MAJOR):
        sizing = _downgrade(sizing)

    # HIGH-impact BINARY catalyst within 7 days: binary gap risk, reduce exposure
    imminent_binary = any(
        c.get("direction") == "binary"
        and c.get("expected_impact") == "high"
        and c.get("days_away") is not None
        and 0 <= int(c["days_away"]) <= 7
        for c in catalyst_map
    )
    if imminent_binary:
        sizing = _downgrade(sizing)

    return sizing


# ─────────────────────────────────────────────
# RISK EXTRACTION
# ─────────────────────────────────────────────

_PROB_RANK   = {"high": 0, "medium": 1, "low": 2}
_IMPACT_RANK = {"high": 0, "medium": 1, "low": 2}


def _extract_primary_risks(risk_factors: List[dict], n: int = 3) -> List[str]:
    """Return descriptions of the top-n risks, sorted by probability then impact."""
    sorted_risks = sorted(
        risk_factors,
        key=lambda r: (
            _PROB_RANK.get(r.get("probability", "low"), 2),
            _IMPACT_RANK.get(r.get("impact", "low"), 2),
        ),
    )
    return [r.get("description", "") for r in sorted_risks[:n]]


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _make_evidence_note(ev: "EvidenceScoreBreakdown") -> str:
    return (
        f"{ev.directional_count} directional items; "
        f"bull weight {ev.bull_weight:.2f} vs bear {ev.bear_weight:.2f} "
        f"→ net {ev.net_score:+.1f}"
    )


def _make_confidence_note(cf: "ConfidencePenaltyBreakdown") -> str:
    parts = [f"base {cf.base_confidence:.1f}"]
    if cf.total_penalty > 0:
        penalty_detail = []
        if cf.contradiction_penalty:
            penalty_detail.append(f"contradiction −{cf.contradiction_penalty:.1f}")
        if cf.binary_catalyst_penalty:
            penalty_detail.append(f"binary catalyst −{cf.binary_catalyst_penalty:.1f}")
        if cf.stale_data_penalty:
            penalty_detail.append(f"stale data −{cf.stale_data_penalty:.1f}")
        if cf.thin_evidence_penalty:
            penalty_detail.append(f"thin evidence −{cf.thin_evidence_penalty:.1f}")
        parts.append("penalties: " + ", ".join(penalty_detail))
    if cf.bonuses > 0:
        parts.append(f"bonuses +{cf.bonuses:.1f}")
    return "  /  ".join(parts) + f"  →  {cf.final_confidence:.1f}"


def _make_score_id(ticker: str) -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"SC-{ticker}-{ts}-{rand}"
