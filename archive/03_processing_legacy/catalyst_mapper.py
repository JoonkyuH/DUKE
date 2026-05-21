"""
catalyst_mapper.py
Structures, scores, and prioritizes catalysts identified during deep research.

A catalyst is any near-term event with meaningful potential price impact.
The catalyst map is one of the most important outputs of Layer 2 because
it directly informs the thesis invalidation conditions in Layer 3.

Catalyst types:
  earnings, product_launch, regulatory, macro, management_change,
  analyst_action, sector_rotation, merger_acquisition, guidance_update

Priority ordering:
  1. Imminent (≤7 days) regardless of type — binary event risk
  2. High-impact catalysts by days_away
  3. Binary direction catalysts elevated over directional ones
  4. Medium-impact catalysts by days_away
  5. Low-impact catalysts
"""

from datetime import datetime, timezone
from typing import List, Optional

from evidence_types import (
    Catalyst,
    CatalystType,
    CatalystImpact,
    EvidenceDirection,
)


# Base impact by catalyst type
# These are starting points — proximity can elevate any type to HIGH
_BASE_IMPACT: dict = {
    CatalystType.EARNINGS:           CatalystImpact.HIGH,
    CatalystType.GUIDANCE_UPDATE:    CatalystImpact.HIGH,
    CatalystType.REGULATORY:         CatalystImpact.HIGH,
    CatalystType.MERGER_ACQUISITION: CatalystImpact.HIGH,
    CatalystType.PRODUCT_LAUNCH:     CatalystImpact.MEDIUM,
    CatalystType.MANAGEMENT_CHANGE:  CatalystImpact.MEDIUM,
    CatalystType.MACRO:              CatalystImpact.MEDIUM,
    CatalystType.ANALYST_ACTION:     CatalystImpact.LOW,
    CatalystType.SECTOR_ROTATION:    CatalystImpact.LOW,
}

# Imminent threshold: any catalyst this close gets elevated to HIGH
IMMINENT_DAYS = 7


def build_catalyst(
    catalyst_id:        str,
    catalyst_type:      str,
    description:        str,
    direction:          str,
    date_str:           Optional[str] = None,
    as_of_date:         Optional[str] = None,
    historical_pattern: Optional[str] = None,
    probability:        Optional[float] = None,
) -> Catalyst:
    """
    Build a structured Catalyst from raw research inputs.

    Args:
        catalyst_id:        Unique ID (e.g. "CAT-001")
        catalyst_type:      String matching CatalystType enum value
        description:        What the catalyst is (1–2 sentences)
        direction:          "bullish" | "bearish" | "binary" | "neutral"
        date_str:           ISO date of catalyst (if known)
        as_of_date:         Current date for computing days_away (ISO date)
        historical_pattern: How similar catalysts have played historically
        probability:        0–1 probability if assessable (optional)
    """
    # Parse catalyst type
    try:
        c_type = CatalystType(catalyst_type)
    except ValueError:
        c_type = CatalystType.MACRO   # Safe fallback

    # Parse direction
    try:
        c_direction = EvidenceDirection(direction)
    except ValueError:
        c_direction = EvidenceDirection.BINARY

    # Compute days_away
    days_away = _compute_days_away(date_str, as_of_date)

    # Determine impact (proximity can elevate)
    impact = _BASE_IMPACT.get(c_type, CatalystImpact.MEDIUM)
    if days_away is not None and 0 <= days_away <= IMMINENT_DAYS:
        impact = CatalystImpact.HIGH   # Imminent = always high impact

    return Catalyst(
        catalyst_id=catalyst_id,
        type=c_type,
        description=description,
        date=date_str,
        days_away=days_away,
        expected_impact=impact,
        direction=c_direction,
        historical_pattern=historical_pattern,
        probability=probability,
    )


def sort_catalysts(catalysts: List[Catalyst]) -> List[Catalyst]:
    """
    Sort catalysts by investment priority.

    Priority logic:
      1. Imminent (0–7 days): always first, regardless of impact rating
      2. Among non-imminent: HIGH impact first, then MEDIUM, then LOW
      3. Within same impact tier: sooner first
      4. Binary direction elevated within each tier (binary = uncertainty risk)
    """
    _impact_rank  = {"high": 0, "medium": 1, "low": 2}
    _dir_rank     = {"binary": 0, "bullish": 1, "bearish": 1, "neutral": 2}

    def _key(c: Catalyst) -> tuple:
        days = c.days_away if c.days_away is not None else 9_999
        days = max(0, days)   # past events treated as 0

        is_imminent    = 1 if days <= IMMINENT_DAYS else 0   # higher = sooner sort
        impact_order   = _impact_rank.get(c.expected_impact.value, 2)
        dir_order      = _dir_rank.get(c.direction.value, 2)

        return (
            -is_imminent,   # imminent first (negated so sort ascending)
            impact_order,
            days,
            dir_order,
        )

    return sorted(catalysts, key=_key)


def get_binary_catalysts(catalysts: List[Catalyst]) -> List[Catalyst]:
    """
    Returns catalysts with BINARY direction that are HIGH impact.
    These are the events Layer 3 uses to add uncertainty penalties.
    """
    return [
        c for c in catalysts
        if c.direction == EvidenceDirection.BINARY
        and c.expected_impact == CatalystImpact.HIGH
    ]


def _compute_days_away(date_str: Optional[str], as_of_date: Optional[str]) -> Optional[int]:
    if not date_str or not as_of_date:
        return None
    try:
        cat  = datetime.fromisoformat(date_str).date()
        ref  = datetime.fromisoformat(as_of_date).date()
        return (cat - ref).days
    except (ValueError, TypeError):
        return None
