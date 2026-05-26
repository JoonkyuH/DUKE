"""
synthesis_types.py
Type contract for Layer 6 synthesis.

This file defines two layers of types:
  ChiefAnalystOutput — the structured JSON response from the Chief Analyst role
  SynthesisOutput    — the assembled brief synthesizer.py returns (input to the agent)

Every field that formatter.py and decision_capture.py touch is defined here.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional


class ChiefRecommendation(str, Enum):
    STRONG_CONVICTION_ENTER   = "strong_conviction_enter"
    MODERATE_CONVICTION_ENTER = "moderate_conviction_enter"
    WATCH    = "watch"
    PASS     = "pass"
    BLOCKED  = "blocked"


class PhilosophyFit(str, Enum):
    STRONG       = "strong"
    ADEQUATE     = "adequate"
    WEAK         = "weak"
    DOES_NOT_FIT = "does_not_fit"


class InvestmentArchetype(str, Enum):
    LONG_TERM_COMPOUNDER = "long_term_compounder"
    QUALITY_COMPOUNDER   = "quality_compounder"
    DEEP_VALUE           = "deep_value"
    DOES_NOT_FIT         = "does_not_fit"


@dataclass
class ContentionAdjudication:
    contention_id: str
    adjudication:  str   # "bull_correct" | "bear_correct" | "unresolvable"
    reasoning:     str


@dataclass
class MonitoringPriority:
    priority:    int
    description: str
    source:      str   # TIC-id, "learning_hook", "risk_factor", "risk_officer"
    frequency:   str   # "weekly" | "monthly" | "quarterly"


@dataclass
class ChiefAnalystOutput:
    """
    Structured response from the Chief Analyst role.
    Parsed directly from the JSON the chief_analyst prompt returns.
    """
    analyst_role:                       str    # "chief_analyst"
    recommendation:                     str    # ChiefRecommendation value
    investment_archetype_confirmed:     str
    final_evidence_score:               float
    final_confidence_score:             float
    executive_summary:                  str
    bull_case_assessment:               str
    bear_case_assessment:               str
    critical_contention_adjudications:  List[ContentionAdjudication]
    philosophy_fit:                     str
    philosophy_fit_notes:               str
    risk_officer_flags:                 List[str]
    monitoring_priorities:              List[MonitoringPriority]
    what_would_change_this:             str
    blocking_issues:                    List[str]
    metadata:                           dict = field(default_factory=dict)


@dataclass
class SynthesisOutput:
    """
    Assembled Chief Analyst brief plus synthesis metadata.
    Returned by synthesizer.synthesize() — this is what the Chief Analyst agent receives.
    """
    synthesis_id:    str
    debate_reference: str   # DebateRecord.debate_id
    ticker:          str
    company_name:    str
    synthesized_at:  str    # ISO8601 UTC

    # Assembled brief to feed to the Chief Analyst agent
    chief_analyst_brief: dict

    # Debate scores passed through for display context
    debate_evidence_score:   float
    debate_confidence_score: float
    debate_outcome:          str

    # Risk gate from Risk Officer
    overall_risk_assessment: str
    ready_for_chief_analyst: bool
    blocking_issues:         List[str]

    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
