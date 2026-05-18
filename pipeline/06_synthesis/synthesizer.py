"""
synthesizer.py
Entry point for Layer 6 synthesis.

Takes the complete debate record (Layer 5) and the Risk Officer assessment,
assembles the structured brief the Chief Analyst agent receives, and returns
a SynthesisOutput.

The actual Chief Analyst response (prose + adjudications + recommendation)
is produced by the AI analyst role after receiving this brief. Once the
response is returned, formatter.py and decision_capture.py handle rendering
and decision recording.

Entry point: synthesize(debate_record, risk_assessment) -> SynthesisOutput
"""

import uuid
from datetime import datetime, timezone

from synthesis_types import SynthesisOutput


def synthesize(debate_record: dict, risk_assessment: dict) -> SynthesisOutput:
    """
    Assemble the Chief Analyst brief from the debate record and risk assessment.

    Args:
        debate_record:   DebateRecord dict (pipeline/05_debate/schemas/output.json)
        risk_assessment: Risk Officer output dict (from risk_officer prompt)

    Returns:
        SynthesisOutput containing the structured Chief Analyst brief
        and synthesis metadata.
    """
    ticker       = debate_record.get("ticker", "UNKNOWN")
    company_name = debate_record.get("company_name", "")
    debate_id    = debate_record.get("debate_id", "")

    ready        = bool(risk_assessment.get("ready_for_chief_analyst", True))
    overall_risk = risk_assessment.get("overall_risk_assessment", "adequate")
    blocking     = list(risk_assessment.get("blocking_issues", []))

    contentions = debate_record.get("contentions", [])

    return SynthesisOutput(
        synthesis_id=_make_synthesis_id(ticker),
        debate_reference=debate_id,
        ticker=ticker,
        company_name=company_name,
        synthesized_at=datetime.now(timezone.utc).isoformat(),
        chief_analyst_brief=_build_brief(debate_record, risk_assessment),
        debate_evidence_score=float(debate_record.get("debate_evidence_score", 0.0)),
        debate_confidence_score=float(debate_record.get("debate_confidence_score", 0.0)),
        debate_outcome=debate_record.get("outcome", ""),
        overall_risk_assessment=overall_risk,
        ready_for_chief_analyst=ready,
        blocking_issues=blocking,
        metadata={
            "contention_count":     len(contentions),
            "critical_contentions": sum(1 for c in contentions if c.get("severity") == "critical"),
            "material_contentions": sum(1 for c in contentions if c.get("severity") == "material"),
            "raised_risks_count":   debate_record.get("metadata", {}).get("raised_risks_count", 0),
        },
    )


# ─────────────────────────────────────────────
# BRIEF ASSEMBLY
# ─────────────────────────────────────────────

def _build_brief(debate_record: dict, risk_assessment: dict) -> dict:
    """
    Assemble the full structured context the Chief Analyst agent receives.

    Contentions are sorted CRITICAL first so the Chief Analyst sees the most
    important adjudications at the top of the list. All score history is
    included so the Chief Analyst can trace the Layer 4 → debate adjustment
    chain without re-running any computation.
    """
    _severity_order = {"critical": 0, "material": 1, "minor": 2}
    contentions = sorted(
        debate_record.get("contentions", []),
        key=lambda c: _severity_order.get(c.get("severity", "minor"), 2),
    )

    bull = debate_record.get("bull_position", {})
    bear = debate_record.get("bear_position", {})

    return {
        "role": "chief_analyst",
        "instruction": (
            "You are the Chief Analyst. Synthesize the full debate record and risk "
            "assessment below into a final investment recommendation. Follow the "
            "chief_analyst system prompt exactly. Return a valid JSON object — "
            "no prose outside the JSON."
        ),

        "ticker":       debate_record.get("ticker"),
        "company_name": debate_record.get("company_name"),

        "scores": {
            "base_evidence_score":     debate_record.get("base_evidence_score"),
            "base_confidence_score":   debate_record.get("base_confidence_score"),
            "debate_evidence_score":   debate_record.get("debate_evidence_score"),
            "debate_confidence_score": debate_record.get("debate_confidence_score"),
            "original_conviction":     debate_record.get("original_conviction"),
            "original_recommendation": debate_record.get("original_recommendation"),
        },

        "debate_outcome": debate_record.get("outcome"),

        "bull_position": {
            "summary":               bull.get("summary"),
            "key_arguments":         bull.get("key_arguments", []),
            "evidence_cited":        bull.get("evidence_cited", []),
            "contested_items":       bull.get("contested_items", []),
            "raised_risks":          bull.get("raised_risks", []),
            "learning_hooks":        bull.get("learning_hooks", []),
            "score_adjustment":      bull.get("score_adjustment"),
            "confidence_adjustment": bull.get("confidence_adjustment"),
        },

        "bear_position": {
            "summary":               bear.get("summary"),
            "key_arguments":         bear.get("key_arguments", []),
            "evidence_cited":        bear.get("evidence_cited", []),
            "contested_items":       bear.get("contested_items", []),
            "raised_risks":          bear.get("raised_risks", []),
            "learning_hooks":        bear.get("learning_hooks", []),
            "valuation_challenge":   bear.get("valuation_challenge"),
            "score_adjustment":      bear.get("score_adjustment"),
            "confidence_adjustment": bear.get("confidence_adjustment"),
        },

        # Sorted CRITICAL first — Chief Analyst adjudicates in this order
        "contentions": contentions,

        "risk_assessment": {
            "overall_risk_assessment": risk_assessment.get("overall_risk_assessment"),
            "ready_for_chief_analyst": risk_assessment.get("ready_for_chief_analyst"),
            "blocking_issues":         risk_assessment.get("blocking_issues", []),
            "tic_assessment":          risk_assessment.get("tic_assessment", []),
            "tic_coverage_gaps":       risk_assessment.get("tic_coverage_gaps", []),
            "risk_factor_assessment":  risk_assessment.get("risk_factor_assessment", []),
            "missing_risk_factors":    risk_assessment.get("missing_risk_factors", []),
            "binary_event_assessment": risk_assessment.get("binary_event_assessment", []),
            "monitoring_plan":         risk_assessment.get("monitoring_plan", {}),
        },

        # Explicit output format so the agent cannot deviate from the schema
        "output_format": {
            "analyst_role":                    "chief_analyst",
            "recommendation":                  "strong_conviction_enter | moderate_conviction_enter | watch | pass | blocked",
            "investment_archetype_confirmed":   "long_term_compounder | deep_value | does_not_fit",
            "final_evidence_score":             0.0,
            "final_confidence_score":           0.0,
            "executive_summary":               "...",
            "bull_case_assessment":            "...",
            "bear_case_assessment":            "...",
            "critical_contention_adjudications": [
                {"contention_id": "CON-D-001", "adjudication": "bull_correct | bear_correct | unresolvable", "reasoning": "..."}
            ],
            "philosophy_fit":       "strong | adequate | weak | does_not_fit",
            "philosophy_fit_notes": "...",
            "risk_officer_flags":   [],
            "monitoring_priorities": [
                {"priority": 1, "description": "...", "source": "TIC-001 | learning_hook | risk_factor | risk_officer", "frequency": "weekly | monthly | quarterly"}
            ],
            "what_would_change_this": "...",
            "blocking_issues": [],
            "metadata": {
                "debate_outcome_used":  "...",
                "risk_assessment_used": "...",
                "score_basis":          "debate_adjusted",
            },
        },
    }


def _make_synthesis_id(ticker: str) -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"SYN-{ticker}-{ts}-{rand}"
