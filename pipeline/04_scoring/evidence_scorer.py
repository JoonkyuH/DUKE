"""
evidence_scorer.py
Computes a weighted net evidence score from the evidence items in an EvidencePacket.

Evidence score represents the directional balance of the research:
  +100 = all high-reliability bullish evidence
  -100 = all high-reliability bearish evidence
     0 = perfectly balanced or no directional evidence

Formula:
  net_score = (bull_weight - bear_weight) / (bull_weight + bear_weight) * 100

NEUTRAL and BINARY items contribute to total_weight (tracked for confidence scoring)
but are excluded from the directional net_score. This keeps the evidence score
focused on direction while letting confidence scoring penalize uncertainty.
"""

from typing import List, Dict, Any
from score_types import EvidenceScoreBreakdown


def score_evidence(evidence_items: List[dict]) -> EvidenceScoreBreakdown:
    """
    Compute a weighted net evidence score from a list of evidence item dicts.

    Args:
        evidence_items: Each dict must have:
          direction   (str):   "bullish" | "bearish" | "neutral" | "binary"
          reliability (float): 0–1

    Returns:
        EvidenceScoreBreakdown with all weight components and a net_score in [-100, 100].
    """
    bull_weight    = 0.0
    bear_weight    = 0.0
    neutral_weight = 0.0
    binary_weight  = 0.0
    high_rel_count = 0

    for item in evidence_items:
        rel       = float(item.get("reliability", 0.0))
        direction = str(item.get("direction") or "neutral").lower()

        if rel >= 0.70:
            high_rel_count += 1

        if direction == "bullish":
            bull_weight += rel
        elif direction == "bearish":
            bear_weight += rel
        elif direction == "binary":
            binary_weight += rel
        else:
            neutral_weight += rel

    total_weight    = bull_weight + bear_weight + neutral_weight + binary_weight
    directional_sum = bull_weight + bear_weight

    if directional_sum == 0.0:
        net_score = 0.0
    else:
        net_score = (bull_weight - bear_weight) / directional_sum * 100.0

    return EvidenceScoreBreakdown(
        bull_weight=round(bull_weight, 3),
        bear_weight=round(bear_weight, 3),
        neutral_weight=round(neutral_weight, 3),
        binary_weight=round(binary_weight, 3),
        total_weight=round(total_weight, 3),
        net_score=round(net_score, 1),
        directional_count=sum(
            1 for item in evidence_items
            if str(item.get("direction") or "").lower() in ("bullish", "bearish")
        ),
        high_reliability_count=high_rel_count,
    )


def score_evidence_split(evidence_items: List[dict]) -> Dict[str, Any]:
    """
    Compute two independent scores from evidence items split by evidence_nature.

    directional_thesis_score:
        Net directional balance excluding disclosed_risk items.
        Same formula as score_evidence() but restricted to items where
        evidence_nature != "disclosed_risk". Risk factor disclosures are
        a possibility checklist, not active negative evidence.

    risk_burden_score:
        Structural risk burden carried by this position [0-100].
        Derived from disclosed_risk items only.
        Formula: min(100, count * avg_reliability * 20)
          3 items @ 0.95 = 57    5 items @ 0.95 = 95

    Returns a dict with:
        directional_thesis_score  float  [-100, 100]
        risk_burden_score         float  [0, 100]
        directional_items_count   int    items contributing to DTS
        risk_items_count          int    disclosed_risk items
        risk_items                list   the disclosed_risk items (for downstream)
    """
    thesis_items = [
        e for e in evidence_items
        if e.get("evidence_nature") != "disclosed_risk"
    ]
    risk_items = [
        e for e in evidence_items
        if e.get("evidence_nature") == "disclosed_risk"
    ]

    # Directional thesis score — same formula as score_evidence()
    bull_w = bear_w = 0.0
    for item in thesis_items:
        rel = float(item.get("reliability", 0.0))
        direction = str(item.get("direction") or "neutral").lower()
        if direction == "bullish":
            bull_w += rel
        elif direction == "bearish":
            bear_w += rel

    directional_sum = bull_w + bear_w
    if directional_sum == 0.0:
        dts = 0.0
    else:
        dts = (bull_w - bear_w) / directional_sum * 100.0

    # Risk burden score — count * avg_reliability * 20, capped at 100
    if risk_items:
        avg_rel = sum(float(e.get("reliability", 0.0)) for e in risk_items) / len(risk_items)
        rbs = min(100.0, len(risk_items) * avg_rel * 20)
    else:
        rbs = 0.0

    return {
        "directional_thesis_score": round(dts, 1),
        "risk_burden_score":        round(rbs, 1),
        "directional_items_count":  sum(
            1 for e in thesis_items
            if str(e.get("direction") or "").lower() in ("bullish", "bearish")
        ),
        "risk_items_count":         len(risk_items),
        "risk_items":               risk_items,
    }
