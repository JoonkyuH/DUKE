"""
contradiction_detector.py
Detects conflicts between evidence items that cover the same category
but point in opposite directions.

This is one of the most important pieces of the analytical framework.
A system that only gathers bullish evidence produces confirmation bias.
A system that detects and flags genuine contradictions forces the analyst
roles in Layer 3 to resolve them before a recommendation is made.

Detection rules:
  A contradiction exists when ALL of the following are true:
    1. Two evidence items share the same EvidenceCategory
    2. One has direction BULLISH, the other has direction BEARISH
    3. Both have reliability ≥ MIN_RELIABILITY (noise floor = 0.30)

Severity:
  HIGH:   min(reliability_a, reliability_b) ≥ 0.70
          — Two credible sources disagree. Must be resolved before Layer 3.
  MEDIUM: min(reliability_a, reliability_b) ≥ 0.50
          — One credible source, one moderate. Requires explanation.
  LOW:    min(reliability_a, reliability_b) < 0.50
          — Lower-quality sources conflict. Note it but do not block.

The detector mutates evidence_items in place to set:
  - contradiction_flag = True
  - contradiction_with = [list of conflicting evidence_ids]
"""

from typing import List, Tuple
from evidence_types import (
    EvidenceItem,
    Contradiction,
    EvidenceDirection,
    ContradictionSeverity,
    ContradictionResolution,
)


MIN_RELIABILITY = 0.30   # Below this, treat as noise — not a real contradiction


def detect_contradictions(evidence_items: List[EvidenceItem]) -> List[Contradiction]:
    """
    Run O(n²) pairwise comparison across all evidence items.
    n is small in practice (15–40 items per ticker), so this is fast.

    Side effect: mutates evidence_items to set contradiction_flag and
    contradiction_with on items that participate in a contradiction.

    Returns a list of Contradiction objects sorted by severity (HIGH first).
    """
    contradictions: List[Contradiction] = []
    counter = 1

    n = len(evidence_items)
    for i in range(n):
        for j in range(i + 1, n):
            a = evidence_items[i]
            b = evidence_items[j]

            # Rule 1: same category
            if a.category != b.category:
                continue

            # Rule 2: opposing directions
            if not _are_opposing(a.direction, b.direction):
                continue

            # Rule 3: both above noise floor
            if a.reliability < MIN_RELIABILITY or b.reliability < MIN_RELIABILITY:
                continue

            severity = _compute_severity(a.reliability, b.reliability)

            # Orient: bullish first, bearish second
            bull, bear = (a, b) if a.direction == EvidenceDirection.BULLISH else (b, a)

            contradiction = Contradiction(
                contradiction_id=f"CON-{counter:03d}",
                bullish_evidence_id=bull.evidence_id,
                bearish_evidence_id=bear.evidence_id,
                description=_build_description(bull, bear),
                severity=severity,
                resolution=ContradictionResolution.UNRESOLVED,
                resolution_notes=None,
            )
            contradictions.append(contradiction)
            counter += 1

            # Mark participating evidence items
            a.contradiction_flag = True
            b.contradiction_flag = True
            if b.evidence_id not in a.contradiction_with:
                a.contradiction_with.append(b.evidence_id)
            if a.evidence_id not in b.contradiction_with:
                b.contradiction_with.append(a.evidence_id)

    # Sort: HIGH first, then MEDIUM, then LOW
    severity_order = {
        ContradictionSeverity.HIGH:   0,
        ContradictionSeverity.MEDIUM: 1,
        ContradictionSeverity.LOW:    2,
    }
    contradictions.sort(key=lambda c: severity_order[c.severity])

    return contradictions


def _are_opposing(a: EvidenceDirection, b: EvidenceDirection) -> bool:
    return (
        (a == EvidenceDirection.BULLISH and b == EvidenceDirection.BEARISH) or
        (a == EvidenceDirection.BEARISH and b == EvidenceDirection.BULLISH)
    )


def _compute_severity(rel_a: float, rel_b: float) -> ContradictionSeverity:
    min_rel = min(rel_a, rel_b)
    if min_rel >= 0.70:
        return ContradictionSeverity.HIGH
    elif min_rel >= 0.50:
        return ContradictionSeverity.MEDIUM
    else:
        return ContradictionSeverity.LOW


def _build_description(bull: EvidenceItem, bear: EvidenceItem) -> str:
    return (
        f"{bull.category.value.upper()} conflict: "
        f"'{bull.source}' (reliability {bull.reliability:.0%}) is bullish — "
        f"'{bear.source}' (reliability {bear.reliability:.0%}) is bearish. "
        f"Category: {bull.category.value}."
    )


def summarize_contradictions(contradictions: List[Contradiction]) -> dict:
    """Returns a summary dict for the packet metadata."""
    if not contradictions:
        return {
            "total": 0, "high": 0, "medium": 0,
            "low": 0, "unresolved": 0
        }
    return {
        "total":      len(contradictions),
        "high":       sum(1 for c in contradictions
                         if c.severity == ContradictionSeverity.HIGH),
        "medium":     sum(1 for c in contradictions
                         if c.severity == ContradictionSeverity.MEDIUM),
        "low":        sum(1 for c in contradictions
                         if c.severity == ContradictionSeverity.LOW),
        "unresolved": sum(1 for c in contradictions
                         if c.resolution == ContradictionResolution.UNRESOLVED),
    }


def get_unresolved_high_severity(
    contradictions: List[Contradiction]
) -> List[Contradiction]:
    """
    Returns contradictions that are HIGH severity and still UNRESOLVED.
    Layer 3 uses this to apply uncertainty penalties.
    """
    return [
        c for c in contradictions
        if c.severity == ContradictionSeverity.HIGH
        and c.resolution == ContradictionResolution.UNRESOLVED
    ]
