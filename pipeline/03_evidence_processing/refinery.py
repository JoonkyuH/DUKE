"""
refinery.py
Main orchestrator for Stage 03 — Evidence Refinery.

Entry point:
    build_analyst_brief(packet: dict) -> dict

Reads a Stage-02 evidence packet and produces a structured analyst brief
ready for the debate analysts in Stage 05. Includes one LLM call at the
end to synthesize catalyst_map, thesis_invalidation_conditions, and
uncertainties from the compressed evidence.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("refinery")

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_REPO_ROOT   = Path(__file__).resolve().parent.parent.parent

from scorer import (
    load_weights,
    build_url_date_map,
    build_contradiction_ids,
    score_evidence_item,
    score_discovery_candidate,
)
from ranker import rank_and_budget


# ─────────────────────────────────────────────
# COVERAGE HELPERS
# ─────────────────────────────────────────────

_TRANSCRIPT_SUBTYPE_STATUS = {
    "earnings_press_release":       "prepared_material_only",
    "earnings_call":                "full_transcript",
    "earnings_call_transcript":     "full_transcript",
    "sec_8k_exhibit":               "prepared_material_only",
    "sec_8k_exhibit_press_release": "prepared_material_only",
    "ir_press_release":             "prepared_material_only",
}


def _transcript_status(transcript: dict) -> str:
    subtype = (transcript.get("document_subtype") or "").lower()
    if not subtype:
        return "not_available"
    return _TRANSCRIPT_SUBTYPE_STATUS.get(subtype, "other")


def _evidence_quality_signal(
    mgmt_count: int,
    filing_count: int,
    bull_count: int,
    bear_count: int,
) -> str:
    if mgmt_count == 0 or filing_count < 5:
        return "weak"
    if mgmt_count >= 5 and filing_count >= 10 and (bull_count >= 2 or bear_count >= 2):
        return "strong"
    return "moderate"


def _build_coverage_warnings(
    transcript_status: str,
    has_q_and_a: bool,
    bull_count: int,
    bear_count: int,
    quality_signal: str,
) -> list:
    warnings = []
    if transcript_status == "prepared_material_only":
        warnings.append(
            "Transcript is prepared materials only; Q&A not available. "
            "Management responses to analyst questions cannot be assessed."
        )
    if transcript_status == "not_available":
        warnings.append("No transcript or press release found for this period.")
    if bull_count == 0:
        warnings.append("No external bull-case discovery candidates found.")
    if bear_count == 0:
        warnings.append("No external bear-case discovery candidates found.")
    if bull_count > 0 and bear_count == 0:
        warnings.append(
            "Asymmetric external coverage: bull candidates present but no bear candidates. "
            "External perspective may be one-sided."
        )
    if quality_signal == "weak":
        warnings.append("Evidence quality signal is weak — brief may be incomplete.")
    return warnings


def _build_source_limitations(packet: dict, transcript_status: str) -> list:
    """
    Generate source limitation notices from the packet's structural properties.
    These are always included in the brief regardless of budget.
    """
    lims = []
    sf = packet.get("sec_filings") or {}

    if transcript_status == "prepared_material_only":
        lims.append({
            "limitation_type": "transcript_coverage",
            "description": (
                "Only an earnings press release (SEC 8-K exhibit) was available. "
                "No earnings call transcript or Q&A session was acquired."
            ),
            "impact": "Management tone and analyst question responses are absent.",
        })
    elif transcript_status == "not_available":
        lims.append({
            "limitation_type": "transcript_coverage",
            "description": "No transcript or press release was acquired for this period.",
            "impact": "All management quote evidence originates from SEC filings only.",
        })

    if not sf.get("10-Q"):
        lims.append({
            "limitation_type": "filing_gap",
            "description": "No 10-Q was acquired for the most recent quarter.",
            "impact": "Quarterly balance sheet and cash-flow discussion may be missing.",
        })

    if not sf.get("10-K"):
        lims.append({
            "limitation_type": "filing_gap",
            "description": "No 10-K was acquired.",
            "impact": "Annual risk factors and business overview are absent.",
        })

    disc_count = len(packet.get("discovery_candidates") or [])
    if disc_count == 0:
        lims.append({
            "limitation_type": "external_coverage",
            "description": "No external discovery candidates were returned by Perplexity.",
            "impact": "External bull/bear perspective is absent from this brief.",
        })

    return lims


# ─────────────────────────────────────────────
# SYNTHESIS (LLM call)
# ─────────────────────────────────────────────

_SIG_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_EMPTY_SYNTHESIS = {
    "catalyst_map": [],
    "thesis_invalidation_conditions": [],
    "uncertainties": [],
}


def _synthesize_structured_fields(brief: dict, ticker: str) -> dict:
    """
    Generate catalyst_map, TICs, and uncertainties from the compressed brief evidence.
    Makes one LLM call using prompts/synthesis.md. Returns empty lists on any failure.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    try:
        from common.llm import get_client
        client = get_client("synthesis")
    except Exception as exc:
        log.warning("%s: LLM client unavailable for synthesis: %s", ticker, exc)
        return _EMPTY_SYNTHESIS

    prompt_path = _PROMPTS_DIR / "synthesis.md"
    try:
        prompt_template = prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("%s: synthesis.md not found at %s", ticker, prompt_path)
        return _EMPTY_SYNTHESIS

    # Build focused evidence summary for the prompt
    lines = []

    mgmt_qs = sorted(
        brief.get("management_quotes", []),
        key=lambda q: _SIG_ORDER.get(str(q.get("significance") or "").upper(), 3),
    )[:5]
    if mgmt_qs:
        lines.append("MANAGEMENT QUOTES:")
        for q in mgmt_qs:
            speaker = q.get("speaker", "Management")
            text    = (q.get("quote_text") or "").replace("\n", " ")
            cat     = q.get("category", "")
            sig     = q.get("significance", "")
            dirn    = q.get("direction", "")
            lines.append(f'  [{speaker}] "{text}" ({cat}, {sig}, {dirn})')

    filing_qs = sorted(
        brief.get("filing_quotes", []),
        key=lambda q: _SIG_ORDER.get(str(q.get("significance") or "").upper(), 3),
    )[:5]
    if filing_qs:
        lines.append("\nSEC FILING QUOTES:")
        for q in filing_qs:
            source = q.get("filing_section_label") or "SEC Filing"
            text   = (q.get("quote_text") or "").replace("\n", " ")
            cat    = q.get("category", "")
            sig    = q.get("significance", "")
            dirn   = q.get("direction", "")
            lines.append(f'  [{source}] "{text}" ({cat}, {sig}, {dirn})')

    bull_ev = brief.get("external_bull_evidence", [])
    if bull_ev:
        lines.append("\nEXTERNAL BULL EVIDENCE:")
        for e in bull_ev:
            snippet = (e.get("snippet") or e.get("quote_text") or e.get("title") or "").replace("\n", " ")
            lines.append(f'  [BULL] "{snippet}"')

    bear_ev = brief.get("external_bear_evidence", [])
    if bear_ev:
        lines.append("\nEXTERNAL BEAR EVIDENCE:")
        for e in bear_ev:
            snippet = (e.get("snippet") or e.get("quote_text") or e.get("title") or "").replace("\n", " ")
            lines.append(f'  [BEAR] "{snippet}"')

    evidence_summary = "\n".join(lines)
    archetype        = brief.get("screening_archetype", "")

    prompt = (
        prompt_template
        .replace("{ticker}", ticker)
        .replace("{archetype}", archetype)
        .replace("{evidence_summary}", evidence_summary)
    )

    try:
        raw = client.structured_generate(
            prompt=prompt,
            system=(
                "You are a senior financial analyst producing structured investment research. "
                "Return ONLY valid JSON matching the specified schema. No preamble or markdown."
            ),
        )
    except Exception as exc:
        log.warning("%s: synthesis LLM call failed: %s", ticker, exc)
        return _EMPTY_SYNTHESIS

    # Unwrap response
    if isinstance(raw, dict):
        result = raw
    elif isinstance(raw, str):
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("%s: synthesis JSON parse failed: %s", ticker, exc)
            return _EMPTY_SYNTHESIS
    else:
        log.warning("%s: unexpected synthesis response type: %s", ticker, type(raw))
        return _EMPTY_SYNTHESIS

    out = {
        "catalyst_map":                   result.get("catalyst_map", []),
        "thesis_invalidation_conditions": result.get("thesis_invalidation_conditions", []),
        "uncertainties":                  result.get("uncertainties", []),
    }
    log.info(
        "%s: synthesis complete — %d catalysts, %d TICs, %d uncertainties",
        ticker,
        len(out["catalyst_map"]),
        len(out["thesis_invalidation_conditions"]),
        len(out["uncertainties"]),
    )
    return out


# ─────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────

def build_analyst_brief(packet: dict) -> dict:
    """
    Transform a Stage-02 evidence packet into a Stage-03 analyst brief.

    Steps:
      1. Score all evidence items and discovery candidates.
      2. Inject '_score' into each item (non-destructive copy not required;
         '_score' is a synthetic field that was not in the Stage-02 output).
      3. Apply budget enforcement via ranker.
      4. Build coverage report and source limitations.
      5. Assemble and return the brief dict.
    """
    weights       = load_weights()
    url_date_map  = build_url_date_map(packet)
    contradictions = packet.get("contradictions") or []
    con_ids       = build_contradiction_ids(contradictions)
    today         = datetime.now(timezone.utc).date()
    # Fallback date for management_quotes whose transcript URL isn't in url_date_map
    packet_date   = (packet.get("generated_at") or "")[:10] or today.isoformat()

    # ── Score evidence_items ────────────────
    scored_items = []
    for item in (packet.get("evidence_items") or []):
        s = score_evidence_item(item, weights, con_ids, url_date_map, today, packet_date)
        scored_items.append({**item, "_score": s})

    # ── Score discovery_candidates ──────────
    scored_candidates = []
    for cand in (packet.get("discovery_candidates") or []):
        s = score_discovery_candidate(cand, weights, today)
        scored_candidates.append({**cand, "_score": s})

    # ── Source limitations (always included) ─
    t_obj    = packet.get("transcript") or {}
    t_status = _transcript_status(t_obj)
    source_limitations = _build_source_limitations(packet, t_status)

    # ── Budget enforcement ──────────────────
    result = rank_and_budget(
        scored_items, scored_candidates, contradictions, source_limitations
    )

    # ── Coverage report ─────────────────────
    bull_qt   = {"bull_case", "competitive_advantage", "sector_opportunity"}
    bear_qt   = {"bear_case", "competitive_risk", "sector_risk"}
    all_bull  = [c for c in scored_candidates if set(c.get("query_types") or []) & bull_qt]
    all_bear  = [c for c in scored_candidates if set(c.get("query_types") or []) & bear_qt]
    mgmt_all  = [e for e in scored_items if e.get("item_class") == "management_quote"]
    filing_all = [e for e in scored_items if e.get("item_class") == "filing_quote"]

    quality   = _evidence_quality_signal(
        len(mgmt_all), len(filing_all), len(all_bull), len(all_bear)
    )
    warnings  = _build_coverage_warnings(
        t_status, t_obj.get("has_q_and_a") or False,
        len(all_bull), len(all_bear), quality
    )

    coverage_report = {
        "transcript_status":             t_status,
        "has_q_and_a":                   t_obj.get("has_q_and_a") or False,
        "management_quotes_available":   len(mgmt_all),
        "filing_quotes_available":       len(filing_all),
        "external_bull_candidates":      len(all_bull),
        "external_bear_candidates":      len(all_bear),
        "coverage_warnings":             warnings,
        "evidence_quality_signal":       quality,
    }

    # ── Totals ──────────────────────────────
    total_in_brief = (
        len(result.management_quotes)
        + len(result.filing_quotes)
        + len(result.external_bull_evidence)
        + len(result.external_bear_evidence)
        + len(result.uncertainties)
        + len(result.source_limitations)
    )
    total_considered = len(scored_items) + len(scored_candidates) + len(contradictions)
    total_excluded   = sum(result.excluded_counts.values())

    # ── Fiscal period label ─────────────────
    fy  = packet.get("fiscal_year") or ""
    fq  = packet.get("fiscal_quarter") or ""
    fiscal_period = f"{fy} {fq}".strip() or packet.get("calendar_period") or ""

    ticker = packet.get("ticker", "")

    # ── Assemble brief ──────────────────────
    brief = {
        "ticker":             ticker,
        "screening_archetype": packet.get("screening_archetype", ""),
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "fiscal_period":      fiscal_period,
        "scoring_version":    weights.get("version", ""),

        "coverage_report":    coverage_report,

        "management_quotes":      result.management_quotes,
        "filing_quotes":          result.filing_quotes,
        "external_bull_evidence": result.external_bull_evidence,
        "external_bear_evidence": result.external_bear_evidence,
        "contradictions":         contradictions,
        "uncertainties":          result.uncertainties,
        "source_limitations":     result.source_limitations,

        "metadata": {
            "total_evidence_considered": total_considered,
            "total_evidence_in_brief":   total_in_brief,
            "evidence_excluded_by_budget": total_excluded,
            "scoring_version":           weights.get("version", ""),
        },
    }

    # ── Synthesis (LLM) ─────────────────────
    synthesis = _synthesize_structured_fields(brief, ticker)
    brief["catalyst_map"]                   = synthesis["catalyst_map"]
    brief["thesis_invalidation_conditions"] = synthesis["thesis_invalidation_conditions"]
    brief["uncertainties"]                  = synthesis["uncertainties"]

    return brief
