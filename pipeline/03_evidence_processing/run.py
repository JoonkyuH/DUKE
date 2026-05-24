"""
run.py — CLI entry point for Stage 03 Evidence Refinery.

Usage (run from this directory):
    python3 run.py NVDA
    python3 run.py NVDA --date 20260520   # pin to a specific packet date
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve paths relative to the repo root regardless of CWD
_HERE     = Path(__file__).resolve().parent
_REPO     = _HERE.parent.parent
_RAW_DIR  = _REPO / "data" / "raw"
_OUT_DIR  = _REPO / "data" / "processed"

sys.path.insert(0, str(_HERE))   # so scorer / ranker / refinery import cleanly
sys.path.insert(0, str(_REPO))   # so common.llm is importable from refinery
from refinery import build_analyst_brief


def _find_packet(ticker: str, date_str: str | None = None) -> Path:
    """Return the most-recent evidence packet for ticker, or a specific date."""
    pattern = f"{ticker.upper()}_evidence_*.json"
    matches = sorted(_RAW_DIR.glob(pattern), reverse=True)
    if not matches:
        raise FileNotFoundError(
            f"No evidence packet found for {ticker} in {_RAW_DIR}"
        )
    if date_str:
        target = _RAW_DIR / f"{ticker.upper()}_evidence_{date_str}.json"
        if not target.exists():
            raise FileNotFoundError(f"Packet not found: {target}")
        return target
    return matches[0]


def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_summary(brief: dict, src_path: Path, out_path: Path) -> None:
    ticker  = brief["ticker"]
    cr      = brief["coverage_report"]
    meta    = brief["metadata"]
    ex      = brief.get("metadata", {})

    # All bucket names and their in-brief lengths
    buckets = [
        ("management_quotes",      brief["management_quotes"]),
        ("filing_quotes",          brief["filing_quotes"]),
        ("external_bull_evidence", brief["external_bull_evidence"]),
        ("external_bear_evidence", brief["external_bear_evidence"]),
        ("uncertainties",          brief["uncertainties"]),
        ("source_limitations",     brief["source_limitations"]),
    ]

    # Build excluded counts (available in ranker result but we need to
    # reconstruct from available/in-brief numbers)
    avail = {
        "management_quotes":      cr["management_quotes_available"],
        "filing_quotes":          cr["filing_quotes_available"],
        "external_bull_evidence": cr["external_bull_candidates"],
        "external_bear_evidence": cr["external_bear_candidates"],
        "uncertainties":          len(brief["uncertainties"]),   # already capped
        "source_limitations":     len(brief["source_limitations"]),
    }

    print()
    _print_separator("═")
    print(f"  DUKE Stage 03 — Evidence Refinery  |  {ticker}")
    _print_separator("═")

    print(f"\n  Source:  {src_path.name}")
    print(f"  Period:  {brief['fiscal_period']}")

    print(f"\n{'Coverage Report':─<60}")
    print(f"  Transcript status:     {cr['transcript_status']}")
    print(f"  Has Q&A:               {cr['has_q_and_a']}")
    print(f"  Evidence quality:      {cr['evidence_quality_signal'].upper()}")

    print(f"\n{'Evidence Counts (before → after compression)':─<60}")
    print(f"  {'Bucket':<26}  {'Available':>9}  {'In brief':>8}  {'Excluded':>8}")
    _print_separator()
    total_avail = 0
    total_brief = 0
    for name, kept in buckets:
        a = avail.get(name, len(kept))
        k = len(kept)
        e = max(0, a - k)
        total_avail += a
        total_brief += k
        print(f"  {name:<26}  {a:>9}  {k:>8}  {e:>8}")
    _print_separator()
    print(f"  {'TOTAL':<26}  {total_avail:>9}  {total_brief:>8}  "
          f"{meta['evidence_excluded_by_budget']:>8}")

    # Coverage warnings
    warnings = cr.get("coverage_warnings") or []
    if warnings:
        print(f"\n{'Coverage Warnings':─<60}")
        for w in warnings:
            print(f"  [!] {w}")

    # Sample evidence items
    print(f"\n{'Sample Scored Items':─<60}")
    samples = []
    for bucket_items in [brief["management_quotes"], brief["filing_quotes"]]:
        if bucket_items:
            samples.append(bucket_items[0])
        if len(samples) >= 2:
            break

    for item in samples[:2]:
        score   = item.get("_score", "—")
        iclass  = item.get("item_class", item.get("source_type", "?"))
        text    = (item.get("quote_text") or item.get("snippet") or "")[:80]
        print(f"  [{iclass}]  score={score}")
        print(f"    \"{text}…\"")

    print(f"\n  Output: {out_path}")
    print()


def main(argv: list) -> None:
    if len(argv) < 2:
        print("Usage: python3 run.py TICKER [--date YYYYMMDD]")
        sys.exit(1)

    ticker   = argv[1].upper()
    date_arg = None
    if "--date" in argv:
        idx = argv.index("--date")
        if idx + 1 < len(argv):
            date_arg = argv[idx + 1]

    # ── Load packet ──────────────────────────
    src_path = _find_packet(ticker, date_arg)
    with src_path.open(encoding="utf-8") as f:
        packet = json.load(f)

    # ── Build brief ──────────────────────────
    brief = build_analyst_brief(packet)

    # ── Write output ─────────────────────────
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path  = _OUT_DIR / f"{ticker}_analyst_brief_{today_str}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)

    # ── Terminal summary ─────────────────────
    _print_summary(brief, src_path, out_path)


if __name__ == "__main__":
    main(sys.argv)
