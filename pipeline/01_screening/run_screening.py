#!/usr/bin/env python3
"""
run_screening.py
Stage 01 entry point. Fetches live regime indicators and market data,
runs the screener, and prints a summary table.

Usage:
    python3 run_screening.py NVDA AAPL MSFT
"""

import sys
import concurrent.futures
from datetime import datetime, timezone

sys.path.insert(0, ".")

from regime_fetcher import fetch_regime_indicators
from data_fetcher import fetch_market_data
from screener import run_screening as _screen
from signal_scorer import (
    score_momentum,
    score_relative_strength,
    score_volume_anomaly,
    score_sector_leadership,
    score_news_velocity,
    score_earnings_proximity,
)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

_CONVICTION_TIERS = [(70, "HIGH"), (55, "MEDIUM"), (0, "LOW")]


def _conviction(score: float) -> str:
    for threshold, label in _CONVICTION_TIERS:
        if score >= threshold:
            return label
    return "LOW"


def _score_record(record: dict, weights: dict, sector_data: dict) -> tuple:
    """
    Compute composite score and per-signal scores for a raw record.
    Used for tickers that did not make the shortlist (screener only
    returns passing entries, so we re-score failing ones for display).
    """
    price_d    = record.get("price_data", {})
    rs_d       = record.get("relative_strength", {})
    news_d     = record.get("news_data") or {}
    earnings_d = record.get("earnings_data", {})
    sector_d   = sector_data.get(record.get("sector", ""), {})

    sigs = {
        "momentum":           score_momentum(price_d),
        "relative_strength":  score_relative_strength(rs_d),
        "volume_anomaly":     score_volume_anomaly(price_d),
        "sector_leadership":  score_sector_leadership(rs_d, sector_d),
        "news_velocity":      score_news_velocity(news_d),
        "earnings_proximity": score_earnings_proximity(earnings_d),
    }

    valid   = {k: v for k, v in sigs.items() if v is not None}
    total_w = sum(weights[k] for k in valid)
    comp    = (
        sum(valid[k] * (weights[k] / total_w) for k in valid)
        if total_w > 0 else 0.0
    )

    display = {k: (round(v, 1) if v is not None else None) for k, v in sigs.items()}
    return round(comp, 1), display


def _cell(v) -> str:
    return f"{v:5.1f}" if v is not None else "    —"


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    tickers = [t.upper() for t in sys.argv[1:]]
    if not tickers:
        sys.exit("Usage: python3 run_screening.py TICKER [TICKER ...]")

    # ── 1. Regime indicators + sector ETF RS data ────────────────
    print(f"Fetching regime indicators …")
    regime_indicators, sector_data = fetch_regime_indicators()

    # ── 2. Market data (parallel) ─────────────────────────────────
    print(f"Fetching market data: {', '.join(tickers)} …")
    raw_records = []
    fetch_errors = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_market_data, t): t for t in tickers}
        for fut in concurrent.futures.as_completed(futures):
            ticker = futures[fut]
            try:
                raw_records.append(fut.result())
            except Exception as exc:
                fetch_errors[ticker] = str(exc)

    if not raw_records:
        sys.exit("No market data could be fetched.")

    # ── 3. Screen ─────────────────────────────────────────────────
    result    = _screen(raw_records, regime_indicators, sector_data)
    out       = result.to_dict()
    threshold = out["threshold_applied"]
    weights   = out["metadata"]["regime_weights"]
    shortlist = {e["ticker"]: e for e in out["shortlist"]}

    # ── 4. Build display rows for ALL tickers ─────────────────────
    rows = []
    for rec in raw_records:
        t = rec["ticker"]
        if t in shortlist:
            entry = shortlist[t]
            comp  = entry["composite_score"]
            sigs  = entry["signal_scores"]      # already rounded by screener
            rows.append({
                "ticker":       t,
                "composite":    comp,
                "sigs":         sigs,
                "passed":       True,
                "priority":     entry["priority"],
                "reason_codes": entry["reason_codes"],
                "flags":        entry["flags"],
            })
        else:
            comp, sigs = _score_record(rec, weights, sector_data)
            rows.append({
                "ticker":       t,
                "composite":    comp,
                "sigs":         sigs,
                "passed":       False,
                "priority":     None,
                "reason_codes": [],
                "flags":        [],
            })

    # Sort: passing tickers by priority, then failing by composite desc
    rows.sort(key=lambda r: (0 if r["passed"] else 1, r["priority"] or 999, -r["composite"]))

    # ── 5. Print ──────────────────────────────────────────────────
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M UTC")
    W       = 70
    n_pass  = sum(1 for r in rows if r["passed"])
    n_fail  = len(rows) - n_pass
    regime  = out["market_regime"]
    conf    = f"{out['regime_confidence']:.0%}"
    fallback = out["metadata"].get("fallback_threshold_used", False)

    print()
    print("═" * W)
    print(f"  DUKE  Stage 01 — Screening               {now}")
    print("═" * W)
    print(f"  Regime:    {regime:<26}  Confidence: {conf}")
    print(f"  Threshold: {threshold:<6}  "
          f"Tickers: {len(rows)}   Passed: {n_pass}   Failed: {n_fail}")
    if fallback:
        print("  ⚠  Fallback threshold — universe too small for regime minimum")
    print("═" * W)

    # Summary table
    print()
    hdr = f"  {'TICKER':<8}  {'SCORE':>5}  {'CONVICTION':<10}  {'RESULT':<10}  RANK"
    print(hdr)
    print(f"  {'──────':<8}  {'─────':>5}  {'──────────':<10}  {'──────':<10}  ────")
    for r in rows:
        rank = f"#{r['priority']}" if r["passed"] else ""
        rslt = "✓ PASS" if r["passed"] else "✗ FAIL"
        conv = _conviction(r["composite"]) if r["passed"] else "—"
        print(f"  {r['ticker']:<8}  {r['composite']:>5.1f}  {conv:<10}  {rslt:<10}  {rank}")

    # Signal breakdown
    print()
    print(f"  {'TICKER':<8}  {'MOM':>5}  {'RS':>5}  {'VOL':>5}  {'SEC':>5}  {'NEWS':>5}  {'EARN':>5}")
    print(f"  {'──────':<8}  {'───':>5}  {'──':>5}  {'───':>5}  {'───':>5}  {'────':>5}  {'────':>5}")
    for r in rows:
        s = r["sigs"]
        print(
            f"  {r['ticker']:<8}"
            f"  {_cell(s.get('momentum'))}"
            f"  {_cell(s.get('relative_strength'))}"
            f"  {_cell(s.get('volume_anomaly'))}"
            f"  {_cell(s.get('sector_leadership'))}"
            f"  {_cell(s.get('news_velocity'))}"
            f"  {_cell(s.get('earnings_proximity'))}"
        )

    # Reason codes (passing only)
    if n_pass:
        print()
        print("  Reason Codes:")
        for r in rows:
            if not r["passed"]:
                continue
            codes = ", ".join(r["reason_codes"]) if r["reason_codes"] else "(none)"
            print(f"    {r['ticker']:<8}  {codes}")

    # Flags (passing only, if any exist)
    flagged = [r for r in rows if r["passed"] and r["flags"]]
    if flagged:
        print()
        print("  Flags:")
        for r in flagged:
            print(f"    {r['ticker']:<8}  {', '.join(r['flags'])}")

    # Fetch errors (if any)
    if fetch_errors:
        print()
        print("  Fetch Errors:")
        for t, err in fetch_errors.items():
            print(f"    {t:<8}  {err}")

    print()
    print("═" * W)
    print()


if __name__ == "__main__":
    main()
