#!/usr/bin/env python3
"""
run.py — Stage 06 (Synthesis) orchestration bridge.

Usage:
    python3 run.py TICKER [--date YYYYMMDD]

If --date is omitted, the most recent debate file for TICKER is used.

Loads:
    data/debate/{TICKER}_debate_{date}.json          Stage 05 DebateRecord
    data/screening/shortlist_{date}.json             Stage 01 price context (optional)

Flow:
    1. Risk Officer review  — Claude API call, assesses risk framework
    2. synthesize()         — assembles Chief Analyst brief (synthesizer.py)
    3. Chief Analyst review — Claude API call, final recommendation
    4. Assemble and write final output

Writes:
    data/synthesis/{TICKER}_synthesis_{date}.json
"""

import argparse
import glob
import json
import logging
import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))

from synthesizer import synthesize  # noqa: E402

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not installed — run: pip install anthropic")

_RISK_MODEL        = "claude-sonnet-4-6"
_CHIEF_MODEL       = "claude-sonnet-4-6"
_RISK_MAX_TOKENS   = 8192
_CHIEF_MAX_TOKENS  = 4096
_REPO_ROOT         = _THIS_DIR.parent.parent
_PROMPTS_DIR = _REPO_ROOT / "pipeline" / "05_debate" / "prompts"

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FILE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def _find_latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file found: {pattern}")
    return Path(matches[-1])


def _load_debate(ticker: str, date_str: str | None) -> tuple[dict, str]:
    base    = str(_REPO_ROOT / "data" / "debate")
    pattern = f"{base}/{ticker}_debate_{date_str or '*'}.json"
    path    = _find_latest(pattern)
    with open(path) as f:
        data = json.load(f)
    date_tag = path.stem.split("_debate_")[-1]
    return data, date_tag


def _load_scoring(ticker: str, date_str: str | None) -> dict:
    base    = str(_REPO_ROOT / "data" / "scored")
    pattern = f"{base}/{ticker}_score_{date_str or '*'}.json"
    try:
        path = _find_latest(pattern)
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _load_shortlist(date_str: str) -> dict | None:
    base = str(_REPO_ROOT / "data" / "screening")
    for pattern in (
        f"{base}/shortlist_{date_str}.json",
        f"{base}/shortlist_*.json",
    ):
        matches = sorted(glob.glob(pattern))
        if matches:
            with open(matches[-1]) as f:
                return json.load(f)
    return None


def _extract_price_data(shortlist: dict | None, ticker: str) -> dict | None:
    # Try per-ticker raw file written by run_screening.py (Fix 4)
    raw_dir = _REPO_ROOT / "data" / "screening" / "raw"
    if raw_dir.is_dir():
        # Find the most recent raw file for this ticker
        raw_files = sorted(raw_dir.glob(f"{ticker}_*.json"))
        if raw_files:
            try:
                with open(raw_files[-1]) as f:
                    raw = json.load(f)
                pd: dict = {}
                pd.update(raw.get("price_data") or {})
                pd.update(raw.get("extended_data") or {})
                if pd:
                    return pd
            except Exception:
                pass

    # Fall back to shortlist file (older runs without per-ticker files)
    if not shortlist:
        return None
    tickers = shortlist.get("tickers", [])
    if isinstance(tickers, list):
        for entry in tickers:
            if entry.get("ticker") == ticker:
                pd = {}
                pd.update(entry.get("price_data") or {})
                pd.update(entry.get("extended_data") or {})
                return pd or None
    elif isinstance(tickers, dict):
        entry = tickers.get(ticker)
        if entry:
            pd = {}
            pd.update(entry.get("price_data") or {})
            pd.update(entry.get("extended_data") or {})
            return pd or None
    return None


def _load_analyst_brief(ticker: str) -> dict:
    brief_dir = _REPO_ROOT / "data" / "processed"
    files = sorted(brief_dir.glob(f"{ticker}_analyst_brief_*.json"))
    if not files:
        log.warning(
            "%s: no analyst brief found — evidence slices will be empty",
            ticker,
        )
        return {}
    brief = json.loads(files[-1].read_text())
    log.info(
        "%s: loaded analyst brief (%s) — %d catalysts %d TICs %d mgmt_quotes",
        ticker,
        files[-1].name,
        len(brief.get("catalyst_map", [])),
        len(brief.get("thesis_invalidation_conditions", [])),
        len(brief.get("management_quotes", [])),
    )
    return brief


def _load_prompt(name: str) -> str:
    with open(_PROMPTS_DIR / name) as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# EVIDENCE FORMATTING
# ─────────────────────────────────────────────────────────────────────────────

def _format_evidence_for_risk_officer(analyst_brief: dict) -> str:
    """
    Build a focused evidence summary for the Risk Officer. Includes only
    risk-relevant management quotes, risk filing quotes, all external bear,
    and competitive/demand external bull.
    """
    lines = []

    RISK_CATEGORIES  = {"risk_factors", "guidance", "tone_shift"}
    RISK_SIGNIFICANCES = {"HIGH", "MEDIUM"}

    risk_mgmt = [
        q for q in analyst_brief.get("management_quotes", [])
        if q.get("category", "") in RISK_CATEGORIES
        and str(q.get("significance", "")).upper() in RISK_SIGNIFICANCES
    ]
    if risk_mgmt:
        lines.append("MANAGEMENT QUOTES (risk/guidance/tone):")
        for q in risk_mgmt:
            speaker = q.get("speaker", "Management")
            text = (q.get("quote_text") or "").replace("\n", " ")[:200]
            cat  = q.get("category", "")
            sig  = q.get("significance", "")
            dirn = q.get("direction", "")
            lines.append(f'  [{speaker} | {cat} | {sig} | {dirn}]')
            lines.append(f'  "{text}"')

    RISK_SECTIONS = {"risk", "mda", "md&a", "risk_factor"}
    risk_filing = [
        q for q in analyst_brief.get("filing_quotes", [])
        if (q.get("category", "") in {"risk_factors", "guidance", "tone_shift"}
            or any(
                rs in str(q.get("filing_section_label", "")).lower()
                for rs in RISK_SECTIONS
            ))
    ]
    if risk_filing:
        lines.append("\nFILING QUOTES (risk/MDA):")
        for q in risk_filing:
            src  = q.get("filing_section_label") or "SEC Filing"
            text = (q.get("quote_text") or "").replace("\n", " ")[:200]
            cat  = q.get("category", "")
            sig  = q.get("significance", "")
            dirn = q.get("direction", "")
            lines.append(f'  [{src} | {cat} | {sig} | {dirn}]')
            lines.append(f'  "{text}"')

    bear_ev = analyst_brief.get("external_bear_evidence", [])
    if bear_ev:
        lines.append("\nEXTERNAL BEAR EVIDENCE:")
        for e in bear_ev:
            snippet = (
                e.get("snippet") or e.get("quote_text") or e.get("title") or ""
            ).replace("\n", " ")[:200]
            src = e.get("source", "")
            lines.append(f'  [{src}] "{snippet}"')

    bull_ev = analyst_brief.get("external_bull_evidence", [])
    if bull_ev:
        lines.append("\nEXTERNAL BULL EVIDENCE:")
        for e in bull_ev:
            snippet = (
                e.get("snippet") or e.get("quote_text") or e.get("title") or ""
            ).replace("\n", " ")[:200]
            src = e.get("source", "")
            lines.append(f'  [{src}] "{snippet}"')

    return "\n".join(lines) if lines else "No filtered evidence available."


def _format_evidence_for_chief(analyst_brief: dict) -> str:
    """
    Build the full compressed evidence summary for the Chief Analyst. Includes
    all compressed items across all 4 buckets.
    """
    lines = []

    mgmt_qs = analyst_brief.get("management_quotes", [])
    if mgmt_qs:
        lines.append("MANAGEMENT QUOTES:")
        for q in mgmt_qs:
            speaker = q.get("speaker", "Management")
            text = (q.get("quote_text") or "").replace("\n", " ")[:200]
            cat  = q.get("category", "")
            sig  = q.get("significance", "")
            dirn = q.get("direction", "")
            lines.append(f'  [{speaker} | {cat} | {sig} | {dirn}]')
            lines.append(f'  "{text}"')

    filing_qs = analyst_brief.get("filing_quotes", [])
    if filing_qs:
        lines.append("\nFILING QUOTES:")
        for q in filing_qs:
            src  = q.get("filing_section_label") or "SEC Filing"
            text = (q.get("quote_text") or "").replace("\n", " ")[:200]
            cat  = q.get("category", "")
            sig  = q.get("significance", "")
            dirn = q.get("direction", "")
            lines.append(f'  [{src} | {cat} | {sig} | {dirn}]')
            lines.append(f'  "{text}"')

    bull_ev = analyst_brief.get("external_bull_evidence", [])
    if bull_ev:
        lines.append("\nEXTERNAL BULL EVIDENCE:")
        for e in bull_ev:
            snippet = (
                e.get("snippet") or e.get("quote_text") or e.get("title") or ""
            ).replace("\n", " ")[:200]
            src = e.get("source", "")
            lines.append(f'  [{src}] "{snippet}"')

    bear_ev = analyst_brief.get("external_bear_evidence", [])
    if bear_ev:
        lines.append("\nEXTERNAL BEAR EVIDENCE:")
        for e in bear_ev:
            snippet = (
                e.get("snippet") or e.get("quote_text") or e.get("title") or ""
            ).replace("\n", " ")[:200]
            src = e.get("source", "")
            lines.append(f'  [{src}] "{snippet}"')

    return "\n".join(lines) if lines else "No evidence available."


# ─────────────────────────────────────────────────────────────────────────────
# RISK OFFICER BRIEF
# ─────────────────────────────────────────────────────────────────────────────

def _build_risk_brief(debate_record: dict, scoring: dict, analyst_brief: dict) -> dict:
    """
    Assemble the Risk Officer's input from the debate record, scoring output,
    and analyst brief.
    """
    disclosed_risk_items = scoring.get("metadata", {}).get("disclosed_risk_items", [])
    return {
        "ticker":       debate_record.get("ticker"),
        "company_name": debate_record.get("company_name"),
        "risk_burden_score":     scoring.get("risk_burden_score", 0.0),
        "disclosed_risk_items":  disclosed_risk_items,
        "debate_record": {
            "debate_id":               debate_record.get("debate_id"),
            "outcome":                 debate_record.get("outcome"),
            "base_evidence_score":     debate_record.get("base_evidence_score"),
            "base_confidence_score":   debate_record.get("base_confidence_score"),
            "debate_evidence_score":   debate_record.get("debate_evidence_score"),
            "debate_confidence_score": debate_record.get("debate_confidence_score"),
            "original_conviction":     debate_record.get("original_conviction"),
            "original_recommendation": debate_record.get("original_recommendation"),
            "bull_position":           debate_record.get("bull_position", {}),
            "bear_position":           debate_record.get("bear_position", {}),
            "contentions":             debate_record.get("contentions", []),
            "metadata":                debate_record.get("metadata", {}),
        },
        "thesis_invalidation_conditions": analyst_brief.get("thesis_invalidation_conditions", []),
        "risk_factors":                   scoring.get("metadata", {}).get("risk_factors", []),
        "catalyst_map":                   analyst_brief.get("catalyst_map", []),
        "evidence_brief":                 _format_evidence_for_risk_officer(analyst_brief),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE API
# ─────────────────────────────────────────────────────────────────────────────

def _repair_truncated_json(raw: str) -> dict | None:
    """
    Salvage a truncated JSON object by finding the last complete top-level key
    and closing the object there. Walks backwards through top-level comma
    boundaries (`,\n  "`) and tries to close the object at each one.
    """
    import re
    for match in reversed(list(re.finditer(r',\s*\n\s*"', raw))):
        candidate = raw[:match.start()].rstrip() + "\n}"
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _call_analyst(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    user_content: dict,
    label: str,
    max_tokens: int = _CHIEF_MAX_TOKENS,
) -> dict:
    user_msg = (
        "Here is your structured brief. Review it carefully and return a valid JSON object.\n\n"
        + json.dumps(user_content, indent=2, default=str)
    )
    print(f"  calling {label}...", flush=True)
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()

    if raw.startswith("```"):
        lines = raw.splitlines()
        start = 1
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        raw   = "\n".join(lines[start:end])

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        repaired = _repair_truncated_json(raw)
        if repaired is not None:
            print(f"  WARNING: {label} response truncated — repaired from partial JSON ({len(repaired)} keys recovered)")
            return repaired
        print(f"  WARNING: {label} response is not valid JSON — {exc}")
        print(f"  raw (first 400 chars): {raw[:400]}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACKS
# ─────────────────────────────────────────────────────────────────────────────

def _risk_fallback() -> dict:
    return {
        "analyst_role":            "risk_officer",
        "overall_risk_assessment": "adequate",
        "ready_for_chief_analyst": True,
        "blocking_issues":         [],
        "tic_assessment":          [],
        "tic_coverage_gaps":       ["Risk Officer response could not be parsed — assessment incomplete."],
        "risk_factor_assessment":  [],
        "missing_risk_factors":    [],
        "binary_event_assessment": [],
        "monitoring_plan": {
            "recommended_review_frequency": "monthly",
            "leading_indicator_tics":        [],
            "lagging_indicator_tics":        [],
            "exit_clarity":                  "ambiguous",
            "exit_clarity_notes":            "Risk Officer parse failure — review manually.",
        },
        "learning_hooks":          [],
        "additional_observations": "Risk Officer parse failed; using minimal defaults.",
    }


def _chief_fallback(debate_record: dict) -> dict:
    return {
        "analyst_role":                      "chief_analyst",
        "recommendation":                    "watch",
        "investment_archetype_confirmed":    "long_term_compounder",
        "final_evidence_score":              float(debate_record.get("debate_evidence_score") or 0.0),
        "final_confidence_score":            float(debate_record.get("debate_confidence_score") or 0.0),
        "executive_summary":                 "Chief Analyst response could not be parsed — manual review required.",
        "bull_case_assessment":              "",
        "bear_case_assessment":              "",
        "critical_contention_adjudications": [],
        "philosophy_fit":                    "adequate",
        "philosophy_fit_notes":              "",
        "risk_officer_flags":                [],
        "monitoring_priorities":             [],
        "what_would_change_this":            "",
        "blocking_issues":                   [],
        "metadata": {
            "debate_outcome_used":  debate_record.get("outcome", ""),
            "risk_assessment_used": "adequate",
            "score_basis":          "debate_adjusted",
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def _collect_learning_hooks(debate_record: dict) -> list:
    hooks = []
    for h in debate_record.get("bull_position", {}).get("learning_hooks", []):
        hooks.append({"source": "bull", "hook": h})
    for h in debate_record.get("bear_position", {}).get("learning_hooks", []):
        hooks.append({"source": "bear", "hook": h})
    return hooks


def _write_synthesis(record: dict, ticker: str, date_tag: str) -> Path:
    out_dir = _REPO_ROOT / "data" / "synthesis"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}_synthesis_{date_tag}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    return path


def _fmt_score(v: object) -> str:
    if isinstance(v, (int, float)):
        return f"{v:+.1f}"
    return str(v)


def _print_summary(record: dict) -> None:
    ca  = record.get("chief_analyst_output", {})
    ra  = record.get("risk_assessment", {})
    m   = record.get("metadata", {})

    rec     = ca.get("recommendation", "—")
    arch    = ca.get("investment_archetype_confirmed", "—")
    fit     = ca.get("philosophy_fit", "—")
    ev      = _fmt_score(ca.get("final_evidence_score", "—"))
    cf      = _fmt_score(ca.get("final_confidence_score", "—"))
    overall = ra.get("overall_risk_assessment", "—")
    ready   = ra.get("ready_for_chief_analyst", "—")
    blockers = ra.get("blocking_issues", [])
    n_con   = m.get("contention_count", 0)
    n_crit  = m.get("critical_contentions", 0)
    n_hooks = len(record.get("learning_hooks", []))

    print()
    print("=" * 62)
    print(f"  SYNTHESIS COMPLETE — {record.get('ticker')}  ({record.get('synthesized_at', '')[:10]})")
    print("=" * 62)
    print(f"  Recommendation:    {rec}")
    print(f"  Archetype:         {arch}")
    print(f"  Philosophy fit:    {fit}")
    print(f"  Final scores:      evidence={ev}  conf={cf}")
    print(f"  Overall risk:      {overall}  (ready={ready})")
    if blockers:
        for b in blockers:
            print(f"  BLOCKER:           {b}")
    print(f"  Contentions:       {n_con}  (critical={n_crit})")
    print(f"  Learning hooks:    {n_hooks}")
    print("=" * 62)

    summary = ca.get("executive_summary", "")
    if summary:
        print()
        words = summary.split()
        line  = "  "
        for w in words:
            if len(line) + len(w) + 1 > 72:
                print(line.rstrip())
                line = "  " + w + " "
            else:
                line += w + " "
        if line.strip():
            print(line.rstrip())
        print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 06 Synthesis orchestration")
    parser.add_argument("ticker", type=str.upper)
    parser.add_argument("--date", default=None, help="YYYYMMDD (defaults to most recent debate file)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set in environment")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"\nStage 06 Synthesis — {args.ticker}")
    print("-" * 40)

    # ── Load debate record ────────────────────────────────────────────────────
    debate_record, date_tag = _load_debate(args.ticker, args.date)
    print(f"  debate:         {args.ticker}_debate_{date_tag}.json")
    print(f"  outcome:        {debate_record.get('outcome')}")
    ev0 = debate_record.get("debate_evidence_score") or 0.0
    cf0 = debate_record.get("debate_confidence_score") or 0.0
    print(f"  scores:         ev={ev0:+.1f}  conf={cf0:.1f}")

    # ── Load scoring output (for risk_burden_score + disclosed_risk_items) ────
    scoring = _load_scoring(args.ticker, args.date)
    rbs = scoring.get("risk_burden_score", 0.0)
    n_risk = scoring.get("metadata", {}).get("risk_items_count", "n/a")
    print(f"  risk_burden:    {rbs:.1f}  ({n_risk} disclosed risk items)")

    # ── Load analyst brief (for TICs, catalyst_map, and evidence slices) ─────
    analyst_brief = _load_analyst_brief(args.ticker)
    n_cats = len(analyst_brief.get("catalyst_map", []))
    n_tics = len(analyst_brief.get("thesis_invalidation_conditions", []))
    print(f"  analyst_brief:  {n_cats} catalysts  {n_tics} TICs")

    # ── Load price context (optional) ────────────────────────────────────────
    shortlist  = _load_shortlist(date_tag)
    price_data = _extract_price_data(shortlist, args.ticker)
    print(f"  price_data:     {'available' if price_data else 'none (technical context omitted)'}")

    # ── Risk Officer ──────────────────────────────────────────────────────────
    print("\nRisk Officer assessment")
    risk_system = _load_prompt("risk_officer.md")
    risk_brief  = _build_risk_brief(debate_record, scoring, analyst_brief)
    risk_raw    = _call_analyst(client, _RISK_MODEL, risk_system, risk_brief, "Risk Officer", max_tokens=_RISK_MAX_TOKENS)

    if risk_raw:
        risk_assessment = risk_raw
        # Ensure synthesize() gets the three keys it reads
        risk_assessment.setdefault("overall_risk_assessment", "adequate")
        risk_assessment.setdefault("ready_for_chief_analyst", True)
        risk_assessment.setdefault("blocking_issues", [])
    else:
        risk_assessment = _risk_fallback()

    overall = risk_assessment.get("overall_risk_assessment")
    ready   = risk_assessment.get("ready_for_chief_analyst")
    print(f"  risk:           {overall}  (ready={ready})")
    if risk_assessment.get("blocking_issues"):
        for b in risk_assessment["blocking_issues"]:
            print(f"  BLOCKER:        {b}")

    # ── Synthesize chief analyst brief ───────────────────────────────────────
    synthesis_output = synthesize(debate_record, risk_assessment, price_data)
    synthesis_dict   = synthesis_output.to_dict()

    # ── Chief Analyst ─────────────────────────────────────────────────────────
    print("\nChief Analyst synthesis")
    chief_system = _load_prompt("chief_analyst.md")
    chief_brief  = synthesis_dict["chief_analyst_brief"]
    chief_brief["evidence_brief"] = _format_evidence_for_chief(analyst_brief)
    chief_raw    = _call_analyst(client, _CHIEF_MODEL, chief_system, chief_brief, "Chief Analyst")

    chief_output = chief_raw if chief_raw else _chief_fallback(debate_record)

    # ── Assemble and write ────────────────────────────────────────────────────
    learning_hooks = _collect_learning_hooks(debate_record)
    final = {
        **synthesis_dict,
        "chief_analyst_output": chief_output,
        "risk_assessment":      risk_assessment,
        "learning_hooks":       learning_hooks,
    }

    out_path = _write_synthesis(final, args.ticker, date_tag)
    print(f"\n  written: {out_path.relative_to(_REPO_ROOT)}")

    _print_summary(final)


if __name__ == "__main__":
    main()
