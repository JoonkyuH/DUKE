"""
score_types.py
Output types for Layer 4 scoring.

This file is the type contract between Layer 4 (scoring) and Layer 5 (debate).
Every field that Layer 5 touches is defined here.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List


class ConvictionLevel(str, Enum):
    HIGH         = "high"
    MEDIUM       = "medium"
    LOW          = "low"
    INSUFFICIENT = "insufficient"


class Recommendation(str, Enum):
    STRONG_BUY   = "strong_buy"
    BUY          = "buy"
    WATCH        = "watch"
    AVOID        = "avoid"
    STRONG_AVOID = "strong_avoid"
    INVALIDATED  = "invalidated"


class PositionSizing(str, Enum):
    FULL    = "full"      # 100% of target position size
    HALF    = "half"      # 50%
    QUARTER = "quarter"   # 25%
    PILOT   = "pilot"     # 10% — toe in the water
    NONE    = "none"


class InvalidationStatus(str, Enum):
    CLEAR      = "clear"       # No conditions triggered or monitoring
    MONITORING = "monitoring"  # One or more conditions approaching trigger
    MAJOR      = "major"       # One or more MAJOR conditions triggered — reassess in 24h
    FATAL      = "fatal"       # FATAL condition triggered — thesis abandoned


@dataclass
class EvidenceScoreBreakdown:
    bull_weight:            float   # Sum of reliability for BULLISH items
    bear_weight:            float   # Sum of reliability for BEARISH items
    neutral_weight:         float   # Sum of reliability for NEUTRAL items
    binary_weight:          float   # Sum of reliability for BINARY items
    total_weight:           float   # Sum of all reliability scores
    net_score:              float   # (bull - bear) / (bull + bear) * 100, range [-100, 100]
    directional_count:      int     # Count of BULLISH + BEARISH items only
    high_reliability_count: int     # Items with reliability >= 0.70


@dataclass
class ConfidencePenaltyBreakdown:
    base_confidence:          float
    contradiction_penalty:    float   # From unresolved contradictions
    binary_catalyst_penalty:  float   # From HIGH-impact BINARY catalysts
    stale_data_penalty:       float   # From stale_fields in data_freshness
    thin_evidence_penalty:    float   # If directional items < minimum threshold
    total_penalty:            float
    bonuses:                  float
    final_confidence:         float


@dataclass
class InvalidationReport:
    status:                InvalidationStatus
    triggered_conditions:  List[str]   # condition_ids with current_status == "triggered"
    monitoring_conditions: List[str]   # condition_ids with current_status == "monitoring"
    fatal_triggered:       bool
    major_triggered:       bool
    notes:                 str


@dataclass
class ScoringOutput:
    score_id:          str
    packet_reference:  str     # Links to EvidencePacket.packet_id
    ticker:            str
    company_name:      str
    scored_at:         str     # ISO8601 UTC

    # Core outputs
    evidence_score:    float              # Net evidence balance [-100, 100]
    confidence_score:  float              # Overall confidence [0, 100]
    conviction:        ConvictionLevel
    recommendation:    Recommendation
    position_sizing:   PositionSizing

    # Breakdowns for human review and Layer 5 debate
    evidence_breakdown:   EvidenceScoreBreakdown
    confidence_breakdown: ConfidencePenaltyBreakdown
    invalidation_report:  InvalidationReport

    # Top risks surfaced for human review
    primary_risks:         List[str]

    # Pass-through context for downstream layers
    screening_score:       float
    screening_reason_codes: List[str]

    # Plain-English explanation of what drove each score (displayed to investor)
    evidence_score_note:   str = ""
    confidence_score_note: str = ""

    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
