#!/usr/bin/env python3
"""
run_screening.py
Stage 01 entry point. Fetches live regime indicators, market data, and
EDGAR fundamental data, runs the fundamental screener, and prints results.

Usage:
    python3 run_screening.py NVDA AAPL MSFT
"""

import argparse
import json
import logging
import os
import sys
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeoutError
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from regime_fetcher import fetch_regime_indicators
from data_fetcher import fetch_market_data
from common.edgar_client import fetch_financials
from screener import (
    run_screening as _screen,
    COMPOUNDER_WEIGHTS, QUALITY_COMPOUNDER_WEIGHTS, DEEP_VALUE_WEIGHTS,
)
from signal_scorer import (
    compute_fundamental_metrics,
    score_business_quality,
    score_valuation_vs_growth,
    score_valuation_vs_growth_compounder,
    score_valuation_vs_growth_quality_compounder,
    score_historical_discount,
    score_earnings_quality,
    score_entry_vs_fundamentals,
    score_binary_event_risk,
)
from economic_profile_classifier import classify

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────


def _fetch_sp500_tickers() -> list[str]:
    """Fetch S&P 500 tickers from the EarningsCall SDK."""
    try:
        import earningscall
    except ImportError:
        sys.exit("earningscall SDK not installed — run: pip install earningscall")
    earningscall.api_key = os.environ.get("EARNINGSCALL_API_KEY")
    print("Fetching S&P 500 company list from EarningsCall …")
    companies = list(earningscall.get_sp500_companies())
    tickers = sorted({
        c.company_info.symbol
        for c in companies
        if c.company_info and c.company_info.symbol
    })
    return tickers

_CONVICTION_TIERS = [(70, "HIGH"), (55, "MEDIUM"), (0, "LOW")]


def _conviction(score: float) -> str:
    for threshold, label in _CONVICTION_TIERS:
        if score >= threshold:
            return label
    return "LOW"


def _score_record(record: dict) -> tuple:
    """
    Compute composite score, per-signal scores, and archetype for a raw record.
    Runs both compounder and deep value passes; returns the higher composite.
    """
    ticker     = record.get("ticker", "")
    fund_d     = record.get("fundamental_data", {})
    price_d    = record.get("price_data", {})
    ext_d      = record.get("extended_data", {})
    earnings_d = record.get("earnings_data", {})

    market_d = {
        "market_cap":    ext_d.get("market_cap"),
        "current_price": price_d.get("current_price"),
        "week_52_high":  ext_d.get("week_52_high"),
        "week_52_low":   ext_d.get("week_52_low"),
    }

    classification   = classify(ticker)
    economic_profile = classification["economic_profile"]
    if fund_d:
        metrics = compute_fundamental_metrics(
            fund_d, market_d, economic_profile=economic_profile
        )
        if classification["classification_method"] == "unknown":
            classification = classify(ticker, metrics)
            economic_profile = classification["economic_profile"]
            metrics["economic_profile"] = economic_profile
    else:
        metrics = {}

    # Store classification on record so the main loop can display it
    record["classification"] = classification

    bq = score_business_quality(metrics)
    hd = score_historical_discount(metrics)
    eq = score_earnings_quality(metrics)
    ef = score_entry_vs_fundamentals(metrics)
    br = score_binary_event_risk(earnings_d)

    vg_dv    = score_valuation_vs_growth(metrics)
    vg_comp  = score_valuation_vs_growth_compounder(metrics)
    vg_qcomp = score_valuation_vs_growth_quality_compounder(metrics)

    def _composite(sigs: dict, weights: dict) -> float:
        valid   = {k: v for k, v in sigs.items() if v is not None}
        total_w = sum(weights[k] for k in valid)
        return sum(valid[k] * (weights[k] / total_w) for k in valid) if total_w > 0 else 0.0

    def _sigs(vg):
        return {
            "business_quality": bq, "valuation_vs_growth": vg,
            "historical_discount": hd, "earnings_quality": eq,
            "entry_vs_fundamentals": ef, "binary_event_risk": br,
        }

    sigs_dv    = _sigs(vg_dv)
    sigs_comp  = _sigs(vg_comp)
    sigs_qcomp = _sigs(vg_qcomp)

    candidates = sorted([
        (_composite(sigs_comp,  COMPOUNDER_WEIGHTS),          "long_term_compounder", sigs_comp),
        (_composite(sigs_qcomp, QUALITY_COMPOUNDER_WEIGHTS),  "quality_compounder",   sigs_qcomp),
        (_composite(sigs_dv,    DEEP_VALUE_WEIGHTS),          "deep_value",           sigs_dv),
    ], key=lambda x: x[0], reverse=True)

    top_score, top_arch, top_sigs = candidates[0]
    archetype = "either" if (top_score - candidates[1][0]) <= 1.0 else top_arch

    display = {k: (round(v, 1) if v is not None else None) for k, v in top_sigs.items()}
    return round(top_score, 1), display, archetype


def _cell(v) -> str:
    return f"{v:5.1f}" if v is not None else "    —"


def _save_output(rows: list, out: dict, universe_size: int, raw_records: list) -> Path:
    repo_root = Path(__file__).resolve().parent.parent.parent
    out_dir = repo_root / "data" / "screening"
    out_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path = out_dir / f"shortlist_{today}.json"

    # Build a lookup for raw records so Fix 4 can write per-ticker price data
    raw_by_ticker = {rec["ticker"]: rec for rec in raw_records}

    passing = [r for r in rows if r["passed"]]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": universe_size,
        "shortlist_size": len(passing),
        "regime": out["market_regime"],
        "tickers": [
            {
                "ticker": r["ticker"],
                "archetype": r["archetype"],
                "composite_score": r["composite"],
                "conviction": _conviction(r["composite"]),
                "reason_codes": r["reason_codes"],
                "flags": r["flags"],
                "rank": r["priority"],
                "signal_scores": r["sigs"],
            }
            for r in passing
        ],
    }

    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)

    # Write per-ticker raw price/extended data for Stage 06 technical context
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for r in passing:
        ticker = r["ticker"]
        rec = raw_by_ticker.get(ticker, {})
        ticker_raw = {
            "ticker":        ticker,
            "price_data":    rec.get("price_data") or {},
            "extended_data": rec.get("extended_data") or {},
        }
        raw_path = raw_dir / f"{ticker}_{today}.json"
        with open(raw_path, "w") as f:
            json.dump(ticker_raw, f, indent=2)

    return out_path


def _fetch_ticker_data(ticker: str) -> dict:
    """
    Fetch market data and EDGAR fundamentals for one ticker.
    Returns the merged record. Raises on market data failure.
    EDGAR failure is non-fatal — record is returned with empty fundamental_data.
    """
    record = fetch_market_data(ticker)
    try:
        record["fundamental_data"] = fetch_financials(ticker)
    except Exception as exc:
        log.warning("%s: EDGAR fetch failed: %s", ticker, exc)
        record["fundamental_data"] = {}
    return record


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DUKE Stage 01 Fundamental Screening")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols to screen")
    parser.add_argument(
        "--universe", choices=["sp500"],
        help="Screen a predefined universe",
    )
    args = parser.parse_args()

    if args.universe == "sp500":
        tickers = _fetch_sp500_tickers()
        universe_label = "S&P 500"
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
        universe_label = "custom"
    else:
        parser.print_help()
        sys.exit(1)

    print(f"Universe: {len(tickers)} tickers ({universe_label})")

    # ── 1. Regime indicators + sector ETF RS data ────────────────
    print("Fetching regime indicators …")
    regime_indicators, sector_data = fetch_regime_indicators()

    # ── 2+3. Market data + EDGAR (sequential, 30s per-ticker timeout) ──
    print(f"Fetching data for {len(tickers)} tickers …")
    raw_records = []
    fetch_errors = {}

    for i, t in enumerate(tickers):
        if i > 0:
            time.sleep(0.5)
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_fetch_ticker_data, t)
            try:
                raw_records.append(future.result(timeout=30))
            except _FuturesTimeoutError:
                log.warning("%s: data fetch timed out after 30s — skipping", t)
                fetch_errors[t] = "timed out after 30s"
            except Exception as exc:
                log.warning("%s: data fetch failed: %s — skipping", t, exc)
                fetch_errors[t] = str(exc)

    if not raw_records:
        sys.exit("No market data could be fetched.")

    # ── 4. Screen ─────────────────────────────────────────────────
    result    = _screen(raw_records, regime_indicators, sector_data)
    out       = result.to_dict()
    threshold = out["threshold_applied"]
    shortlist = {e["ticker"]: e for e in out["shortlist"]}

    # ── 5. Build display rows for ALL tickers ─────────────────────
    rows = []
    for rec in raw_records:
        t = rec["ticker"]
        if t in shortlist:
            entry = shortlist[t]
            comp  = entry["composite_score"]
            sigs  = entry["signal_scores"]
            rows.append({
                "ticker":         t,
                "composite":      comp,
                "sigs":           sigs,
                "passed":         True,
                "priority":       entry["priority"],
                "archetype":      entry["screening_archetype"],
                "classification": entry.get("classification", {}),
                "reason_codes":   entry["reason_codes"],
                "flags":          entry["flags"],
                "hypothesis":     entry["mispricing_hypothesis"],
                "sector_name":    rec.get("sector_name", "Unknown"),
                "industry":       rec.get("industry", "Unknown"),
            })
        else:
            comp, sigs, archetype = _score_record(rec)
            rows.append({
                "ticker":         t,
                "composite":      comp,
                "sigs":           sigs,
                "passed":         False,
                "priority":       None,
                "archetype":      archetype,
                "classification": rec.get("classification", {}),
                "reason_codes":   [],
                "flags":          [],
                "hypothesis":     "",
                "sector_name":    rec.get("sector_name", "Unknown"),
                "industry":       rec.get("industry", "Unknown"),
            })

    # Sort: passing tickers by priority, then failing by composite desc
    rows.sort(key=lambda r: (0 if r["passed"] else 1, r["priority"] or 999, -r["composite"]))

    # ── 6. Print ──────────────────────────────────────────────────
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M UTC")
    W        = 72
    n_pass   = sum(1 for r in rows if r["passed"])
    n_fail   = len(rows) - n_pass
    regime   = out["market_regime"]
    conf     = f"{out['regime_confidence']:.0%}"
    fallback = out["metadata"].get("fallback_threshold_used", False)

    print()
    print("═" * W)
    print(f"  DUKE  Stage 01 — Fundamental Screening       {now}")
    print("═" * W)
    print(f"  Regime:    {regime:<26}  Confidence: {conf}")
    print(f"  Threshold: {threshold:<6}  "
          f"Tickers: {len(rows)}   Passed: {n_pass}   Failed: {n_fail}")
    if fallback:
        print("  ⚠  Fallback threshold — universe too small for regime minimum")
    print("═" * W)

    _ARCH_ABBREV = {
        "long_term_compounder": "LT COMPOUNDER",
        "quality_compounder":   "QUALITY COMP",
        "deep_value":           "DEEP VALUE",
        "either":               "EITHER",
    }

    # Summary table
    print()
    hdr = f"  {'TICKER':<8}  {'SCORE':>5}  {'CONVICTION':<10}  {'RESULT':<10}  {'RANK':<6}  ARCHETYPE"
    print(hdr)
    print(f"  {'──────':<8}  {'─────':>5}  {'──────────':<10}  {'──────':<10}  {'────':<6}  ─────────")
    for r in rows:
        rank  = f"#{r['priority']}" if r["passed"] else ""
        rslt  = "✓ PASS" if r["passed"] else "✗ FAIL"
        conv  = _conviction(r["composite"]) if r["passed"] else "—"
        arch  = _ARCH_ABBREV.get(r["archetype"], r["archetype"]) if r["passed"] else ""
        print(f"  {r['ticker']:<8}  {r['composite']:>5.1f}  {conv:<10}  {rslt:<10}  {rank:<6}  {arch}")

    # Signal breakdown
    print()
    print(f"  {'TICKER':<8}  {'BQ':>5}  {'VG':>5}  {'HD':>5}  {'EQ':>5}  {'EF':>5}  {'BR':>5}")
    print(f"  {'──────':<8}  {'──':>5}  {'──':>5}  {'──':>5}  {'──':>5}  {'──':>5}  {'──':>5}")
    for r in rows:
        s = r["sigs"]
        print(
            f"  {r['ticker']:<8}"
            f"  {_cell(s.get('business_quality'))}"
            f"  {_cell(s.get('valuation_vs_growth'))}"
            f"  {_cell(s.get('historical_discount'))}"
            f"  {_cell(s.get('earnings_quality'))}"
            f"  {_cell(s.get('entry_vs_fundamentals'))}"
            f"  {_cell(s.get('binary_event_risk'))}"
        )
    print("  (BQ=Business Quality  VG=Valuation vs Growth  HD=Historical Discount")
    print("   EQ=Earnings Quality  EF=Entry vs Fundamentals  BR=Binary Event Risk)")

    # Economic profile classification audit
    print()
    print(f"  {'TICKER':<8}  {'PROFILE':<30}  {'METHOD':<20}  {'CONF':>5}")
    print(f"  {'──────':<8}  {'───────':<30}  {'──────':<20}  {'────':>5}")
    for r in rows:
        clf    = r.get("classification", {})
        pname  = clf.get("economic_profile", "—")[:30]
        method = clf.get("classification_method", "—")[:20]
        conf   = clf.get("classification_confidence")
        cstr   = f"{conf:.0%}" if conf is not None else "   —"
        print(f"  {r['ticker']:<8}  {pname:<30}  {method:<20}  {cstr:>5}")

    # Reason codes (passing only)
    if n_pass:
        print()
        print("  Reason Codes:")
        for r in rows:
            if not r["passed"]:
                continue
            codes = ", ".join(r["reason_codes"]) if r["reason_codes"] else "(none)"
            print(f"    {r['ticker']:<8}  {codes}")

    # Flags (passing only, if any)
    flagged = [r for r in rows if r["passed"] and r["flags"]]
    if flagged:
        print()
        print("  Flags:")
        for r in flagged:
            print(f"    {r['ticker']:<8}  {', '.join(r['flags'])}")

    # Mispricing hypotheses (passing tickers, for Stage 02 research brief)
    if n_pass:
        print()
        print("  Mispricing Hypotheses (Stage 02 Research Brief):")
        for r in rows:
            if not r["passed"] or not r["hypothesis"]:
                continue
            clf      = r.get("classification", {})
            profile  = clf.get("economic_profile", "unknown")
            method   = clf.get("classification_method", "unknown")
            conf     = clf.get("classification_confidence", 0.0)
            sector_n = r.get("sector_name", "Unknown")
            industry = r.get("industry", "Unknown")
            print(f"\n    [{r['ticker']}]")
            print(f"    Sector: {sector_n} / {industry}")
            print(f"    Economic profile: {profile}  ({method}, confidence {conf:.0%})")
            # Word-wrap at ~70 chars
            words = r["hypothesis"].split()
            line = "    "
            for word in words:
                if len(line) + len(word) + 1 > 74:
                    print(line)
                    line = "      " + word
                else:
                    line += (" " if line.strip() else "") + word
            if line.strip():
                print(line)

    # Fetch errors
    all_errors = fetch_errors
    if all_errors:
        print()
        print("  Fetch Errors:")
        for t, err in all_errors.items():
            print(f"    {t:<8}  {err}")

    # Save shortlist to disk
    saved_path = _save_output(rows, out, len(tickers), raw_records)
    print()
    print(f"  Saved → {saved_path}")

    # ── Transcript prefetch ───────────────────────────────────────
    try:
        import sys as _sys
        _sys.path.insert(0, str(
            Path(__file__).resolve().parent.parent /
            "02_research" / "acquisition"
        ))
        from earningscall_fetcher import fetch_earningscall_transcript
        from transcript_fetcher import (
            _cache_transcript,
            _read_transcript_cache,
            _is_transcript_stale,
        )
        from ir_discovery import get_company_name

        print()
        print("  [Transcript prefetch]")
        prefetched = skipped = failed = 0
        for i, rec in enumerate(raw_records):
            t = rec.get("ticker", "")
            if not t:
                continue
            if i > 0 and i % 50 == 0:
                print(
                    f"    [{i}/{len(raw_records)}] "
                    f"prefetched={prefetched} "
                    f"skipped={skipped} "
                    f"failed={failed}"
                )
            try:
                cached = _read_transcript_cache(t)
                if cached and not _is_transcript_stale(cached):
                    skipped += 1
                    continue
                cn = get_company_name(t)
                result = fetch_earningscall_transcript(t, cn)
                if result:
                    _cache_transcript(t, result)
                    prefetched += 1
                else:
                    failed += 1
            except Exception as exc:
                log.warning("%s: prefetch failed: %s", t, exc)
                failed += 1
        print(
            f"    Prefetched: {prefetched}  "
            f"Skipped (fresh): {skipped}  "
            f"Failed/no coverage: {failed}"
        )
        try:
            import sqlite3
            db_path = (
                Path(__file__).resolve().parent.parent
                / "02_research" / "acquisition" / "cache" / "duke_cache.db"
            )
            conn = sqlite3.connect(db_path)
            cached_total = conn.execute(
                "SELECT COUNT(*) FROM transcript_cache"
            ).fetchone()[0]
            earningscall_cached = conn.execute(
                "SELECT COUNT(*) FROM transcript_cache "
                "WHERE source_type='earningscall_api'"
            ).fetchone()[0]
            conn.close()
            print(
                f"  Cache state: {cached_total} total transcripts "
                f"({earningscall_cached} from EarningsCall API)"
            )
        except Exception:
            pass
    except Exception as exc:
        log.warning("Transcript prefetch error: %s", exc)

    print()
    print("═" * W)
    print()


if __name__ == "__main__":
    main()
