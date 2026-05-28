"""
position_builder.py
Builds structured briefing documents for Bull and Bear analyst roles.

Each brief gives the AI analyst agent:
  - A filtered view of evidence organized for their case
  - The Layer 4 scoring baseline they must engage with
  - The opposing evidence they are required to address
  - An explicit output format for their structured position

These briefings are consumed by Claude Finance Agent in the Bull and Bear roles.
The Python layer produces structured dicts that callers can serialize to JSON
or render as a system prompt for an agent API call.

Entry points:
  build_bull_brief(packet, scoring) → dict
  build_bear_brief(packet, scoring) → dict
"""

from typing import List


# Only surface opposing evidence above this reliability for the "must address" list.
# Below this threshold it is noise; above it, ignoring it would be a red flag.
HIGH_QUALITY_THRESHOLD = 0.70

# How many top opposing items to surface — keeps the brief focused
MAX_OPPOSING_ITEMS = 5


def build_bull_brief(packet: dict, scoring: dict) -> dict:
    """
    Build the briefing document for the Bull Analyst.

    The Bull Analyst receives their supporting evidence first, then is required
    to directly address the highest-reliability bearish evidence. They must
    not ignore the bear case — the brief explicitly surfaces it.
    """
    evidence_items = packet.get("evidence_items", [])
    bull_items     = [e for e in evidence_items if e.get("direction", "").lower() == "bullish"]
    bear_items     = [e for e in evidence_items if e.get("direction", "").lower() == "bearish"]

    # Highest-reliability bearish items the bull must address
    must_address = sorted(
        [e for e in bear_items if e.get("reliability", 0) >= HIGH_QUALITY_THRESHOLD],
        key=lambda e: e.get("reliability", 0),
        reverse=True,
    )[:MAX_OPPOSING_ITEMS]

    return {
        "role": "bull_analyst",
        "mandate": (
            "Construct the strongest possible bullish investment case for this ticker. "
            "Cite evidence by evidence_id. You MUST directly address every item in "
            "'must_address_evidence' — explain why each is less damaging than it appears "
            "or why it is outweighed by bullish evidence. Do not ignore them. "
            "score_adjustment must be in [-15, +15]; confidence_adjustment in [-10, +10]."
        ),

        "ticker":       packet.get("ticker"),
        "company_name": packet.get("company_name"),
        "sector":       packet.get("sector"),

        "scoring_baseline": {
            "evidence_score":            scoring.get("evidence_score"),
            "directional_thesis_score":  scoring.get("directional_thesis_score"),
            "risk_burden_score":         scoring.get("risk_burden_score"),
            "confidence_score":          scoring.get("confidence_score"),
            "conviction":                scoring.get("conviction"),
            "recommendation":            scoring.get("recommendation"),
            "position_sizing":           scoring.get("position_sizing"),
        },

        "supporting_evidence":   _format_evidence(bull_items),
        "must_address_evidence": _format_evidence(must_address),
        "binary_events":         _filter_by_direction(packet.get("catalyst_map", []), "binary"),

        "thesis_invalidation_conditions": packet.get("thesis_invalidation_conditions", []),
        "key_questions_from_research":    packet.get("summary", {}).get("key_questions", []),

        "screening_context": {
            "screening_score":       scoring.get("screening_score"),
            "screening_reason_codes": scoring.get("screening_reason_codes", []),
        },

        "output_format": {
            "analyst_role":          "bull",
            "summary":               "<3-5 sentence bullish case>",
            "key_arguments":         ["<argument 1>", "<argument 2>", "<argument 3>"],
            "evidence_cited":        ["<evidence_id>", "..."],
            "contested_items":       ["<bear evidence_id you dispute>", "..."],
            "raised_strengths":      [
                {
                    "strength":  "<specific positive factor not already weighted in supporting_evidence>",
                    "grounding": "<EV-ID, disclosed-fact reference, or 'Inference from: ...'>",
                },
            ],
            "raised_risks":          [],
            "score_adjustment":      "<float in [-15, +15] — see Score Adjustment Rubric>",
            "confidence_adjustment": "<float in [-10, +10]>",
        },
    }


def build_bear_brief(packet: dict, scoring: dict) -> dict:
    """
    Build the briefing document for the Bear Analyst.

    The Bear Analyst receives their supporting bearish evidence first, then is
    required to address the highest-reliability bullish evidence — explaining
    why it is weaker than it appears. They may raise new risks not in the
    original packet under 'raised_risks'.
    """
    evidence_items = packet.get("evidence_items", [])
    bull_items     = [e for e in evidence_items if e.get("direction", "").lower() == "bullish"]
    bear_items     = [e for e in evidence_items if e.get("direction", "").lower() == "bearish"]

    # Highest-reliability bullish items the bear must challenge
    must_address = sorted(
        [e for e in bull_items if e.get("reliability", 0) >= HIGH_QUALITY_THRESHOLD],
        key=lambda e: e.get("reliability", 0),
        reverse=True,
    )[:MAX_OPPOSING_ITEMS]

    # Unresolved HIGH-severity contradictions are prime material for the bear case
    contradictions     = packet.get("contradictions", [])
    unresolved_high    = [
        c for c in contradictions
        if c.get("severity") == "high" and c.get("resolution", "unresolved") == "unresolved"
    ]

    return {
        "role": "bear_analyst",
        "mandate": (
            "Construct the strongest possible bearish case against this ticker. "
            "Cite evidence by evidence_id. You MUST directly address every item in "
            "'must_address_evidence' — explain why each bullish piece is weaker than "
            "it appears, overstated, or offset by risks. "
            "You may raise risks not in the original packet under 'raised_risks'. "
            "score_adjustment must be in [-15, +15]; confidence_adjustment in [-10, +10]."
        ),

        "ticker":       packet.get("ticker"),
        "company_name": packet.get("company_name"),
        "sector":       packet.get("sector"),

        "scoring_baseline": {
            "evidence_score":            scoring.get("evidence_score"),
            "directional_thesis_score":  scoring.get("directional_thesis_score"),
            "risk_burden_score":         scoring.get("risk_burden_score"),
            "confidence_score":          scoring.get("confidence_score"),
            "conviction":                scoring.get("conviction"),
            "recommendation":            scoring.get("recommendation"),
        },

        "supporting_evidence":              _format_evidence(bear_items),
        "must_address_evidence":            _format_evidence(must_address),
        "unresolved_high_contradictions":   unresolved_high,
        "risk_factors":                     packet.get("risk_factors", []),
        "thesis_invalidation_conditions":   packet.get("thesis_invalidation_conditions", []),
        "binary_events":                    _filter_by_direction(packet.get("catalyst_map", []), "binary"),
        "key_questions_from_research":      packet.get("summary", {}).get("key_questions", []),

        "screening_context": {
            "screening_flags": packet.get("screening_flags", []),
        },

        "output_format": {
            "analyst_role":          "bear",
            "summary":               "<3-5 sentence bearish case>",
            "key_arguments":         ["<argument 1>", "<argument 2>", "<argument 3>"],
            "evidence_cited":        ["<bear evidence_id>", "..."],
            "contested_items":       ["<bull evidence_id you dispute>", "..."],
            "raised_risks":          [
                {
                    "risk":      "<specific new risk not in original packet>",
                    "grounding": "<EV-ID, disclosed-fact reference, or 'Inference from: ...'>",
                },
            ],
            "score_adjustment":      "<float in [-15, +15] — see Score Adjustment Rubric>",
            "confidence_adjustment": "<float in [-10, +10]>",
        },
    }


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _format_evidence(items: List[dict]) -> List[dict]:
    """Return a clean, brief-safe subset of evidence item fields."""
    return [
        {
            "evidence_id":          item.get("evidence_id", ""),
            "content":              item.get("quote_text", ""),
            "source":               item.get("source_url", ""),
            "reliability":          item.get("reliability"),
            "category":             item.get("category", ""),
            "date":                 item.get("filing_date", ""),
            "quote":                item.get("quote_text", ""),
            "speaker":              item.get("speaker", ""),
            "filing_section_label": item.get("filing_section_label", ""),
        }
        for item in items
    ]


def _filter_by_direction(catalysts: List[dict], direction: str) -> List[dict]:
    return [c for c in catalysts if c.get("direction") == direction]
