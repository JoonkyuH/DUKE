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
from typing import Optional

from synthesis_types import SynthesisOutput


def synthesize(
    debate_record: dict,
    risk_assessment: dict,
    price_data: Optional[dict] = None,
) -> SynthesisOutput:
    """
    Assemble the Chief Analyst brief from the debate record and risk assessment.

    Args:
        debate_record:   DebateRecord dict (pipeline/05_debate/schemas/output.json)
        risk_assessment: Risk Officer output dict (from risk_officer prompt)
        price_data:      Merged price_data + extended_data from the Stage 01 screening
                         record. Keys used: current_price, ma_50, ma_200, rsi_14,
                         volume_ratio, above_ma_50, above_ma_200, week_52_high,
                         week_52_low. If None, the market_technical_context section
                         is omitted from the brief.

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
        chief_analyst_brief=_build_brief(debate_record, risk_assessment, price_data),
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
            "evidence_score_note":  debate_record.get("metadata", {}).get("evidence_score_note", ""),
            "confidence_score_note": debate_record.get("metadata", {}).get("confidence_score_note", ""),
        },
    )


# ─────────────────────────────────────────────
# BRIEF ASSEMBLY
# ─────────────────────────────────────────────

def _build_brief(
    debate_record: dict,
    risk_assessment: dict,
    price_data: Optional[dict] = None,
) -> dict:
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

    bull     = debate_record.get("bull_position", {})
    bear     = debate_record.get("bear_position", {})
    tech_ctx = _derive_technical_context(price_data) if price_data else {}
    disagreement_note = _market_disagreement_note(tech_ctx) if tech_ctx else None

    brief = {
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

    # Inject technical context if price_data was supplied
    if tech_ctx:
        brief["market_technical_context"] = tech_ctx
        brief["risk_assessment"]["market_disagreement_note"] = disagreement_note

    return brief


# ─────────────────────────────────────────────
# TECHNICAL CONTEXT HELPERS
# ─────────────────────────────────────────────

def _derive_technical_context(price_data: dict) -> dict:
    """
    Compute the market_technical_context block from a merged price_data +
    extended_data dict (as produced by data_fetcher.fetch_market_data()).

    Expected keys (all optional — missing keys are handled gracefully):
      current_price, ma_50, ma_200, rsi_14, volume_ratio,
      above_ma_50, above_ma_200, week_52_high, week_52_low
    """
    current      = price_data.get("current_price")
    ma_50        = price_data.get("ma_50")
    ma_200       = price_data.get("ma_200")
    rsi_14       = price_data.get("rsi_14")
    vol_ratio    = price_data.get("volume_ratio")
    above_ma_50  = price_data.get("above_ma_50")
    above_ma_200 = price_data.get("above_ma_200")
    hi_52w       = price_data.get("week_52_high")
    lo_52w       = price_data.get("week_52_low")

    if current is None:
        return {}

    def _pct(a, b):
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / b * 100, 2)

    vs_ma200 = _pct(current, ma_200)
    vs_ma50  = _pct(current, ma_50)
    vs_hi    = _pct(current, hi_52w)   # ≤ 0 (below high)
    vs_lo    = _pct(current, lo_52w)   # ≥ 0 (above low)

    # Use pre-computed booleans when available; fall back to sign of pct
    _above_200 = above_ma_200 if above_ma_200 is not None else (vs_ma200 is not None and vs_ma200 > 0)
    _above_50  = above_ma_50  if above_ma_50  is not None else (vs_ma50  is not None and vs_ma50  > 0)

    # Technical posture — priority: RSI extreme → MA structure
    if rsi_14 is not None and rsi_14 < 35:
        posture = "oversold"
    elif rsi_14 is not None and rsi_14 > 70:
        posture = "overbought"
    elif not _above_200 and _above_50:
        posture = "recovering"
    elif not _above_200:
        posture = "technical_breakdown"
    else:
        posture = "technical_uptrend"

    return {
        "price_vs_ma200_pct":  vs_ma200,
        "price_vs_ma50_pct":   vs_ma50,
        "rsi_14":              rsi_14,
        "volume_ratio":        vol_ratio,
        "pct_from_52w_high":   vs_hi,
        "pct_from_52w_low":    vs_lo,
        "technical_posture":   posture,
    }


def _market_disagreement_note(ctx: dict) -> str:
    """
    One-sentence plain-English summary of what the technical posture means
    for the entry decision. Written for the Risk Officer section of the brief.
    """
    posture  = ctx.get("technical_posture", "")
    rsi      = ctx.get("rsi_14")
    vs_200   = ctx.get("price_vs_ma200_pct")
    vs_50    = ctx.get("price_vs_ma50_pct")

    rsi_tag  = f"RSI {rsi:.0f}" if rsi is not None else "RSI unavailable"

    if posture == "technical_breakdown":
        pct_tag = f"({vs_200:+.1f}% vs 200MA) " if vs_200 is not None else ""
        return (
            f"Stock is in technical breakdown below the 200-day MA {pct_tag}with "
            f"{rsi_tag} — market is actively selling despite fundamental strength; "
            f"investigate whether the market knows something the evidence packet does not."
        )
    elif posture == "recovering":
        pct_tag = (
            f"(above 50MA {vs_50:+.1f}%, below 200MA {vs_200:+.1f}%) "
            if vs_200 is not None and vs_50 is not None else ""
        )
        return (
            f"Stock is above the 50-day MA but below the 200-day MA {pct_tag}with "
            f"{rsi_tag} — price is recovering but has not reclaimed the primary trend; "
            f"confirm the fundamental catalyst before the price reclaims the 200MA."
        )
    elif posture == "technical_uptrend":
        pct_tag = f"(+{vs_200:.1f}% vs 200MA) " if vs_200 is not None else ""
        return (
            f"Stock is in a technical uptrend above both moving averages {pct_tag}with "
            f"{rsi_tag} — market structure is aligned with the fundamental thesis."
        )
    elif posture == "oversold":
        return (
            f"Stock is oversold with {rsi_tag} — selling pressure may represent a "
            f"temporary dislocation rather than fundamental deterioration; verify no "
            f"new adverse information is driving the weakness before treating as an entry."
        )
    elif posture == "overbought":
        return (
            f"Stock is overbought with {rsi_tag} — momentum is extended; "
            f"entry here risks chasing; consider waiting for a pullback toward the "
            f"50-day MA before initiating a position."
        )
    return "Technical posture is neutral — no specific entry timing concern from market data."


def _make_synthesis_id(ticker: str) -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"SYN-{ticker}-{ts}-{rand}"
