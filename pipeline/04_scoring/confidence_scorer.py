"""
confidence_scorer.py
Computes a confidence score [0, 100] for an evidence packet.

Confidence answers: "How much should we trust this evidence score?"

Unlike the evidence score (directional balance), confidence measures the
quality and completeness of the evidence base itself.

Base confidence is derived from:
  - Evidence quality: average reliability of directional items (BULLISH + BEARISH)
  - Evidence volume: count of directional items, saturating at QUALITY_SATURATION

Penalties applied for structural weaknesses:
  - Unresolved HIGH-severity contradictions: two reliable sources conflict
  - HIGH-impact BINARY catalysts: outcome-uncertain events approaching
  - Stale data fields: information may be materially outdated
  - Thin evidence base: not enough directional items to form a view

Bonuses for strong signals:
  - MULTI_SIGNAL_CONFLUENCE from Layer 1 (multi-factor technical alignment)
  - RS_MARKET_LEADER from Layer 1 (strong relative price leadership)
  - Research dominated by high-reliability sources (>= 0.80)
  - Positive FCF and above-consensus guidance (fundamental confirmation)
"""

from typing import List, Optional
from score_types import ConfidencePenaltyBreakdown


MIN_DIRECTIONAL_ITEMS = 6    # Below this, thin-evidence penalty applies
QUALITY_SATURATION    = 15   # Volume factor saturates at this many directional items


def score_confidence(
    evidence_items:         List[dict],
    contradictions:         List[dict],
    catalyst_map:           List[dict],
    data_freshness:         dict,
    screening_reason_codes: List[str],
    fundamentals:           Optional[dict] = None,
) -> ConfidencePenaltyBreakdown:
    """
    Compute a confidence score with full penalty and bonus breakdown.

    Args:
        evidence_items:         From EvidencePacket
        contradictions:         From EvidencePacket (post contradiction_detector)
        catalyst_map:           From EvidencePacket (sorted catalysts)
        data_freshness:         From EvidencePacket.data_freshness
        screening_reason_codes: From EvidencePacket.screening_reason_codes
        fundamentals:           From EvidencePacket.fundamentals (optional)

    Returns:
        ConfidencePenaltyBreakdown with all components and final_confidence.
    """
    # ── Base confidence ────────────────────────────────────────────────────────
    directional = [
        item for item in evidence_items
        if str(item.get("direction") or "").lower() in ("bullish", "bearish")
    ]
    n = len(directional)

    if n == 0:
        base = 0.0
    else:
        avg_reliability = sum(item.get("reliability", 0.0) for item in directional) / n
        quality_factor  = avg_reliability * 100.0
        volume_factor   = min(n / QUALITY_SATURATION, 1.0) * 100.0
        base = quality_factor * 0.60 + volume_factor * 0.40

    # ── Penalties ──────────────────────────────────────────────────────────────
    contradiction_penalty   = _contradiction_penalty(contradictions)
    binary_catalyst_penalty = _binary_catalyst_penalty(catalyst_map)
    stale_data_penalty      = _stale_data_penalty(data_freshness)
    thin_evidence_penalty   = 15.0 if n < MIN_DIRECTIONAL_ITEMS else 0.0

    total_penalty = (
        contradiction_penalty
        + binary_catalyst_penalty
        + stale_data_penalty
        + thin_evidence_penalty
    )

    # ── Bonuses ────────────────────────────────────────────────────────────────
    bonuses = _compute_bonuses(
        evidence_items, screening_reason_codes, fundamentals or {}
    )

    final = max(0.0, min(100.0, base - total_penalty + bonuses))

    return ConfidencePenaltyBreakdown(
        base_confidence=round(base, 1),
        contradiction_penalty=round(contradiction_penalty, 1),
        binary_catalyst_penalty=round(binary_catalyst_penalty, 1),
        stale_data_penalty=round(stale_data_penalty, 1),
        thin_evidence_penalty=round(thin_evidence_penalty, 1),
        total_penalty=round(total_penalty, 1),
        bonuses=round(bonuses, 1),
        final_confidence=round(final, 1),
    )


def _contradiction_penalty(contradictions: List[dict]) -> float:
    penalty = 0.0
    for c in contradictions:
        if c.get("resolution", "unresolved") != "unresolved":
            continue
        severity = c.get("severity", "low")
        if severity == "high":
            penalty += 12.0
        elif severity == "medium":
            penalty += 5.0
    # Cap: even many contradictions shouldn't completely zero out confidence —
    # the unresolved conflict is visible to the analyst and can still be weighed.
    return min(penalty, 40.0)


def _binary_catalyst_penalty(catalyst_map: List[dict]) -> float:
    penalty = 0.0
    for cat in catalyst_map:
        if (str(cat.get("direction") or "").lower() == "binary"
                and str(cat.get("expected_impact") or "").lower() == "high"):
            penalty += 8.0
    return min(penalty, 24.0)


def _stale_data_penalty(data_freshness: dict) -> float:
    stale_fields = data_freshness.get("stale_fields", [])
    return min(len(stale_fields) * 4.0, 16.0)


def _compute_bonuses(
    evidence_items:         List[dict],
    screening_reason_codes: List[str],
    fundamentals:           dict,
) -> float:
    bonuses = 0.0

    if "MULTI_SIGNAL_CONFLUENCE" in screening_reason_codes:
        bonuses += 5.0

    if "RS_MARKET_LEADER" in screening_reason_codes:
        bonuses += 3.0

    # Research dominated by high-reliability (>= 0.80) sources
    high_rel = sum(1 for item in evidence_items if item.get("reliability", 0) >= 0.80)
    if evidence_items and high_rel / len(evidence_items) >= 0.50:
        bonuses += 5.0

    # Fundamental confirmation: positive FCF + above-consensus guidance
    fcf     = fundamentals.get("fcf_ttm_m")
    guidance= fundamentals.get("guidance_vs_consensus_pct")
    if fcf is not None and fcf > 0 and guidance is not None and guidance > 0:
        bonuses += 5.0

    return bonuses
