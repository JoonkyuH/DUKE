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

import logging
from typing import List, Dict, Any
from score_types import EvidenceScoreBreakdown

log = logging.getLogger("evidence_scorer")


# Management has an optimism bias — bearish signals from management are
# understated and therefore more meaningful; bullish signals are expected.
_MGMT_DIRECTION_MULTIPLIERS = {
    "bullish": 0.85,
    "bearish": 1.30,
    "neutral": 1.00,
}

# External bear queries are adversarially framed ("risks against", "competitive threat")
# while bull queries are framed more neutrally ("positive developments", "moat").
# Apply a small asymmetric adjustment so the 4+4 split doesn't systematically
# over-weight bear evidence from adversarially-constructed queries.
_EXTERNAL_QUERY_MULTIPLIERS = {
    "external_bull": 1.10,  # slight boost — bull queries are less adversarially framed
    "external_bear": 0.90,  # slight discount — bear queries are adversarially framed
}


def _mgmt_multiplier(item: dict) -> float:
    """Return direction multiplier for management_quote items; 1.0 for all others."""
    if item.get("item_class") != "management_quote":
        return 1.0
    direction = str(item.get("direction") or "neutral").lower()
    return _MGMT_DIRECTION_MULTIPLIERS.get(direction, 1.0)


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
        rel        = float(item.get("reliability", 0.0))
        direction  = str(item.get("direction") or "neutral").lower()
        item_class = item.get("item_class", "")
        if item_class in _EXTERNAL_QUERY_MULTIPLIERS:
            eff_weight = rel * _EXTERNAL_QUERY_MULTIPLIERS[item_class]
        else:
            eff_weight = rel * _mgmt_multiplier(item)

        if rel >= 0.70:
            high_rel_count += 1

        if direction == "bullish":
            bull_weight += eff_weight
        elif direction == "bearish":
            bear_weight += eff_weight
        elif direction == "binary":
            binary_weight += eff_weight
        else:
            neutral_weight += eff_weight

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

    # Directional thesis score — same formula as score_evidence(), with mgmt and
    # external query asymmetry multipliers applied.
    bull_w = bear_w = 0.0
    has_mgmt     = False
    has_external = False
    for item in thesis_items:
        rel        = float(item.get("reliability", 0.0))
        direction  = str(item.get("direction") or "neutral").lower()
        item_class = item.get("item_class", "")
        if item_class in _EXTERNAL_QUERY_MULTIPLIERS:
            eff_weight   = rel * _EXTERNAL_QUERY_MULTIPLIERS[item_class]
            has_external = True
        else:
            eff_weight = rel * _mgmt_multiplier(item)
        if item_class == "management_quote":
            has_mgmt = True
        if direction == "bullish":
            bull_w += eff_weight
        elif direction == "bearish":
            bear_w += eff_weight
        elif (
            direction == "neutral"
            and item_class == "management_quote"
            and str(item.get("significance") or "").upper() == "HIGH"
            and item.get("category") == "guidance"
        ):
            # HIGH-significance guidance with neutral tone is a mild bearish signal —
            # management could have been bullish but chose neutral language.
            mild_bear = eff_weight * 0.08
            bear_w += mild_bear
            log.debug(
                "%s: NEUTRAL HIGH guidance → mild bear signal (eff_weight=%.3f)",
                item.get("ticker", "?"), mild_bear,
            )

    directional_sum = bull_w + bear_w
    if directional_sum == 0.0:
        dts = 0.0
    else:
        dts = (bull_w - bear_w) / directional_sum * 100.0

    # Risk burden score — sum(rel * specificity_weight) * 20, capped at 100
    # specificity_weight: specific=1.0, generic=0.35, untagged=0.65 (backward compat)
    spec_counts = {"specific": 0, "generic": 0, "untagged": 0}
    if risk_items:
        weighted_sum = 0.0
        for e in risk_items:
            rel = float(e.get("reliability", 0.0))
            spec = e.get("specificity")
            if spec == "specific":
                spec_weight = 1.00
                spec_counts["specific"] += 1
            elif spec == "generic":
                spec_weight = 0.35
                spec_counts["generic"] += 1
            else:
                spec_weight = 0.65
                spec_counts["untagged"] += 1
            weighted_sum += rel * spec_weight
        rbs = min(100.0, weighted_sum * 20)
    else:
        rbs = 0.0

    return {
        "directional_thesis_score":         round(dts, 1),
        "risk_burden_score":                round(rbs, 1),
        "directional_items_count":          sum(
            1 for e in thesis_items
            if str(e.get("direction") or "").lower() in ("bullish", "bearish")
        ),
        "risk_items_count":                 len(risk_items),
        "risk_items":                       risk_items,
        "mgmt_direction_adjustment_applied":    has_mgmt,
        "external_asymmetry_adjustment_applied": has_external,
        "risk_specificity_breakdown":           spec_counts,
    }
