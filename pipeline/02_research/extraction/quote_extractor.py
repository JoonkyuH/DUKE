"""
quote_extractor.py
Extracts attributed executive quotes from earnings documents and SEC filings.

Entry points:
    extract_quotes(transcript: dict) -> list[dict]
        Extracts quotes from a transcript/press release.
        Each item includes item_class="management_quote",
        source_priority="official_company_material".

    extract_filing_quotes(passages: list[dict], ticker: str) -> tuple[list[dict], dict]
        Extracts quotes from SEC filing passages (10-K, 10-Q, 8-K).
        Returns (items, stats) where stats = {filing_type: count}.
        Each item includes item_class="filing_quote",
        source_priority="primary_sec".
"""

import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("quote_extractor")

_REPO_ROOT   = Path(__file__).resolve().parent.parent.parent.parent
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_FILING_SECTION_LABELS: dict = {
    "item_1_business":      "Business",
    "item_1a_risk_factors": "Risk Factors",
    "item_7_mda":           "MD&A",
    "item_7a_market_risk":  "Market Risk",
    "item_2_mda":           "MD&A",
    "item_3_market_risk":   "Market Risk",
    "full_document":        "Earnings Release",
}


def _filing_section_label(section: str) -> str:
    return _FILING_SECTION_LABELS.get(section, section)

sys.path.insert(0, str(_REPO_ROOT))


def _load_prompt(name: str) -> dict:
    """Parse a YAML prompt file without external dependencies."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8")

    name_m    = re.search(r"^name:\s*(.+)$",              content, re.M)
    version_m = re.search(r'^version:\s*"?([^"\n]+)"?',   content, re.M)

    prompt_start = re.search(r"^prompt:\s*\|", content, re.M)
    if not prompt_start:
        raise ValueError(f"No 'prompt: |' block found in {path}")

    after = content[prompt_start.end():]
    if after.startswith("\n"):
        after = after[1:]

    # Stop at next top-level YAML key
    end_m = re.search(r"\n(?=[a-zA-Z])", after)
    if end_m:
        after = after[: end_m.start()]

    lines   = after.split("\n")
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    indent  = min(indents) if indents else 0
    prompt_text = "\n".join(l[indent:] if len(l) > indent else l for l in lines).strip()

    return {
        "name":    name_m.group(1).strip()    if name_m    else name,
        "version": version_m.group(1).strip() if version_m else "1.0.0",
        "prompt":  prompt_text,
    }


def extract_quotes(transcript: dict) -> list:
    """
    Extract structured quotes from a transcript or press release dict.

    Args:
        transcript: dict from fetch_transcript(). Must include raw_text.

    Returns:
        List of evidence item dicts, one per extracted quote.
    """
    from common.llm import get_client

    raw_text         = transcript.get("raw_text", "")
    ticker           = transcript.get("ticker", "UNKNOWN")
    fiscal_year      = transcript.get("fiscal_year", "")
    fiscal_quarter   = transcript.get("fiscal_quarter", "")
    source_type      = transcript.get("source_type", "")
    source_url       = transcript.get("source_url", "")
    reliability      = transcript.get("reliability", 0.75)
    document_subtype = transcript.get("document_subtype", "") or source_type

    if not raw_text:
        log.warning("%s: empty raw_text — nothing to extract", ticker)
        return []

    prompt_def = _load_prompt("quote_extractor")
    period     = f"{fiscal_quarter} {fiscal_year}".strip()

    filled = prompt_def["prompt"].format(
        document_subtype=document_subtype,
        company=ticker,
        period=period,
        text=raw_text[:100_000],
    )

    try:
        client       = get_client("extraction")
        raw_response = client.structured_generate(
            prompt=filled,
            system=(
                "You are a financial analyst extracting verbatim executive quotes. "
                "Return a JSON array and nothing else."
            ),
        )
    except Exception as exc:
        log.error("%s: LLM call failed: %s", ticker, exc)
        return []

    raw_quotes = _unwrap(raw_response, ticker, ("quotes", "items", "results", "data"))
    if raw_quotes is None:
        return []

    items = []
    for q in raw_quotes:
        if not isinstance(q, dict):
            continue
        quote_text = (q.get("quote_text") or "").strip()
        if not quote_text:
            continue
        items.append({
            "quote_text":          quote_text,
            "quote_type":          "direct",
            "speaker":             q.get("speaker") or "Management",
            "speaker_confidence":  float(q.get("speaker_confidence", 0.50)),
            "category":            q.get("category", ""),
            "direction":           q.get("direction", "NEUTRAL"),
            "significance":        q.get("significance", "MEDIUM"),
            "source_type":         source_type,
            "source_url":          source_url,
            "fiscal_year":         fiscal_year,
            "fiscal_quarter":      fiscal_quarter,
            "reliability":         reliability,
            "prompt_name":         prompt_def["name"],
            "prompt_version":      prompt_def["version"],
            "document_subtype":    document_subtype,
            "ticker":              ticker,
            "item_class":          "management_quote",
            "source_priority":     "official_company_material",
            "category_confidence": float(q.get("category_confidence", 0.75)),
            "category_source":     "llm_assigned",
        })

    log.info("%s: extracted %d quotes", ticker, len(items))
    return items


def _unwrap(response, ticker: str, envelope_keys: tuple):
    """Return a list from a raw LLM response (list or dict envelope)."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in envelope_keys:
            if isinstance(response.get(key), list):
                return response[key]
        log.warning("%s: unexpected LLM response keys: %s", ticker, list(response.keys()))
        return None
    log.warning("%s: non-list/dict LLM response", ticker)
    return None


def extract_filing_quotes(passages: list, ticker: str) -> tuple:
    """
    Extract structured quotes from SEC filing passages (10-K, 10-Q, 8-K).

    Passages are batched by (filing_type, section, filing_date) — one LLM
    call per logical section. All chunk metadata from the group is preserved
    on each resulting evidence item so Stage 03 can use it for compression.

    Args:
        passages: list of passage dicts from fetch_filings().
        ticker:   stock ticker for logging.

    Returns:
        (items, stats) where:
            items: list of evidence item dicts with item_class="filing_quote"
            stats: {filing_type: passage_count, "extraction_calls_made": int}
    """
    from common.llm import get_client

    if not passages:
        return [], {}

    prompt_def = _load_prompt("filing_quote_extractor")
    try:
        client = get_client("extraction")
    except Exception as exc:
        log.error("%s: LLM client unavailable: %s", ticker, exc)
        return [], {}

    # Group passages by (filing_type, section, filing_date) — order preserved
    groups: dict = {}
    for p in passages:
        if not p.get("passage_text", "").strip():
            continue
        key = (p.get("filing_type", ""), p.get("section", ""), p.get("filing_date", ""))
        if key not in groups:
            groups[key] = []
        groups[key].append(p)

    all_items:        list = []
    stats:            dict = {}
    extraction_calls        = 0

    for (filing_type, section, filing_date), group in groups.items():
        first       = group[0]
        last        = group[-1]
        doc_url     = first.get("doc_url", "")
        accession   = first.get("accession", "")
        reliability = first.get("reliability", 0.95)
        source_type = first.get("source_type", "")

        # Aggregate chunk metadata across the group
        total_chunks            = first.get("total_chunks", len(group))
        original_section_length = first.get("original_section_length", 0)
        group_start_char        = first.get("chunk_start_char", 0)
        group_end_char          = last.get("chunk_end_char", 0)

        combined_text = "\n\n---\n\n".join(p["passage_text"] for p in group)
        total_chars   = len(combined_text)

        log.info(
            "%s: %s / %s / %s → %d chunks → 1 call (%d chars)",
            ticker, filing_type, section, filing_date, len(group), total_chars,
        )

        filled = prompt_def["prompt"].format(
            filing_type=filing_type,
            section=section,
            company=ticker,
            period=filing_date,
            text=combined_text[:40_000],
        )

        try:
            raw_response = client.structured_generate(
                prompt=filled,
                system=(
                    "You are a financial analyst extracting verbatim statements from SEC filings. "
                    "Return a JSON array and nothing else."
                ),
            )
        except Exception as exc:
            log.warning("%s: LLM call failed for %s %s: %s", ticker, filing_type, section, exc)
            continue

        extraction_calls += 1
        stats[filing_type] = stats.get(filing_type, 0) + len(group)

        raw_quotes = _unwrap(raw_response, ticker, ("quotes", "items", "results", "data"))
        if not raw_quotes:
            continue

        for q in raw_quotes:
            if not isinstance(q, dict):
                continue
            quote_text = (q.get("quote_text") or "").strip()
            if not quote_text:
                continue
            all_items.append({
                "quote_text":               quote_text,
                "quote_type":               "direct",
                "speaker":                  "SEC Filing",
                "speaker_confidence":       1.0,
                "category":                 q.get("category", ""),
                "direction":                q.get("direction", "NEUTRAL"),
                "significance":             q.get("significance", "MEDIUM"),
                "source_type":              source_type,
                "source_url":               doc_url,
                "filing_type":              filing_type,
                "filing_section":           section,
                "filing_date":              filing_date,
                "accession":                accession,
                "reliability":              reliability,
                "prompt_name":              prompt_def["name"],
                "prompt_version":           prompt_def["version"],
                "ticker":                   ticker.upper(),
                "item_class":               "filing_quote",
                "source_priority":          "primary_sec",
                "category_confidence":      float(q.get("category_confidence", 0.75)),
                "category_source":          "llm_assigned",
                "filing_section_label":     _filing_section_label(section),
                "chunk_index":              -1,
                "total_chunks":             total_chunks,
                "original_section_length":  original_section_length,
                "chunk_start_char":         group_start_char,
                "chunk_end_char":           group_end_char,
            })

    stats["extraction_calls_made"] = extraction_calls
    log.info(
        "%s: extract_filing_quotes — %d items from %d calls (%d passages)",
        ticker, len(all_items), extraction_calls, len(passages),
    )
    return all_items, stats
