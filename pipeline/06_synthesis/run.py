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

_RISK_MODEL  = "claude-sonnet-4-6"
_CHIEF_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS  = 4096
_REPO_ROOT   = _THIS_DIR.parent.parent
_PROMPTS_DIR = _REPO_ROOT / "pipeline" / "05_debate" / "prompts"


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


def _load_prompt(name: str) -> str:
    with open(_PROMPTS_DIR / name) as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# RISK OFFICER BRIEF
# ─────────────────────────────────────────────────────────────────────────────

def _build_risk_brief(debate_record: dict) -> dict:
    """
    Assemble the Risk Officer's input from the debate record.

    thesis_invalidation_conditions, risk_factors, and catalyst_map are empty
    in this run because Stage 03 EvidencePacket is not yet wired through.
    The Risk Officer prompt instructs the model to note coverage gaps.
    """
    return {
        "ticker":       debate_record.get("ticker"),
        "company_name": debate_record.get("company_name"),
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
        # Stage 03 fields — empty until full pipeline wired
        "thesis_invalidation_conditions": [],
        "risk_factors":                   [],
        "catalyst_map":                   [],
        "invalidation_report":            {},
        "instruction": (
            "Note: thesis_invalidation_conditions, risk_factors, and catalyst_map are "
            "empty because Stage 03 output is not yet wired into this data flow. "
            "Assess TIC coverage gaps accordingly and note this structural limitation. "
            "Use the debate record — especially the bear's raised_risks and the "
            "contentions — as your primary inputs."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE API
# ─────────────────────────────────────────────────────────────────────────────

def _call_analyst(
    client: anthropic.Anthropic,
    model: str,
    system_prompt: str,
    user_content: dict,
    label: str,
) -> dict:
    user_msg = (
        "Here is your structured brief. Review it carefully and return a valid JSON object.\n\n"
        + json.dumps(user_content, indent=2, default=str)
    )
    print(f"  calling {label}...", flush=True)
    resp = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
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

    # ── Load price context (optional) ────────────────────────────────────────
    shortlist  = _load_shortlist(date_tag)
    price_data = _extract_price_data(shortlist, args.ticker)
    print(f"  price_data:     {'available' if price_data else 'none (technical context omitted)'}")

    # ── Risk Officer ──────────────────────────────────────────────────────────
    print("\nRisk Officer assessment")
    risk_system = _load_prompt("risk_officer.md")
    risk_brief  = _build_risk_brief(debate_record)
    risk_raw    = _call_analyst(client, _RISK_MODEL, risk_system, risk_brief, "Risk Officer")

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
