"""
debate_types.py
Output types for Layer 5 debate.

This file is the type contract between Layer 5 (debate) and Layer 6 (synthesis).
Every field that Layer 6 touches is defined here.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, List, Optional


class AnalystRole(str, Enum):
    BULL = "bull"
    BEAR = "bear"


class DebateOutcome(str, Enum):
    BULL_PREVAILS = "bull_prevails"    # Net score moved materially upward after debate
    BEAR_PREVAILS = "bear_prevails"    # Net score moved materially downward after debate
    BALANCED      = "balanced"          # Debate reinforced existing view without major shift
    INCONCLUSIVE  = "inconclusive"      # Bull and bear strongly disagree; gap unresolved


class ContentionSeverity(str, Enum):
    CRITICAL = "critical"   # Affects thesis viability; Chief Analyst must adjudicate in Layer 6
    MATERIAL = "material"   # Meaningful to the recommendation
    MINOR    = "minor"      # Secondary consideration


@dataclass
class AnalystPosition:
    """
    Structured output from a Bull or Bear analyst role.
    Produced by the AI analyst after receiving their brief from position_builder.py.
    """
    analyst_role:          AnalystRole
    summary:               str          # 3–5 sentence case
    key_arguments:         List[str]    # Top 3–5 one-sentence arguments
    evidence_cited:        List[str]    # evidence_ids from the EvidencePacket supporting this case
    contested_items:       List[str]    # evidence_ids from the opposing case being disputed
    raised_risks:          List[str]    # New risks not in the original packet
    score_adjustment:      float        # Recommended adjustment to evidence_score  [-15, +15]
    confidence_adjustment: float        # Recommended adjustment to confidence_score [-10, +10]
    learning_hooks:        List[Any]    = field(default_factory=list)  # Falsifiable predictions; checked at 90/180/365 days


@dataclass
class Contention:
    """
    A specific point of disagreement where bull cites evidence that bear contests,
    or bear cites evidence that bull contests, within the same evidence category.
    """
    contention_id: str
    category:      str                    # EvidenceCategory value (e.g. "revenue", "margins")
    bull_claim:    str                    # Summary of bull's position on this category
    bear_claim:    str                    # Summary of bear's position on this category
    evidence_ids:  List[str]              # Evidence items at the heart of the dispute
    severity:      ContentionSeverity
    adjudication:  Optional[str] = None  # Set by Chief Analyst in Layer 6


@dataclass
class DebateRecord:
    """
    Complete record of the bull vs bear debate for a single ticker.
    This is the document Layer 6 synthesis operates on.
    """
    debate_id:       str
    score_reference: str    # ScoringOutput.score_id
    packet_reference: str   # EvidencePacket.packet_id
    ticker:          str
    company_name:    str
    debated_at:      str    # ISO8601 UTC

    # Analyst positions
    bull_position: AnalystPosition
    bear_position: AnalystPosition

    # Contentions auto-detected from overlapping evidence citations
    contentions: List[Contention]

    # Layer 4 baseline scores (unchanged — for traceability)
    base_evidence_score:   float
    base_confidence_score: float

    # Debate-adjusted scores passed to Layer 6
    debate_evidence_score:   float
    debate_confidence_score: float
    net_score_adjustment:    float

    # Outcome classification
    outcome: DebateOutcome

    # Layer 4 outputs passed through for traceability
    original_conviction:     str
    original_recommendation: str

    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
