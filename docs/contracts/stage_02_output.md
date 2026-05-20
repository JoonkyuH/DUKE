# Stage 02 Output Contract

**Stage:** 02 Research / Acquisition  
**Entry point:** `pipeline/02_research/acquisition/run.py` → `fetch_and_extract(ticker)`  
**Output file:** `data/raw/{TICKER}_evidence_{YYYYMMDD}.json`

---

## Top-Level Evidence Packet

| Field | Type | Example | Source | Status |
|---|---|---|---|---|
| `ticker` | str | `"NVDA"` | input arg | PRESENT |
| `screening_archetype` | str | `"long_term_compounder"` | passed from Stage 01 or default | PRESENT |
| `fiscal_year` | str | `"FY2026"` | transcript metadata | PRESENT |
| `fiscal_quarter` | str | `"Q1"` | transcript metadata | PRESENT |
| `calendar_period` | str | `"Q1 2026"` | derived | PRESENT |
| `transcript` | dict | see Transcript block | `fetch_transcript()` | PRESENT |
| `sec_filings` | dict | see SEC Filings block | `fetch_filings()` | PRESENT |
| `evidence_items` | list[dict] | see Evidence Item | `extract_quotes()` + `extract_filing_quotes()` | PRESENT |
| `discovery_candidates` | list[dict] | see Discovery Candidate | `fetch_discovery_candidates()` | PRESENT |
| `contradictions` | list[dict] | `[]` | not yet populated by Stage 02 | PLACEHOLDER |
| `packet_id` | str | — | **not produced by Stage 02** | MISSING |
| `company_name` | str | — | **not produced by Stage 02** | MISSING |
| `sector` | str | — | **not produced by Stage 02** | MISSING |
| `catalyst_map` | list | — | **not produced by Stage 02** | MISSING |
| `thesis_invalidation_conditions` | list | — | **not produced by Stage 02** | MISSING |
| `risk_factors` | list | — | **not produced by Stage 02** | MISSING |
| `data_freshness` | dict | — | **not produced by Stage 02** | MISSING |
| `fundamentals` | dict | — | **not produced by Stage 02** | MISSING |
| `screening_score` | float | — | **not produced by Stage 02** | MISSING |
| `screening_reason_codes` | list[str] | — | **not produced by Stage 02** | MISSING |
| `summary` | dict | — | **not produced by Stage 02** | MISSING |
| `screening_flags` | list[str] | — | **not produced by Stage 02** | MISSING |

---

## Transcript Block

| Field | Type | Example | Status |
|---|---|---|---|
| `raw_text` | str | full transcript text | PRESENT |
| `ticker` | str | `"NVDA"` | PRESENT |
| `fiscal_year` | str | `"FY2026"` | PRESENT |
| `fiscal_quarter` | str | `"Q1"` | PRESENT |
| `source_type` | str | `"earnings_call"` | PRESENT |
| `source_url` | str | `"https://..."` | PRESENT |
| `document_subtype` | str | `"earnings_call"` or `"earnings_press_release"` | PRESENT |
| `reliability` | float | `0.90` | PRESENT |
| `has_q_and_a` | bool | `true` | PRESENT |

---

## SEC Filings Block

```json
{
  "10-K": {"accession": "...", "doc_url": "...", "filing_date": "2025-01-20", ...},
  "10-Q": {"accession": "...", "doc_url": "...", "filing_date": "2025-10-15", ...},
  "8-K":  [{"accession": "...", "doc_url": "...", "filing_date": "2025-11-20", ...}]
}
```

10-K and 10-Q are single dicts; 8-K is a list.

---

## Evidence Item (from `evidence_items`)

Produced by `extract_quotes()` (management_quote) and `extract_filing_quotes()` (filing_quote).

| Field | Type | Example | Status |
|---|---|---|---|
| `quote_text` | str | `"We expect revenue of $43–44B..."` | PRESENT |
| `quote_type` | str | `"direct"` | PRESENT |
| `speaker` | str | `"Jensen Huang"` or `"SEC Filing"` | PRESENT |
| `speaker_confidence` | float | `0.95` | PRESENT |
| `category` | str | `"guidance"` | PRESENT |
| `category_confidence` | float | `0.92` | PRESENT |
| `category_source` | str | `"llm_assigned"` | PRESENT |
| `direction` | str | `"BULLISH"` / `"BEARISH"` / `"NEUTRAL"` | PRESENT — **UPPERCASE** |
| `significance` | str | `"HIGH"` / `"MEDIUM"` / `"LOW"` | PRESENT |
| `source_type` | str | `"earnings_call"` | PRESENT |
| `source_url` | str | `"https://..."` | PRESENT |
| `fiscal_year` | str | `"FY2026"` | PRESENT |
| `fiscal_quarter` | str | `"Q1"` | PRESENT |
| `reliability` | float | `0.90` | PRESENT |
| `prompt_name` | str | `"quote_extractor"` | PRESENT |
| `prompt_version` | str | `"1.0.0"` | PRESENT |
| `document_subtype` | str | `"earnings_call"` | PRESENT (management_quote only) |
| `ticker` | str | `"NVDA"` | PRESENT |
| `item_class` | str | `"management_quote"` or `"filing_quote"` | PRESENT |
| `source_priority` | str | `"official_company_material"` or `"primary_sec"` | PRESENT |
| `filing_type` | str | `"10-K"` | PRESENT (filing_quote only) |
| `filing_section` | str | `"item_1a_risk_factors"` | PRESENT (filing_quote only) |
| `filing_section_label` | str | `"Risk Factors"` | PRESENT (filing_quote only) |
| `filing_date` | str | `"2025-01-20"` | PRESENT (filing_quote only) |
| `accession` | str | `"0001045810-25-..."` | PRESENT (filing_quote only) |
| `chunk_index` | int | `-1` (group-level) | PRESENT (filing_quote only) |
| `total_chunks` | int | `4` | PRESENT (filing_quote only) |
| `original_section_length` | int | `42000` | PRESENT (filing_quote only) |
| `chunk_start_char` | int | `0` | PRESENT (filing_quote only) |
| `chunk_end_char` | int | `39800` | PRESENT (filing_quote only) |
| `evidence_id` | str | — | **not produced** — Stage 04/05 expect this | MISSING |
| `content` | str | — | **not produced** — Stage 05 `_format_evidence()` reads this | MISSING |
| `quote` | str | — | **not produced** — Stage 05 `_format_evidence()` reads this | MISSING |
| `date` | str | — | **not produced** — Stage 05 `_format_evidence()` reads this | MISSING |
| `source` | str | — | **not produced** — Stage 05 `_format_evidence()` reads this | MISSING |

> **CRITICAL:** `direction` is UPPERCASE in Stage 02. Stage 04 `evidence_scorer.py` checks for lowercase `"bullish"` / `"bearish"`. All items score as NEUTRAL until this is fixed.

---

## Discovery Candidate (from `discovery_candidates`)

Produced by `fetch_discovery_candidates()` (Perplexity).

| Field | Type | Example | Status |
|---|---|---|---|
| `snippet` | str | `"Analysts note NVDA's data center..."` | PRESENT |
| `source_url` | str | `"https://..."` | PRESENT |
| `source_domain` | str | `"barrons.com"` | PRESENT |
| `query_types` | list[str] | `["bull_case", "competitive_advantage"]` | PRESENT |
| `reliability` | float | `0.65` | PRESENT |
| `published_date` | str | `"2026-05-01"` | PRESENT |
| `title` | str | `"Why NVDA..."` | PRESENT |
