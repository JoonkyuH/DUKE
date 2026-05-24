"""
brief_adapter.py — shared Stage 02 analyst brief → evidence packet adapter.

Used by Stage 04 (scoring) and Stage 05 (debate) to convert the analyst
brief format (management_quotes, filing_quotes, external_bull_evidence,
external_bear_evidence) into a flat evidence_items list with sequential
EV-NNN IDs.

Stage 04 augments the returned dict with extra fields (data_freshness,
fundamentals, screening_reason_codes, screening_score, data_availability).
"""


def build_evidence_packet(brief: dict, scoring: dict) -> dict:
    """
    Convert an analyst brief + scoring dict into an EvidencePacket-compatible dict.

    Args:
        brief:   Stage 02/03 analyst brief (management_quotes, filing_quotes,
                 external_bull_evidence, external_bear_evidence, ...)
        scoring: Stage 04 scoring dict or equivalent; supplies company_name,
                 packet_reference, and ticker fallback.

    Returns:
        dict with keys: ticker, company_name, sector, packet_id,
        investment_archetype, evidence_items, catalyst_map,
        thesis_invalidation_conditions, risk_factors, contradictions,
        screening_flags, summary.
    """
    items: list[dict] = []
    n = 0

    def _next_id() -> str:
        nonlocal n
        n += 1
        return f"EV-{n:03d}"

    for q in brief.get("management_quotes", []):
        items.append({
            "evidence_id":          _next_id(),
            "direction":            q.get("direction", "NEUTRAL").lower(),
            "reliability":          q.get("reliability", 0.70),
            "category":             q.get("category", "guidance"),
            "quote_text":           q.get("quote_text", ""),
            "source_url":           q.get("source_url", ""),
            "filing_date":          q.get("fiscal_quarter", ""),
            "speaker":              q.get("speaker", ""),
            "filing_section_label": q.get("document_subtype", ""),
            "item_class":           "management_quote",
        })

    for q in brief.get("filing_quotes", []):
        items.append({
            "evidence_id":          _next_id(),
            "direction":            q.get("direction", "NEUTRAL").lower(),
            "reliability":          q.get("reliability", 0.85),
            "category":             q.get("category", "filing"),
            "quote_text":           q.get("quote_text", ""),
            "source_url":           q.get("source_url", ""),
            "filing_date":          q.get("filing_date", ""),
            "speaker":              q.get("speaker", ""),
            "filing_section_label": q.get("filing_section", ""),
            "item_class":           "filing_quote",
        })

    for e in brief.get("external_bull_evidence", []):
        items.append({
            "evidence_id":          _next_id(),
            "direction":            "bullish",
            "reliability":          e.get("reliability", 0.60),
            "category":             "external_research",
            "quote_text":           e.get("snippet", e.get("title", "")),
            "source_url":           e.get("url", ""),
            "filing_date":          e.get("date", ""),
            "speaker":              "",
            "filing_section_label": "",
            "item_class":           "external_bull",
        })

    for e in brief.get("external_bear_evidence", []):
        items.append({
            "evidence_id":          _next_id(),
            "direction":            "bearish",
            "reliability":          e.get("reliability", 0.60),
            "category":             "external_research",
            "quote_text":           e.get("snippet", e.get("title", "")),
            "source_url":           e.get("url", ""),
            "filing_date":          e.get("date", ""),
            "speaker":              "",
            "filing_section_label": "",
            "item_class":           "external_bear",
        })

    risk_factors = [
        {
            "description": q.get("quote_text", ""),
            "probability": "medium",
            "impact":      "medium",
        }
        for q in brief.get("filing_quotes", [])
        if q.get("category") == "risk_factors"
    ]

    return {
        "ticker":                         brief.get("ticker", scoring.get("ticker", "")),
        "company_name":                   scoring.get("company_name", ""),
        "sector":                         brief.get("metadata", {}).get("sector", ""),
        "packet_id":                      scoring.get("packet_reference", ""),
        "investment_archetype":           brief.get("screening_archetype", ""),
        "evidence_items":                 items,
        "catalyst_map":                   [],
        "thesis_invalidation_conditions": [],
        "risk_factors":                   risk_factors,
        "contradictions":                 brief.get("uncertainties", []),
        "screening_flags":                [],
        "summary":                        {},
    }
