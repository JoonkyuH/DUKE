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
sys.path.insert(0, str(_REPO_ROOT / "pipeline" / "02_research" / "acquisition"))

from scorer import score_packet
from ir_discovery import get_company_name

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

def _normalize(item: dict) -> dict:
    """Return a copy of the evidence item with direction lowercased.
    Stage 02 emits BULLISH/BEARISH/NEUTRAL; evidence_scorer expects lowercase."""
    if isinstance(item.get("direction"), str):
        return {**item, "direction": item["direction"].lower()}
    return item


def _to_risk_factor(item: dict) -> dict:
    """Wrap a filing_quote into the {description, probability, impact} shape
    that _extract_primary_risks() expects."""
    level = _SIG_MAP.get(str(item.get("significance", "")).upper(), "medium")
    return {
        "description": item.get("quote_text", ""),
        "probability": level,
        "impact":      level,
    }


def _build_packet(brief: dict, ticker: str, date: str, screening_entry: dict) -> dict:
    mgmt_items   = [_normalize(i) for i in brief.get("management_quotes", [])]
    filing_items = [_normalize(i) for i in brief.get("filing_quotes", [])]

    risk_factors = [
        _to_risk_factor(item)
        for item in brief.get("filing_quotes", [])
        if item.get("category") == "risk_factors"
    ]

    return {
        "ticker":       ticker,
        "company_name": get_company_name(ticker),
        "packet_id":    f"{ticker}_{date}",
        "evidence_items": mgmt_items + filing_items,
        "contradictions": brief.get("uncertainties", []),
        "catalyst_map":   [],
        "thesis_invalidation_conditions": [],
        "risk_factors":   risk_factors,
        "data_freshness": {},
        "fundamentals":   {},
        "screening_reason_codes": screening_entry.get("reason_codes", []),
        "screening_score":        float(screening_entry.get("composite_score", 0.0)),
        "data_availability": {
            "fundamentals":                   "not_available",
            "catalyst_map":                   "not_available",
            "thesis_invalidation_conditions": "not_available",
            "data_freshness":                 "not_available",
            "screening_score": "available" if screening_entry else "not_available",
        },
    }


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
    print(f"  Evidence Score:   {result.evidence_score:>7.1f}  (net directional balance)")
    print(f"  Confidence Score: {result.confidence_score:>7.1f}  (quality + volume)")
    print()
    print(f"  Conviction:       {result.conviction.value}")
    print(f"  Recommendation:   {result.recommendation.value}")
    print(f"  Position Sizing:  {result.position_sizing.value}")
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
    print("  Fundamentals, catalyst_map, and TICs are")
    print("  placeholders — will be wired in V1.5.")
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
