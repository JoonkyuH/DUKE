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

from typing import List
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
