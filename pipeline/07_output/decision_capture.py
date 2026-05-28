"""
decision_capture.py
Prompt the investor for their decision inputs and write the completed
record to data/journal/.

Flow:
  1. Display the full formatted recommendation (via formatter.py)
  2. Show sizing guidance based on conviction tier and risk flags
  3. Show portfolio context from data/raw/portfolio/latest.csv if present
  4. Prompt for: action, position_size_pct, conviction_1_to_10,
                 override_recommendation, override_reason, notes
  5. Write the decision record to data/journal/ via journal.py

Entry point: capture_decision(chief_analyst_output, synthesis_output) -> dict
"""

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Sibling-module imports — run this file from pipeline/07_output/
import formatter
import journal


PORTFOLIO_PATH  = Path(__file__).parent.parent.parent / "data" / "raw" / "portfolio" / "latest.csv"
_PROFILE_PATH   = Path(__file__).parent.parent.parent / "config" / "investor_profile.json"


def _load_max_position() -> float:
    try:
        with open(_PROFILE_PATH) as f:
            return float(json.load(f).get("max_position_size_pct", 10.0))
    except (OSError, ValueError, KeyError):
        return 10.0


def _sizing_range(rec: str) -> tuple:
    """Return (lo, hi) percentage range for a given recommendation tier, or (0, 0)."""
    max_pct = _load_max_position()
    tiers = {
        "strong_conviction_enter":   max_pct,
        "moderate_conviction_enter": max_pct * 0.5,
    }
    hi = tiers.get(rec, 0.0)
    if hi == 0.0:
        return (0.0, 0.0)
    return (round(hi * 0.6, 1), round(hi, 1))


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def capture_decision(
    chief_analyst_output: dict,
    synthesis_output: Optional[dict] = None,
) -> dict:
    """
    Display recommendation, collect investor inputs, and write to journal.

    Returns the decision record dict that was written to the journal.
    """
    syn = synthesis_output or {}
    ca  = chief_analyst_output

    # ── 1. Display recommendation ────────────────────────────────────────────
    print(formatter.format_recommendation(ca, syn))

    # ── 2. Sizing guidance ───────────────────────────────────────────────────
    _print_sizing_guidance(ca, syn)

    # ── 3. Portfolio context ─────────────────────────────────────────────────
    _print_portfolio_context()

    # ── 4. Collect inputs ────────────────────────────────────────────────────
    print("\n" + "─" * 72)
    print("  DECISION CAPTURE")
    print("─" * 72 + "\n")

    action = _prompt_choice(
        "Action",
        ["enter", "watch", "pass", "override"],
        default="pass",
    )

    position_size_pct = None
    if action in ("enter", "override"):
        position_size_pct = _prompt_float(
            "Position size (% of portfolio, e.g. 5.0)",
            min_val=0.1, max_val=100.0,
        )

    conviction = _prompt_int("Conviction (1–10)", min_val=1, max_val=10)

    override_recommendation = None
    override_reason         = None
    if action == "override":
        override_recommendation = _prompt_text("Override recommendation (your actual decision)")
        override_reason         = _prompt_text("Override reason (required)")

    notes = _prompt_text("Notes (press Enter to skip)", required=False)

    # ── 5. Assemble and write record ─────────────────────────────────────────
    record = _build_record(
        ca, syn,
        action=action,
        position_size_pct=position_size_pct,
        conviction=conviction,
        override_recommendation=override_recommendation,
        override_reason=override_reason,
        notes=notes,
    )

    path = journal.write_decision_record(record)
    print(f"\n  Decision recorded → {path}\n")

    return record


# ─────────────────────────────────────────────
# SIZING GUIDANCE
# ─────────────────────────────────────────────

def _print_sizing_guidance(ca: dict, syn: dict) -> None:
    rec      = ca.get("recommendation", "")
    fit      = ca.get("philosophy_fit", "")
    risk     = syn.get("overall_risk_assessment", "adequate")
    flags    = ca.get("risk_officer_flags", [])
    blocking = ca.get("blocking_issues", [])

    lo, hi = _sizing_range(rec)

    print("  SIZING GUIDANCE")
    print("  " + "─" * 40)

    if blocking:
        print("  Blocked — do not size. Resolve blocking issues first.")
        for b in blocking:
            print(f"    !! {b}")
        print()
        return

    if hi == 0.0:
        print(f"  {rec.upper().replace('_', ' ')} — no position recommended.")
        print()
        return

    # Downgrade ceiling for risk flags or weak philosophy fit
    if risk == "needs_attention" or flags:
        hi = round(hi * 0.6, 1)
        lo = round(lo * 0.6, 1)
        print(f"  {lo:.1f}–{hi:.1f}% of portfolio")
        print("  Reduced from base — Risk Officer flags or needs-attention status.")
    elif fit in ("weak", "does_not_fit"):
        hi = round(hi * 0.5, 1)
        lo = round(lo * 0.5, 1)
        print(f"  {lo:.1f}–{hi:.1f}% of portfolio")
        print("  Reduced from base — weak philosophy fit.")
    else:
        print(f"  {lo:.1f}–{hi:.1f}% of portfolio")

    if rec == "moderate_conviction_enter":
        print("  Add on confirmation before building to full size.")
    print()


# ─────────────────────────────────────────────
# PORTFOLIO CONTEXT
# ─────────────────────────────────────────────

def _print_portfolio_context() -> None:
    if not PORTFOLIO_PATH.exists():
        return

    try:
        with open(PORTFOLIO_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (OSError, csv.Error):
        return

    if not rows:
        return

    print("  CURRENT PORTFOLIO CONTEXT")
    print("  " + "─" * 40)

    total_pct = 0.0
    for row in rows:
        ticker = row.get("ticker") or row.get("Ticker") or "—"
        pct    = row.get("weight_pct") or row.get("Weight") or row.get("pct") or "—"
        name   = row.get("name") or row.get("Company") or ""
        label  = f"{ticker}  {name}".strip()
        print(f"    {label:<30} {pct}%")
        try:
            total_pct += float(str(pct).replace("%", ""))
        except ValueError:
            pass

    cash_pct = max(0.0, 100.0 - total_pct)
    print(f"    {'Cash / Undeployed':<30} {cash_pct:.1f}%")
    print(f"    Positions: {len(rows)}")
    print()


# ─────────────────────────────────────────────
# RECORD ASSEMBLY
# ─────────────────────────────────────────────

def _build_record(
    ca: dict,
    syn: dict,
    *,
    action: str,
    position_size_pct,
    conviction: int,
    override_recommendation,
    override_reason,
    notes: str,
) -> dict:
    now = datetime.now(timezone.utc)
    ticker = syn.get("ticker") or ca.get("ticker") or "UNKNOWN"
    # Python-computed entry-price band; the Chief no longer emits these numbers.
    ce = syn.get("computed_entry", {}) or {}

    return {
        "ticker":       ticker,
        "company_name": syn.get("company_name") or "",
        "date":         now.strftime("%Y-%m-%d"),
        "decided_at":   now.isoformat(),

        # Analyst outputs
        "synthesis_id":              syn.get("synthesis_id"),
        "debate_reference":          syn.get("debate_reference"),
        "analyst_recommendation":    ca.get("recommendation"),
        "final_evidence_score":      ca.get("final_evidence_score"),
        "final_confidence_score":    ca.get("final_confidence_score"),
        "debate_outcome":            syn.get("debate_outcome"),
        "overall_risk_assessment":   syn.get("overall_risk_assessment"),
        "philosophy_fit":            ca.get("philosophy_fit"),
        "philosophy_fit_notes":      ca.get("philosophy_fit_notes", ""),
        # Entry-price numbers come from Python (computed_entry); the Chief
        # contributes only the rationale prose. entry_price_rationale uses
        # the Chief's text if present, otherwise the calculator's one-liner.
        "entry_price":               ce.get("entry_price"),
        "entry_range":               ce.get("entry_range"),
        "entry_price_rationale":     ca.get("entry_price_rationale") or ce.get("rationale", ""),
        "current_price_used":        ce.get("current_price_used"),
        "entry_price_case":          ce.get("case_label"),
        "ratio_at_current":          ce.get("ratio_at_current"),
        "price_gate_passed":         ce.get("price_gate_passed"),
        "archetype_min_rr":          ce.get("archetype_min_rr"),
        "target_2to1_price":         ce.get("target_2to1_price"),
        # screening_archetype = Stage 01 screened value; investment_archetype = Chief Analyst's confirmed value
        # Live field names: analyst_recommendation, investment_archetype, final_evidence_score,
        #   final_confidence_score, conviction_1_to_10 (not the shorthand versions of these names)
        "screening_archetype":       syn.get("chief_analyst_brief", {}).get("screening_archetype"),
        "investment_archetype":      ca.get("investment_archetype_confirmed"),
        "executive_summary":         ca.get("executive_summary"),
        "what_would_change_this":    ca.get("what_would_change_this"),
        "blocking_issues":           ca.get("blocking_issues", []),
        "monitoring_priorities":     ca.get("monitoring_priorities", []),

        # Learning hooks — persisted for outcome tracking at 90/180/365 days
        "learning_hooks": _extract_learning_hooks(syn),

        # Investor decision
        "action":                   action,
        "position_size_pct":        position_size_pct,
        "conviction_1_to_10":       conviction,
        "override_recommendation":  override_recommendation,
        "override_reason":          override_reason,
        "notes":                    notes or None,
    }


def _extract_learning_hooks(syn: dict) -> list:
    brief = syn.get("chief_analyst_brief", {})
    bull_hooks = brief.get("bull_position", {}).get("learning_hooks", [])
    bear_hooks = brief.get("bear_position", {}).get("learning_hooks", [])
    return bull_hooks + bear_hooks


# ─────────────────────────────────────────────
# INPUT HELPERS
# ─────────────────────────────────────────────

def _prompt_choice(label: str, options: list, default: str = None) -> str:
    opts_str = " / ".join(
        f"[{o}]" if o == default else o for o in options
    )
    while True:
        raw = input(f"  {label} ({opts_str}): ").strip().lower()
        if not raw and default:
            return default
        if raw in options:
            return raw
        print(f"  Please enter one of: {', '.join(options)}")


def _prompt_float(label: str, min_val: float = None, max_val: float = None) -> float:
    while True:
        raw = input(f"  {label}: ").strip()
        try:
            val = float(raw)
            if min_val is not None and val < min_val:
                print(f"  Minimum is {min_val}")
                continue
            if max_val is not None and val > max_val:
                print(f"  Maximum is {max_val}")
                continue
            return val
        except ValueError:
            print("  Please enter a number.")


def _prompt_int(label: str, min_val: int = None, max_val: int = None) -> int:
    while True:
        raw = input(f"  {label}: ").strip()
        try:
            val = int(raw)
            if min_val is not None and val < min_val:
                print(f"  Minimum is {min_val}")
                continue
            if max_val is not None and val > max_val:
                print(f"  Maximum is {max_val}")
                continue
            return val
        except ValueError:
            print("  Please enter a whole number.")


def _prompt_text(label: str, required: bool = True) -> Optional[str]:
    while True:
        raw = input(f"  {label}: ").strip()
        if raw:
            return raw
        if not required:
            return None
        print("  This field is required.")
