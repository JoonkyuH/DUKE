"""
formatter.py
Format the Chief Analyst output and synthesis metadata as human-readable
terminal output.

Entry point: format_recommendation(chief_analyst_output, synthesis_output) -> str

The returned string is ready for print() — no external dependencies.
"""

import json
from pathlib import Path
from typing import Optional

_PROFILE_PATH = Path(__file__).parent.parent.parent / "config" / "investor_profile.json"

_REC_TO_TIER = {
    "strong_conviction_enter":   "full",
    "moderate_conviction_enter": "half",
}

def _load_max_position() -> float:
    try:
        with open(_PROFILE_PATH) as f:
            return float(json.load(f).get("max_position_size_pct", 10.0))
    except (OSError, ValueError, KeyError):
        return 10.0

def _sizing_range(recommendation: str) -> str:
    """Return a human-readable size range string, or empty string if no position."""
    tier = _REC_TO_TIER.get(recommendation)
    if not tier:
        return ""
    max_pct = _load_max_position()
    hi = max_pct if tier == "full" else max_pct * 0.5
    lo = hi * 0.6
    return f"{lo:.1f}–{hi:.1f}% suggested initial position"


# ANSI codes kept minimal — just emphasis, no color library needed
_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_RESET = "\033[0m"
_LINE  = "─" * 72


def format_recommendation(
    chief_analyst_output: dict,
    synthesis_output: Optional[dict] = None,
    technical_state: Optional[dict] = None,
) -> str:
    """
    Render the Chief Analyst output as a terminal-ready report string.

    Args:
        chief_analyst_output: Parsed ChiefAnalystOutput dict
        synthesis_output:     SynthesisOutput dict (optional, adds score context)

    Returns:
        Multi-line string ready for print().
    """
    lines = []
    ca = chief_analyst_output
    syn = synthesis_output or {}
    ts  = technical_state or {}

    ticker       = syn.get("ticker") or "—"
    company_name = syn.get("company_name") or ""

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        "",
        _LINE,
        f"{_BOLD}  DUKE INVESTMENT RECOMMENDATION{_RESET}",
        f"  {ticker}  {company_name}",
        _LINE,
    ]

    # ── Recommendation banner ────────────────────────────────────────────────
    rec       = ca.get("recommendation", "—")
    rec_label = rec.upper().replace("_", " ")
    sizing    = _sizing_range(rec)

    lines += ["", f"{_BOLD}  RECOMMENDATION:  {rec_label}{_RESET}"]
    if sizing:
        lines.append(f"  {sizing}")
        # Nearest support as entry zone hint
        supports = ts.get("key_support_levels", [])
        if supports:
            nearest = max(float(s) for s in supports)
            lines.append(f"  Nearest support: ${nearest:,.2f}")
    elif rec in ("watch", "pass"):
        # Preview what position size would be if conditions were met (full conviction)
        max_pct = _load_max_position()
        hi = round(max_pct, 1)
        lo = round(hi * 0.6, 1)
        lines.append(f"  If conditions met → {lo:.1f}–{hi:.1f}% initial position")
    lines.append("")

    # ── Scores ───────────────────────────────────────────────────────────────
    ev   = ca.get("final_evidence_score")
    conf = ca.get("final_confidence_score")

    base_ev   = syn.get("debate_evidence_score")
    base_conf = syn.get("debate_confidence_score")

    meta = syn.get("metadata", {})
    ev_note   = meta.get("evidence_score_note", "")
    conf_note = meta.get("confidence_score_note", "")

    lines.append(f"  Scores (final / debate-adjusted)")
    lines.append(f"    Evidence score   : {_fmt_score(ev)}  (debate: {_fmt_score(base_ev)})")
    if ev_note:
        lines.append(f"      {_DIM}↳ {ev_note}{_RESET}")
    lines.append(f"    Confidence score : {_fmt_score(conf)}  (debate: {_fmt_score(base_conf)})")
    if conf_note:
        lines.append(f"      {_DIM}↳ {conf_note}{_RESET}")
    lines.append("")

    # ── Philosophy fit ───────────────────────────────────────────────────────
    archetype = ca.get("investment_archetype_confirmed", "—")
    fit       = ca.get("philosophy_fit", "—")
    fit_notes = ca.get("philosophy_fit_notes", "")

    lines.append(f"  Philosophy Fit: {fit.upper()}  ({archetype})")
    if fit_notes:
        lines.append(f"  {_DIM}{fit_notes}{_RESET}")
    lines.append("")

    # ── Executive summary ────────────────────────────────────────────────────
    lines.append(_section("Executive Summary"))
    lines += _wrap(ca.get("executive_summary", ""), indent=2)
    lines.append("")

    # ── Debate outcome ───────────────────────────────────────────────────────
    outcome = syn.get("debate_outcome") or ca.get("metadata", {}).get("debate_outcome_used") or "—"
    risk_status = syn.get("overall_risk_assessment") or "—"
    lines.append(f"  Debate outcome: {outcome.upper().replace('_', ' ')}   "
                 f"Risk status: {risk_status.upper().replace('_', ' ')}")
    lines.append("")

    # ── Bull / Bear assessments ──────────────────────────────────────────────
    lines.append(_section("Bull Case Assessment"))
    lines += _wrap(ca.get("bull_case_assessment", ""), indent=2)
    lines.append("")

    lines.append(_section("Bear Case Assessment"))
    lines += _wrap(ca.get("bear_case_assessment", ""), indent=2)
    lines.append("")

    # ── Critical contention adjudications ───────────────────────────────────
    adjudications = ca.get("critical_contention_adjudications", [])
    if adjudications:
        lines.append(_section("Critical Contention Adjudications"))
        for adj in adjudications:
            cid    = adj.get("contention_id", "—")
            ruling = adj.get("adjudication", "—").upper().replace("_", " ")
            reason = adj.get("reasoning", "")
            lines.append(f"  {cid}  →  {ruling}")
            if reason:
                lines += _wrap(reason, indent=4)
        lines.append("")

    # ── Risk Officer flags ───────────────────────────────────────────────────
    flags = ca.get("risk_officer_flags", [])
    if flags:
        lines.append(_section("Risk Officer Flags"))
        for f in flags:
            lines.append(f"  • {f}")
        lines.append("")

    # ── Monitoring priorities ────────────────────────────────────────────────
    priorities = ca.get("monitoring_priorities", [])
    if priorities:
        lines.append(_section("Monitoring Priorities"))
        for p in priorities:
            n    = p.get("priority", "?")
            desc = p.get("description", "")
            src  = p.get("source", "")
            freq = p.get("frequency", "")
            lines.append(f"  {n}. {desc}")
            lines.append(f"     {_DIM}Source: {src}  |  Frequency: {freq}{_RESET}")
        lines.append("")

    # ── What would change this ───────────────────────────────────────────────
    wwct = ca.get("what_would_change_this", "")
    if wwct:
        lines.append(_section("What Would Change This"))
        lines += _wrap(wwct, indent=2)
        lines.append("")

    # ── Blocking issues ──────────────────────────────────────────────────────
    blocking = ca.get("blocking_issues", [])
    if blocking:
        lines.append(_section("Blocking Issues"))
        for b in blocking:
            lines.append(f"  !! {b}")
        lines.append("")

    lines.append(_LINE)
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _section(title: str) -> str:
    return f"  {_BOLD}{title}{_RESET}"


def _fmt_score(val) -> str:
    if val is None:
        return "—"
    return f"{float(val):.1f}"


def _wrap(text: str, indent: int = 2, width: int = 68) -> list:
    """Naively word-wrap text to terminal width, returning list of lines."""
    if not text:
        return []
    prefix = " " * indent
    words  = text.split()
    lines  = []
    current = prefix
    for word in words:
        if len(current) + len(word) + 1 > width + indent:
            lines.append(current.rstrip())
            current = prefix + word + " "
        else:
            current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines
