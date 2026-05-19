#!/usr/bin/env python3
"""
run.py
Stage 02 — Research & Acquisition entry point.

Usage:
    python3 run.py TICKER SCREENING_ARCHETYPE

    SCREENING_ARCHETYPE: long_term_compounder | quality_compounder | deep_value

Orchestrates the full Stage 02 pipeline:
    1. IR discovery
    2. Transcript acquisition
    3. Quote extraction
    4. Contradiction extraction (vs prior quarter if available)
    5. Deduplication
    6. Evidence validation
    7. Bearish discovery (Perplexity)
    8. News discovery (NewsAPI)
    9. Assemble evidence packet
   10. Write to data/raw/{ticker}_evidence_{YYYYMMDD}.json
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("run")

_STAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _STAGE_DIR.parent.parent

sys.path.insert(0, str(_STAGE_DIR))
sys.path.insert(0, str(_STAGE_DIR / "acquisition"))
sys.path.insert(0, str(_REPO_ROOT))

_OUTPUT_DIR = _REPO_ROOT / "data" / "raw"

_VALID_ARCHETYPES = {"long_term_compounder", "quality_compounder", "deep_value"}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _count_by_category(items: list) -> dict:
    counts: dict = {}
    for item in items:
        cat = item.get("category", "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    return dict(sorted(counts.items()))


def _safe_import(module_path: str, fn_name: str):
    """Import a function from a dotted module path, returning None on failure."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name)
    except Exception as exc:
        log.warning("Could not import %s.%s: %s", module_path, fn_name, exc)
        return None


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: python3 run.py TICKER SCREENING_ARCHETYPE")

    ticker    = sys.argv[1].upper()
    archetype = sys.argv[2].lower()
    if archetype not in _VALID_ARCHETYPES:
        sys.exit(f"Unknown archetype {archetype!r}. Choose from: {', '.join(_VALID_ARCHETYPES)}")

    W = 68
    print()
    print("═" * W)
    print(f"  DUKE  Stage 02 — Research & Acquisition")
    print(f"  Ticker: {ticker}   Archetype: {archetype}")
    print("═" * W)

    # ── 1. IR discovery ───────────────────────────────────────────────
    print("\n[1] IR page discovery …")
    from ir_discovery import get_ir_url, get_company_name
    ir_url       = get_ir_url(ticker)
    company_name = get_company_name(ticker)
    print(f"    company:  {company_name}")
    print(f"    ir_url:   {ir_url or '(not found)'}")

    # ── 2. Transcript acquisition ─────────────────────────────────────
    print("\n[2] Transcript acquisition …")
    from transcript_fetcher import fetch_transcript
    transcript = fetch_transcript(ticker)
    if not transcript:
        print("    ERROR: all transcript sources exhausted — aborting")
        sys.exit(1)
    print(f"    source_type:     {transcript['source_type']}")
    print(f"    document_subtype:{transcript['document_subtype']}")
    print(f"    discovered_by:   {transcript['discovered_by']}")
    print(f"    fiscal:          {transcript['fiscal_year']} {transcript['fiscal_quarter']}")
    print(f"    text length:     {len(transcript['raw_text'])} chars")

    # ── 3. Quote extraction ───────────────────────────────────────────
    print("\n[3] Quote extraction …")
    sys.path.insert(0, str(_STAGE_DIR / "extraction"))
    from quote_extractor import extract_quotes
    quotes = extract_quotes(transcript)
    print(f"    extracted: {len(quotes)} quotes")

    # ── 4. Contradiction extraction ───────────────────────────────────
    print("\n[4] Contradiction extraction …")
    from contradiction_extractor import extract_contradictions
    contradictions = extract_contradictions(ticker, transcript)
    print(f"    found: {len(contradictions)} contradictions/shifts")

    # ── 5. Deduplication ──────────────────────────────────────────────
    print("\n[5] Deduplication …")
    from deduplicate import deduplicate
    before_count = len(quotes)
    quotes       = deduplicate(quotes)
    removed      = before_count - len(quotes)
    print(f"    duplicates removed: {removed}   remaining: {len(quotes)}")

    # ── 6. Evidence validation ────────────────────────────────────────
    print("\n[6] Evidence validation …")
    sys.path.insert(0, str(_STAGE_DIR / "validation"))
    from evidence_validator import validate_evidence
    validated    = validate_evidence(quotes, transcript)
    passed       = len(validated)
    routed       = len(quotes) - passed
    print(f"    passed: {passed}   routed to review queue: {routed}")

    # ── 7. Evidence discovery (Perplexity) ───────────────────────────
    print("\n[7] Evidence discovery (Perplexity) …")
    from perplexity_discovery import discover_evidence
    perplexity_candidates = discover_evidence(ticker, company_name)
    print(f"    candidates: {len(perplexity_candidates)}")

    # ── 8. News discovery (NewsAPI) ───────────────────────────────────
    print("\n[8] News discovery (NewsAPI) …")
    from news_fetcher import fetch_news
    news_candidates = fetch_news(ticker, company_name)
    print(f"    articles: {len(news_candidates)}")

    # ── 9. Assemble evidence packet ───────────────────────────────────
    print("\n[9] Assembling evidence packet …")
    discovery_candidates = perplexity_candidates + news_candidates

    packet = {
        "ticker":              ticker,
        "screening_archetype": archetype,
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "fiscal_year":         transcript["fiscal_year"],
        "fiscal_quarter":      transcript["fiscal_quarter"],
        "calendar_period":     transcript["calendar_period"],
        "transcript": {
            "source_type":      transcript["source_type"],
            "document_subtype": transcript["document_subtype"],
            "source_url":       transcript["source_url"],
            "reliability":      transcript["reliability"],
            "discovered_by":    transcript["discovered_by"],
        },
        "evidence_items":          validated,
        "contradictions":          contradictions,
        "discovery_candidates":    discovery_candidates,
        "metadata": {
            "quotes_extracted":          len(quotes) + removed,
            "duplicates_removed":        removed,
            "quotes_passed_validation":  passed,
            "quotes_routed_to_review":   routed,
            "perplexity_candidates":     len(perplexity_candidates),
            "news_candidates":           len(news_candidates),
            "company_name":              company_name,
            "ir_url":                    ir_url,
        },
    }

    # ── 10. Write output ──────────────────────────────────────────────
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str  = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_path  = _OUTPUT_DIR / f"{ticker}_evidence_{date_str}.json"
    out_path.write_text(json.dumps(packet, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"    written: {out_path.relative_to(_REPO_ROOT)}")

    # ── Summary ───────────────────────────────────────────────────────
    print()
    print("═" * W)
    print(f"  Stage 02 Complete — {ticker}")
    print("═" * W)
    print(f"  Archetype:         {archetype}")
    print(f"  Transcript:        {transcript['source_type']}")
    print(f"  Document subtype:  {transcript['document_subtype']}")
    print(f"  Fiscal period:     {transcript['fiscal_year']} {transcript['fiscal_quarter']}")
    print()
    print("  Quote counts by category:")
    for cat, n in _count_by_category(validated).items():
        print(f"    {cat:<30} {n}")
    if not validated:
        print("    (none — ANTHROPIC_API_KEY required for extraction)")
    print()
    print(f"  Contradictions:    {len(contradictions)}")
    print()
    _QT_ORDER = [
        "bear_case", "bull_case",
        "competitive_risk", "competitive_advantage",
        "sector_risk", "sector_opportunity",
    ]
    pplx_by_qt: dict = {}
    for c in perplexity_candidates:
        qt = c.get("query_type", "unknown")
        pplx_by_qt[qt] = pplx_by_qt.get(qt, 0) + 1
    print(f"  Discovery candidates ({len(perplexity_candidates)} Perplexity"
          f"  +  {len(news_candidates)} news):")
    for qt in _QT_ORDER:
        print(f"    {qt:<26} {pplx_by_qt.get(qt, 0)}")
    if news_candidates:
        print(f"    {'news_discovery':<26} {len(news_candidates)}")
    print()
    print(f"  Output: {out_path.relative_to(_REPO_ROOT)}")
    print("═" * W)
    print()

    return packet


if __name__ == "__main__":
    main()
