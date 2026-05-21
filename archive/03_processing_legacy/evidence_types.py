"""
evidence_types.py
Core types, enums, and dataclasses for the Layer 2 evidence packet.

This file is the type contract between Layer 2 (research) and Layer 3 (scoring).
Every field that Layer 3 touches is defined here.

Evidence hierarchy (reliability defaults):
  SEC filings / EDGAR    0.95  — primary source, objective
  Earnings call          0.85  — management statements, can be spun
  Management / IR        0.80  — direct but self-interested
  Tier-1 financial press 0.75  — Reuters, WSJ, FT, Bloomberg
  Macro / fed data       0.70  — objective but lagged
  Technical analysis     0.70  — objective price data, interpretation varies
  Analyst reports        0.65  — informed but conflicted
  Tier-2 press           0.50  — industry publications, trade press
  Perplexity synthesis   0.55  — structured research, secondary source
  Grok / sentiment       0.40  — narrative signal, low precision
  Social / blogs         0.20  — noise floor
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ─────────────────────────────────────────────
# SOURCE TYPES AND RELIABILITY
# ─────────────────────────────────────────────

class SourceType(str, Enum):
    SEC_FILING      = "sec_filing"       # 10-K, 10-Q, 8-K, DEF 14A
    EARNINGS_CALL   = "earnings_call"    # Transcript (prepared remarks or Q&A)
    MANAGEMENT      = "management"       # CEO/CFO direct quotes, IR statements
    NEWS_TIER1      = "news_tier1"       # Reuters, WSJ, FT, Bloomberg
    MACRO           = "macro"            # Fed, BLS, economic data
    TECHNICAL       = "technical"        # Price/volume/chart analysis
    ANALYST_REPORT  = "analyst_report"   # Sell-side research
    NEWS_TIER2      = "news_tier2"       # Trade press, industry publications
    PERPLEXITY      = "perplexity"       # Perplexity research synthesis
    GROK            = "grok"             # Grok narrative/sentiment analysis
    NEWS_SOCIAL     = "news_social"      # Twitter/X, Reddit, blogs


SOURCE_RELIABILITY_DEFAULTS: dict = {
    SourceType.SEC_FILING:    0.95,
    SourceType.EARNINGS_CALL: 0.85,
    SourceType.MANAGEMENT:    0.80,
    SourceType.NEWS_TIER1:    0.75,
    SourceType.MACRO:         0.70,
    SourceType.TECHNICAL:     0.70,
    SourceType.ANALYST_REPORT:0.65,
    SourceType.NEWS_TIER2:    0.50,
    SourceType.PERPLEXITY:    0.55,
    SourceType.GROK:          0.40,
    SourceType.NEWS_SOCIAL:   0.20,
}


# ─────────────────────────────────────────────
# EVIDENCE CLASSIFICATION
# ─────────────────────────────────────────────

class EvidenceDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BINARY  = "binary"    # Material but outcome uncertain — binary event


class EvidenceCategory(str, Enum):
    REVENUE       = "revenue"
    EARNINGS      = "earnings"
    MARGINS       = "margins"
    BALANCE_SHEET = "balance_sheet"
    GUIDANCE      = "guidance"
    COMPETITIVE   = "competitive"
    MANAGEMENT    = "management"
    MACRO         = "macro"
    TECHNICAL     = "technical"
    NEWS          = "news"
    REGULATORY    = "regulatory"
    CATALYST      = "catalyst"


# ─────────────────────────────────────────────
# CATALYST TYPES
# ─────────────────────────────────────────────

class CatalystType(str, Enum):
    EARNINGS          = "earnings"
    PRODUCT_LAUNCH    = "product_launch"
    REGULATORY        = "regulatory"
    MACRO             = "macro"
    MANAGEMENT_CHANGE = "management_change"
    ANALYST_ACTION    = "analyst_action"
    SECTOR_ROTATION   = "sector_rotation"
    MERGER_ACQUISITION= "merger_acquisition"
    GUIDANCE_UPDATE   = "guidance_update"


class CatalystImpact(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


# ─────────────────────────────────────────────
# CONTRADICTION CLASSIFICATION
# ─────────────────────────────────────────────

class ContradictionSeverity(str, Enum):
    HIGH   = "high"    # Both high-reliability sources conflict on same category
    MEDIUM = "medium"  # One high-reliability, one medium
    LOW    = "low"     # Both lower-reliability sources conflict


class ContradictionResolution(str, Enum):
    UNRESOLVED     = "unresolved"
    EXPLAINED      = "explained"        # Context resolves the apparent conflict
    CONFIRMED_RISK = "confirmed_risk"   # Bear evidence is correct — risk is real
    DISMISSED      = "dismissed"        # Bear evidence is outweighed or stale


# ─────────────────────────────────────────────
# THESIS INVALIDATION
# ─────────────────────────────────────────────

class ThesisInvalidationSeverity(str, Enum):
    FATAL = "fatal"   # Triggers immediate thesis invalidation
    MAJOR = "major"   # Triggers urgent reassessment within 24 hours
    MINOR = "minor"   # Monitor — does not invalidate but signals stress


class TICStatus(str, Enum):
    NOT_TRIGGERED = "not_triggered"
    MONITORING    = "monitoring"        # Condition is approaching trigger
    TRIGGERED     = "triggered"         # Condition has been met


# ─────────────────────────────────────────────
# QUALITATIVE CLASSIFICATIONS
# ─────────────────────────────────────────────

class TrendDirection(str, Enum):
    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"
    STABLE       = "stable"
    REVERSING    = "reversing"


class MoatStrength(str, Enum):
    WIDE      = "wide"
    NARROW    = "narrow"
    NONE      = "none"
    CONTESTED = "contested"    # Under active competitive pressure


class CompetitivePosition(str, Enum):
    GAINING = "gaining"
    HOLDING = "holding"
    LOSING  = "losing"


class ManagementSignal(str, Enum):
    STRONG  = "strong"
    NEUTRAL = "neutral"
    WEAK    = "weak"
    FLAGS   = "flags"    # Active concerns: unusual selling, restated guidance, etc.


class TrendStructure(str, Enum):
    UPTREND       = "uptrend"
    DOWNTREND     = "downtrend"
    CONSOLIDATION = "consolidation"
    BREAKOUT      = "breakout"
    BREAKDOWN     = "breakdown"


class RSLineTrend(str, Enum):
    NEW_HIGH  = "new_high"
    RISING    = "rising"
    FLAT      = "flat"
    DECLINING = "declining"


class ManagementTone(str, Enum):
    CONFIDENT     = "confident"
    CAUTIOUS      = "cautious"
    MIXED         = "mixed"
    DETERIORATING = "deteriorating"


# ─────────────────────────────────────────────
# CORE EVIDENCE DATACLASSES
# ─────────────────────────────────────────────

@dataclass
class EvidenceItem:
    """
    A single piece of evidence. The atomic unit of the research layer.

    Every claim in the evidence packet must be traceable to an EvidenceItem
    with a source, reliability, and direction. No unsourced assertions.
    """
    evidence_id:        str
    content:            str                 # What this evidence says (1–3 sentences)
    source:             str                 # Human-readable source name
    source_type:        SourceType
    reliability:        float               # 0–1, from SOURCE_RELIABILITY_DEFAULTS or overridden
    direction:          EvidenceDirection
    category:           EvidenceCategory
    date:               str                 # ISO date of the source
    source_url:         Optional[str] = None
    quote:              Optional[str] = None  # Exact quote if from primary source (≤50 words)
    contradiction_flag: bool = False          # Set by contradiction_detector
    contradiction_with: List[str] = field(default_factory=list)  # evidence_ids


@dataclass
class Catalyst:
    """
    An identified upcoming or recent event with potential price impact.
    """
    catalyst_id:        str
    type:               CatalystType
    description:        str
    date:               Optional[str]          # ISO date if known
    days_away:          Optional[int]           # Negative = past event
    expected_impact:    CatalystImpact
    direction:          EvidenceDirection
    historical_pattern: Optional[str] = None   # How similar catalysts have played
    probability:        Optional[float] = None  # 0–1 if assessable


@dataclass
class Contradiction:
    """
    A detected conflict between two evidence items in the same category.
    """
    contradiction_id:    str
    bullish_evidence_id: str
    bearish_evidence_id: str
    description:         str
    severity:            ContradictionSeverity
    resolution:          ContradictionResolution = ContradictionResolution.UNRESOLVED
    resolution_notes:    Optional[str] = None


@dataclass
class ThesisInvalidationCondition:
    """
    A condition that, if triggered, requires the thesis to be reassessed or abandoned.
    These are set during research and monitored continuously after entry.
    """
    condition_id:       str
    description:        str               # What the condition is
    monitoring_trigger: str               # Exact observable event that triggers it
    severity:           ThesisInvalidationSeverity
    current_status:     TICStatus = TICStatus.NOT_TRIGGERED


@dataclass
class RiskFactor:
    """
    A specific risk to the investment thesis — company, sector, macro, or regulatory.
    """
    risk_id:     str
    category:    str               # company | sector | macro | regulatory | execution
    description: str
    probability: str               # high | medium | low
    impact:      str               # high | medium | low
    mitigants:   Optional[str] = None


# ─────────────────────────────────────────────
# STRUCTURED FUNDAMENTAL DATA
# ─────────────────────────────────────────────

@dataclass
class Fundamentals:
    """Structured financial data extracted from SEC filings and earnings calls."""

    # Revenue
    revenue_ttm_m:            Optional[float] = None   # TTM revenue in $M
    revenue_growth_yoy_pct:   Optional[float] = None
    revenue_growth_qoq_pct:   Optional[float] = None
    revenue_trend:            Optional[TrendDirection] = None

    # Earnings
    eps_ttm:                  Optional[float] = None
    eps_growth_yoy_pct:       Optional[float] = None
    eps_surprise_last_pct:    Optional[float] = None   # Most recent quarter
    eps_surprise_avg_4q_pct:  Optional[float] = None   # 4-quarter average

    # Margins
    gross_margin_pct:         Optional[float] = None
    gross_margin_trend:       Optional[TrendDirection] = None
    operating_margin_pct:     Optional[float] = None
    operating_margin_trend:   Optional[TrendDirection] = None

    # Balance sheet
    cash_m:                   Optional[float] = None
    total_debt_m:             Optional[float] = None
    net_cash_m:               Optional[float] = None   # cash - debt
    fcf_ttm_m:                Optional[float] = None   # TTM free cash flow
    fcf_yield_pct:            Optional[float] = None   # FCF / market cap

    # Guidance
    next_q_revenue_guide_m:   Optional[float] = None
    guidance_vs_consensus_pct:Optional[float] = None   # +ve = above consensus
    management_tone:          Optional[ManagementTone] = None


@dataclass
class BusinessQuality:
    """Qualitative assessment of business durability and competitive position."""
    moat_assessment:             Optional[MoatStrength] = None
    moat_sources:                List[str] = field(default_factory=list)
    # Valid moat sources: network_effects, switching_costs, cost_advantage,
    # intangible_assets, efficient_scale
    competitive_position:        Optional[CompetitivePosition] = None
    customer_concentration_risk: Optional[str] = None   # low | medium | high
    management_signals:          Optional[ManagementSignal] = None
    insider_activity:            Optional[str] = None   # buying | selling | neutral


@dataclass
class TechnicalState:
    """Price structure and technical context beyond the screening signals."""
    trend_structure:       Optional[TrendStructure] = None
    key_support_levels:    List[float] = field(default_factory=list)
    key_resistance_levels: List[float] = field(default_factory=list)
    pattern:               Optional[str] = None        # e.g. "base breakout", "cup and handle"
    rs_line_trend:         Optional[RSLineTrend] = None
    weeks_in_base:         Optional[int] = None        # For base patterns
    prior_uptrend_weeks:   Optional[int] = None        # Quality of prior trend


# ─────────────────────────────────────────────
# PACKET ASSEMBLY
# ─────────────────────────────────────────────

@dataclass
class EvidenceSummary:
    """Narrative synthesis generated by the AI researcher."""
    bull_case:      str           # 2–4 sentence synthesis of bullish evidence
    bear_case:      str           # 2–4 sentence synthesis of bearish evidence
    key_questions:  List[str]     # Unresolved questions for the analyst roles
    evidence_count: dict          # {"bullish": N, "bearish": N, "neutral": N, "binary": N}


@dataclass
class DataFreshness:
    """Timestamps indicating how current each data source is."""
    price_data_as_of:      Optional[str] = None
    last_filing_date:      Optional[str] = None
    last_earnings_date:    Optional[str] = None
    news_coverage_through: Optional[str] = None
    stale_fields:          List[str] = field(default_factory=list)


@dataclass
class EvidencePacket:
    """
    The complete research output for a single ticker.
    This is the document Layer 3 operates on.
    Every field used by Layer 3 scoring must be populated here.
    """
    # Identity
    packet_id:             str
    ticker:                str
    company_name:          str
    sector:                str
    generated_at:          str        # ISO8601 UTC
    screening_reference:   str        # Links back to the Layer 1 output
    screening_score:       float
    screening_reason_codes:List[str]
    screening_flags:       List[str]

    # Structured research
    fundamentals:          Fundamentals
    business_quality:      BusinessQuality
    technical_state:       TechnicalState

    # Catalysts and evidence
    catalyst_map:                   List[Catalyst]
    evidence_items:                 List[EvidenceItem]
    contradictions:                 List[Contradiction]
    thesis_invalidation_conditions: List[ThesisInvalidationCondition]
    risk_factors:                   List[RiskFactor]

    # Synthesis
    summary:               EvidenceSummary
    data_freshness:        DataFreshness

    # Operational
    metadata:              dict = field(default_factory=dict)
