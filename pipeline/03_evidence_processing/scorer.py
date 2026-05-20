"""
scorer.py
Deterministic scoring of evidence items and discovery candidates.

Entry points:
    load_weights() -> dict
    build_url_date_map(packet) -> dict
    score_evidence_item(item, weights, contradiction_ids, url_date_map) -> float
    score_discovery_candidate(item, weights) -> float
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_WEIGHTS_PATH = Path(__file__).resolve().parent / "scoring_weights.yaml"

_EXTRACTION_CONFIDENCE_MAP = {"high": 1.0, "medium": 0.7, "low": 0.3}


# ─────────────────────────────────────────────
# WEIGHTS LOADER  (stdlib-only YAML parser)
# ─────────────────────────────────────────────

def load_weights() -> dict:
    """
    Parse scoring_weights.yaml without PyYAML.
    Handles two-level structure: top-level scalar keys and one level of
    nested mapping sections.
    """
    text = _WEIGHTS_PATH.read_text(encoding="utf-8")
    result: dict = {}
    current_section: Optional[str] = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not raw_line[0].isspace():
            m = re.match(r'^([\w]+):\s*(.*)', raw_line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
            if val:
                result[key] = val
                current_section = None
            else:
                current_section = key
                result[key] = {}
        elif current_section is not None:
            m = re.match(r'^\s+([\w]+):\s*(.+)', raw_line)
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
            try:
                result[current_section][key] = float(val)
            except ValueError:
                result[current_section][key] = val

    return result


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def build_url_date_map(packet: dict) -> dict:
    """
    Map source_url → filing_date using the sec_filings block.
    Covers 10-K / 10-Q (single dict) and 8-K (list of dicts).
    """
    url_date: dict = {}
    for ftype, value in (packet.get("sec_filings") or {}).items():
        if isinstance(value, dict):
            url = value.get("doc_url")
            date = value.get("filing_date")
            if url and date:
                url_date[url] = date
        elif isinstance(value, list):
            for item in value:
                url = item.get("doc_url")
                date = item.get("filing_date")
                if url and date:
                    url_date[url] = date
    return url_date


def build_contradiction_ids(contradictions: list) -> set:
    """
    Collect every identifier that references an evidence item inside a
    contradiction.  Supports both Stage-02-style dicts (accession,
    source_url) and Stage-03-processing-style dicts
    (bullish_evidence_id, bearish_evidence_id).
    """
    ids: set = set()
    for c in (contradictions or []):
        for field in ("bullish_evidence_id", "bearish_evidence_id",
                      "evidence_id", "accession", "source_url"):
            v = c.get(field)
            if v:
                ids.add(v)
    return ids


def _recency_score(date_str: Optional[str], today=None) -> float:
    if not date_str:
        return 0.6   # unknown → treat as ~180-day-old
    try:
        if today is None:
            today = datetime.now(timezone.utc).date()
        d = datetime.fromisoformat(date_str).date()
        age = (today - d).days
        if age <= 30:
            return 1.0
        if age <= 90:
            return 0.8
        if age <= 180:
            return 0.6
        return 0.4
    except Exception:
        return 0.6


def _query_type_overlap_score(query_types: list) -> float:
    n = len(query_types or [])
    if n >= 3:
        return 1.0
    if n == 2:
        return 0.75
    return 0.5   # 0 or 1 query type


# ─────────────────────────────────────────────
# SCORING
# ─────────────────────────────────────────────

def score_evidence_item(
    item: dict,
    weights: dict,
    contradiction_ids: set,
    url_date_map: dict,
    today=None,
) -> float:
    """
    Score a management_quote or filing_quote evidence item.

    Formula:
        raw = (reliability * 0.30)
            + (extraction_confidence_score * 0.20)
            + (category_weight * 0.20)
            + (recency_score * 0.15)
            + (query_type_overlap_score * 0.10)   ← always 0.5 for these items
            + (contradiction_bonus * 0.05)
        score = raw * source_priority_multiplier
    """
    category_weights    = weights.get("category_weights") or {}
    source_multipliers  = weights.get("source_priority_multipliers") or {}

    reliability         = float(item.get("reliability") or 0.5)
    extraction_conf     = _EXTRACTION_CONFIDENCE_MAP.get(
                              (item.get("extraction_confidence") or "").lower(), 0.5)
    category_weight     = float(category_weights.get(item.get("category") or "", 0.5))

    # Recency: filing_date on the item itself (10-K/10-Q), else look up via source_url
    date_str = item.get("filing_date") or url_date_map.get(item.get("source_url") or "")
    recency  = _recency_score(date_str, today)

    # filing_quotes and management_quotes carry no query_types → default 0.5
    query_overlap = 0.5

    # Contradiction bonus: match by accession or composite source key
    item_id = item.get("accession") or (
        (item.get("source_url") or "") + str(item.get("source_span") or "")
    )
    contradiction_bonus = 1.0 if item_id in contradiction_ids else 0.0

    raw = (
        reliability          * 0.30
        + extraction_conf    * 0.20
        + category_weight    * 0.20
        + recency            * 0.15
        + query_overlap      * 0.10
        + contradiction_bonus * 0.05
    )

    multiplier = float(
        source_multipliers.get(item.get("source_priority") or "external_discovery", 0.70)
    )
    raw *= multiplier

    # Category confidence discount: only when category was LLM-assigned with low confidence
    if (
        item.get("category_source") == "llm_assigned"
        and float(item.get("category_confidence") or 1.0) < 0.70
    ):
        raw *= 0.85

    return round(raw, 4)


def score_discovery_candidate(
    item: dict,
    weights: dict,
    today=None,
) -> float:
    """
    Score a discovery_candidate.

    Discovery candidates lack extraction_confidence and category, so those
    components use neutral defaults.  query_type_overlap_score IS used because
    candidates explicitly carry query_types.
    """
    source_multipliers = weights.get("source_priority_multipliers") or {}

    reliability         = float(item.get("reliability") or 0.5)
    extraction_conf     = 0.7    # no field → assume medium
    category_weight     = 0.5    # no category → neutral
    recency             = _recency_score(item.get("date"), today)
    query_overlap       = _query_type_overlap_score(item.get("query_types") or [])
    contradiction_bonus = 0.0    # no ID to match against

    raw = (
        reliability          * 0.30
        + extraction_conf    * 0.20
        + category_weight    * 0.20
        + recency            * 0.15
        + query_overlap      * 0.10
        + contradiction_bonus * 0.05
    )

    multiplier = float(
        source_multipliers.get(item.get("source_priority") or "external_discovery", 0.70)
    )
    raw *= multiplier

    return round(raw, 4)
