#!/usr/bin/env python3
"""
run.py
Stage 02 — Research & Acquisition entry point.

Usage:
    python3 run.py TICKER SCREENING_ARCHETYPE

    SCREENING_ARCHETYPE: long_term_compounder | quality_compounder | deep_value

Orchestrates the full Stage 02 pipeline:
    1.  IR discovery
    2.  Transcript acquisition
    2.5 SEC filings acquisition (10-K, 10-Q, 8-Ks)
    3A. Transcript quote extraction
    3B. Filing quote extraction
    3C. Merge raw quotes
    4.  Contradiction extraction (vs prior quarter if available)
    5.  Deduplication
    6.  Evidence validation (against combined transcript + filing text)
    7.  Evidence discovery (Perplexity)
    8.  News discovery (NewsAPI)
    9.  Assemble evidence packet
   10.  Write to data/raw/{ticker}_evidence_{YYYYMMDD}.json
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


def _count_by_class(items: list) -> dict:
    counts: dict = {}
    for item in items:
        cls = item.get("item_class", "unknown")
        counts[cls] = counts.get(cls, 0) + 1
    return counts


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

    # ── 2.5 SEC filings acquisition ───────────────────────────────────
    print("\n[2.5] SEC filings acquisition …")
    sys.path.insert(0, str(_STAGE_DIR / "acquisition"))
    from filings_fetcher import fetch_filings
    filing_passages, filing_metadata = fetch_filings(ticker)
    n_10k_p = filing_metadata.get("10-K", {}).get("passage_count", 0) if filing_metadata.get("10-K") else 0
    n_10q_p = filing_metadata.get("10-Q", {}).get("passage_count", 0) if filing_metadata.get("10-Q") else 0
    n_8k_filings = len(filing_metadata.get("8-K", []))
    n_8k_p  = sum(f.get("passage_count", 0) for f in filing_metadata.get("8-K", []))
    print(f"    10-K passages:   {n_10k_p}")
    print(f"    10-Q passages:   {n_10q_p}")
    print(f"    8-K filings:     {n_8k_filings}  ({n_8k_p} passages)")
    print(f"    total passages:  {len(filing_passages)}")

    # ── 3A. Transcript quote extraction ───────────────────────────────
    print("\n[3A] Transcript quote extraction …")
    sys.path.insert(0, str(_STAGE_DIR / "extraction"))
    from quote_extractor import extract_quotes, extract_filing_quotes
    transcript_quotes = extract_quotes(transcript)
    print(f"    extracted: {len(transcript_quotes)} transcript quotes")

    # ── 3B. Filing quote extraction ────────────────────────────────────
    print("\n[3B] Filing quote extraction …")
    filing_quotes, filing_stats = extract_filing_quotes(filing_passages, ticker)
    print(f"    extracted: {len(filing_quotes)} filing quotes")
    for ft, cnt in sorted(filing_stats.items()):
        print(f"      {ft}: {cnt} passages processed")

    # ── 3C. Merge raw quotes ───────────────────────────────────────────
    print("\n[3C] Merging quotes …")
    raw_quotes = transcript_quotes + filing_quotes
    print(f"    total raw: {len(raw_quotes)} quotes")

    # ── 4. Contradiction extraction ───────────────────────────────────
    print("\n[4] Contradiction extraction …")
    from contradiction_extractor import extract_contradictions
    contradictions = extract_contradictions(ticker, transcript)
    print(f"    found: {len(contradictions)} contradictions/shifts")

    # ── 5. Deduplication ──────────────────────────────────────────────
    print("\n[5] Deduplication …")
    from deduplicate import deduplicate
    before_count = len(raw_quotes)
    quotes       = deduplicate(raw_quotes)
    removed      = before_count - len(quotes)
    print(f"    duplicates removed: {removed}   remaining: {len(quotes)}")

    # ── 6. Evidence validation ────────────────────────────────────────
    print("\n[6] Evidence validation …")
    sys.path.insert(0, str(_STAGE_DIR / "validation"))
    from evidence_validator import validate_evidence
    # Combine transcript + all filing passages for verbatim search
    combined_raw = transcript["raw_text"]
    if filing_passages:
        combined_raw += "\n\n" + "\n\n".join(
            p["passage_text"] for p in filing_passages if p.get("passage_text")
        )
    combined_transcript = {**transcript, "raw_text": combined_raw}
    validated = validate_evidence(quotes, combined_transcript)
    passed    = len(validated)
    routed    = len(quotes) - passed
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
        "sec_filings": {
            "10-K": filing_metadata.get("10-K"),
            "10-Q": filing_metadata.get("10-Q"),
            "8-K":  filing_metadata.get("8-K", []),
        },
        "evidence_items":          validated,
        "contradictions":          contradictions,
        "discovery_candidates":    discovery_candidates,
        "metadata": {
            "quotes_extracted":          len(raw_quotes),
            "duplicates_removed":        removed,
            "quotes_passed_validation":  passed,
            "quotes_routed_to_review":   routed,
            "transcript_quotes":         len(transcript_quotes),
            "filing_quotes":             len(filing_quotes),
            "filing_passages_total":     len(filing_passages),
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

    # SEC filings summary
    print("  SEC Filings:")
    fm_10k = filing_metadata.get("10-K")
    fm_10q = filing_metadata.get("10-Q")
    if fm_10k:
        print(f"    10-K:  {fm_10k['filing_date']}  ({fm_10k['passage_count']} passages)")
    else:
        print(f"    10-K:  (not found)")
    if fm_10q:
        print(f"    10-Q:  {fm_10q['filing_date']}  ({fm_10q['passage_count']} passages)")
    else:
        print(f"    10-Q:  (not found)")
    print(f"    8-K:   {n_8k_filings} post-10-Q earnings filings  ({n_8k_p} passages)")
    print()

    print("  Quote counts by item_class:")
    for cls, n in _count_by_class(validated).items():
        print(f"    {cls:<28} {n}")
    if not validated:
        print("    (none — ANTHROPIC_API_KEY required for extraction)")
    print()

    print("  Quote counts by category:")
    for cat, n in _count_by_category(validated).items():
        print(f"    {cat:<30} {n}")
    if not validated:
        print("    (none)")
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
        qts = c.get("query_types") or [c.get("query_type", "unknown")]
        for qt in qts:
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
