#!/usr/bin/env python3
"""
run.py
Stage 04 bridge: reads Stage 03 analyst brief + Stage 01 screening output,
builds a scoring packet, calls score_packet(), and writes results to disk.

Usage:
    python3 run.py TICKER
    python3 run.py TICKER --date YYYYMMDD
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── path setup ────────────────────────────────────────────────────────────────
_HERE      = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "pipeline" / "02_research" / "acquisition"))

from scorer import score_packet
from ir_discovery import get_company_name
from common.brief_adapter import build_evidence_packet

# ── directories ───────────────────────────────────────────────────────────────
_PROCESSED_DIR = _REPO_ROOT / "data" / "processed"
_SCREENING_DIR = _REPO_ROOT / "data" / "screening"
_SCORED_DIR    = _REPO_ROOT / "data" / "scored"

# Maps analyst brief significance → risk probability/impact level
_SIG_MAP = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


# ── file discovery ────────────────────────────────────────────────────────────

def _find_brief(ticker: str, date: str | None) -> tuple:
    if date:
        p = _PROCESSED_DIR / f"{ticker}_analyst_brief_{date}.json"
        if not p.exists():
            sys.exit(f"Analyst brief not found: {p}")
        return p, date
    files = sorted(_PROCESSED_DIR.glob(f"{ticker}_analyst_brief_*.json"))
    if not files:
        sys.exit(f"No analyst brief found for {ticker} in {_PROCESSED_DIR}")
    p = files[-1]
    return p, p.stem.split("_")[-1]


def _find_screening_entry(ticker: str, brief_date: str) -> dict:
    """Return the shortlist entry for ticker from the most recent shortlist
    on or before brief_date, or {} if not found."""
    files = sorted(_SCREENING_DIR.glob("shortlist_*.json"))
    if not files:
        return {}
    candidates = [f for f in files if f.stem.split("_")[-1] <= brief_date] or files
    try:
        data = json.loads(candidates[-1].read_text())
        for entry in data.get("tickers", []):
            if entry.get("ticker") == ticker:
                return entry
    except Exception:
        pass
    return {}


# ── packet builder ────────────────────────────────────────────────────────────

def _build_packet(brief: dict, ticker: str, date: str, screening_entry: dict) -> dict:
    company_name = get_company_name(ticker)
    scoring_stub = {
        "ticker":           ticker,
        "company_name":     company_name,
        "packet_reference": f"{ticker}_{date}",
    }
    packet = build_evidence_packet(brief, scoring_stub)

    # Honour significance-based risk probability/impact for filing_quote risk factors.
    # build_evidence_packet defaults both to "medium"; upgrade here using _SIG_MAP.
    for item in brief.get("filing_quotes", []):
        if item.get("category") == "risk_factors":
            level = _SIG_MAP.get(str(item.get("significance", "")).upper(), "medium")
            for rf in packet["risk_factors"]:
                if rf.get("description") == item.get("quote_text", ""):
                    rf["probability"] = level
                    rf["impact"]      = level
                    break

    # Stage 04-specific fields not part of the shared packet
    packet.update({
        "ticker":       ticker,
        "company_name": company_name,
        "packet_id":    f"{ticker}_{date}",
        "data_freshness": {},
        "fundamentals":   {},
        "screening_reason_codes": screening_entry.get("reason_codes", []),
        "screening_score":        float(screening_entry.get("composite_score", 0.0)),
        "data_availability": {
            "fundamentals":                   "not_available",
            "catalyst_map":                   "available" if packet.get("catalyst_map") else "not_available",
            "thesis_invalidation_conditions": "available" if packet.get("thesis_invalidation_conditions") else "not_available",
            "data_freshness":                 "not_available",
            "screening_score":                "available" if screening_entry else "not_available",
        },
    })
    return packet


# ── save ──────────────────────────────────────────────────────────────────────

def _save(result, packet: dict, ticker: str, date: str) -> Path:
    _SCORED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _SCORED_DIR / f"{ticker}_score_{date}.json"
    payload  = result.to_dict()
    payload.update({
        "ticker":               ticker,
        "generated_at":         datetime.now(timezone.utc).isoformat(),
        "analyst_brief_date":   date,
        "screening_score_used": packet["screening_score"],
        "data_availability":    packet["data_availability"],
    })
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


# ── terminal summary ──────────────────────────────────────────────────────────

def _print_summary(result, packet: dict, ticker: str, out_path: Path) -> None:
    da  = packet["data_availability"]
    W   = 52
    sep = "═" * W

    print()
    print(sep)
    print(f"  DUKE Stage 04 — Quantitative Scoring  |  {ticker}")
    print(sep)
    print()
    meta = result.metadata
    sadj = meta.get("screening_adjustment_applied", 0.0)
    print(f"  Raw DTS (pre-screening):  {result.raw_directional_thesis_score:>+7.1f}  (excl. risk disclosures)")
    print(f"  Screening Adjustment:     {sadj:>+7.2f}  ((screening_score−50)×0.30)")
    print(f"  DTS (adjusted):           {result.directional_thesis_score:>+7.1f}  (used for conviction)")
    spec = meta.get("risk_specificity_breakdown", {})
    spec_note = f"  (specific={spec.get('specific',0)} generic={spec.get('generic',0)} untagged={spec.get('untagged',0)})"
    print(f"  Risk Burden Score:        {result.risk_burden_score:>7.1f}{spec_note}")
    print(f"  Evidence Score (=DTS):    {result.evidence_score:>+7.1f}  (backward compat)")
    cb = result.confidence_breakdown
    cov_note = f"  (mgmt quotes: {cb.management_quote_count}, coverage penalty: -{cb.coverage_penalty:.0f})"
    print(f"  Confidence Score:         {result.confidence_score:>7.1f}{cov_note}")
    print()
    ceiling_note = "  [ceiling applied]" if meta.get("conviction_ceiling_applied") else ""
    print(f"  Conviction:       {result.conviction.value}{ceiling_note}")
    print(f"  Recommendation:   {result.recommendation.value}")
    cap_note = ""
    if meta.get("risk_burden_cap_applied"):
        cap_note = f"  [capped from {meta['position_sizing_before_cap']}]"
    elif meta.get("risk_burden_cap_reason"):
        cap_note = "  [noted, no change]"
    print(f"  Position Sizing:  {result.position_sizing.value}{cap_note}")
    print()
    sc    = packet["screening_score"]
    codes = packet["screening_reason_codes"]
    print(f"  Screening Score:  {sc:.1f}  (from Stage 01)")
    print(f"  Reason Codes:     {', '.join(codes) if codes else '(none)'}")
    print()
    if result.primary_risks:
        print("  Primary Risks:")
        for i, r in enumerate(result.primary_risks, 1):
            text = (r[:80] + "…") if len(r) > 80 else r
            print(f"    {i}. {text}")
        print()
    print("  Data Availability:")
    for k, v in da.items():
        print(f"    {k:<34}  {v}")
    print()
    print("  Note: scores reflect evidence balance only.")
    print("  Fundamentals are not yet wired (V1.5).")
    print()
    print(f"  Output: {out_path.relative_to(_REPO_ROOT)}")
    print()
    print(sep)
    print()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        sys.exit("Usage: python3 run.py TICKER [--date YYYYMMDD]")

    ticker = args[0].upper()
    date   = None
    if "--date" in args:
        idx = args.index("--date")
        if idx + 1 < len(args):
            date = args[idx + 1]

    brief_path, brief_date = _find_brief(ticker, date)
    brief           = json.loads(brief_path.read_text())
    screening_entry = _find_screening_entry(ticker, brief_date)
    packet          = _build_packet(brief, ticker, brief_date, screening_entry)
    result          = score_packet(packet)
    out_path        = _save(result, packet, ticker, brief_date)
    _print_summary(result, packet, ticker, out_path)


if __name__ == "__main__":
    main()
