"""
contention_detector.py
Auto-detects contentions between bull and bear analyst positions.

A contention exists when:
  - Bull cites an evidence item AND bear contests that same item, OR
  - Bear cites an evidence item AND bull contests that same item

Items are grouped by their evidence category so the Chief Analyst in Layer 6
can adjudicate one topic at a time rather than item by item.

Severity:
  CRITICAL: Any contested item has reliability >= 0.80 (two credible views clash)
  MATERIAL: Any contested item has reliability >= 0.60
  MINOR:    Lower-reliability items only
"""

from typing import Dict, List
from debate_types import Contention, ContentionSeverity


def detect_contentions(
    evidence_items: List[dict],
    bull_pos:       dict,
    bear_pos:       dict,
) -> List[Contention]:
    """
    Detect contentions from overlapping bull citations and bear contestations,
    and vice versa.

    Args:
        evidence_items: Full evidence item list from the EvidencePacket
        bull_pos:       Bull analyst position dict (with evidence_cited, contested_items)
        bear_pos:       Bear analyst position dict

    Returns:
        List of Contention objects sorted CRITICAL first, then MATERIAL, then MINOR.
    """
    ev_map: Dict[str, dict] = {
        e["evidence_id"]: e
        for e in evidence_items
        if "evidence_id" in e
    }

    bull_cited     = set(bull_pos.get("evidence_cited", []))
    bull_contested = set(bull_pos.get("contested_items", []))
    bear_cited     = set(bear_pos.get("evidence_cited", []))
    bear_contested = set(bear_pos.get("contested_items", []))

    # Bear challenges bull's supporting evidence
    bear_challenges_bull = bull_cited & bear_contested
    # Bull challenges bear's supporting evidence
    bull_challenges_bear = bear_cited & bull_contested

    all_contested = bear_challenges_bull | bull_challenges_bear

    # Group contested items by evidence category
    by_category: Dict[str, List[str]] = {}
    for eid in all_contested:
        cat = ev_map.get(eid, {}).get("category", "unknown")
        by_category.setdefault(cat, []).append(eid)

    contentions: List[Contention] = []
    counter = 1

    for category, eids in by_category.items():
        items    = [ev_map[eid] for eid in eids if eid in ev_map]
        severity = _compute_severity(items)

        bull_side = [e for e in eids if e in bear_challenges_bull]
        bear_side = [e for e in eids if e in bull_challenges_bear]

        bull_claim = (
            f"Bull cites {bull_side} as supportive of the bullish thesis; bear disputes these."
            if bull_side
            else "Bull does not directly cite evidence in this category."
        )
        bear_claim = (
            f"Bear cites {bear_side} as damaging to the thesis; bull disputes these."
            if bear_side
            else "Bear does not directly cite evidence in this category."
        )

        contentions.append(Contention(
            contention_id=f"CON-D-{counter:03d}",
            category=category,
            bull_claim=bull_claim,
            bear_claim=bear_claim,
            evidence_ids=eids,
            severity=severity,
        ))
        counter += 1

    _order = {
        ContentionSeverity.CRITICAL: 0,
        ContentionSeverity.MATERIAL: 1,
        ContentionSeverity.MINOR:    2,
    }
    contentions.sort(key=lambda c: _order[c.severity])
    return contentions


def _compute_severity(items: List[dict]) -> ContentionSeverity:
    if not items:
        return ContentionSeverity.MINOR
    max_rel = max(item.get("reliability", 0.0) for item in items)
    if max_rel >= 0.80:
        return ContentionSeverity.CRITICAL
    if max_rel >= 0.60:
        return ContentionSeverity.MATERIAL
    return ContentionSeverity.MINOR
