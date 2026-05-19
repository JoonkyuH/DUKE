"""
perplexity_discovery.py
Perplexity Sonar search utilities for the DUKE acquisition layer.

Entry points:
    perplexity_search(query: str) -> list[dict]
        General-purpose search. Parses search_results array only.
        Returns list of {url, title, date, snippet}.

    discover_evidence(ticker: str, company_name: str) -> list[dict]
        Runs six symmetric queries (bull + bear on case, competitive,
        and sector dimensions), caches results in discovery_cache, and
        returns discovery candidates tagged with query_type.
"""

import hashlib
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("perplexity_discovery")

_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
_DB_PATH        = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

# Six symmetric evidence queries: (query_type_label, query_template)
_EVIDENCE_QUERIES = [
    (
        "bear_case",
        "bearish arguments concerns risks against {ticker} {company_name} last 60 days",
    ),
    (
        "bull_case",
        "bull thesis positive developments upgrades for {ticker} {company_name} last 60 days",
    ),
    (
        "competitive_risk",
        "competitive threat competitor challenge {company_name} recent news",
    ),
    (
        "competitive_advantage",
        "competitive moat differentiation advantage {company_name}",
    ),
    (
        "sector_risk",
        "industry headwinds regulation demand weakness {company_name} industry 2026",
    ),
    (
        "sector_opportunity",
        "industry tailwinds growth opportunity {company_name} industry 2026",
    ),
]


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema() -> None:
    """Add query_type column to discovery_cache if it does not already exist."""
    with _db() as con:
        try:
            con.execute("ALTER TABLE discovery_cache ADD COLUMN query_type TEXT")
        except sqlite3.OperationalError:
            pass  # column already present


def _cache_write(ticker: str, query_type: str, result: dict) -> None:
    url = result.get("url", "")
    key = hashlib.sha256(f"{ticker}:{query_type}:{url}".encode()).hexdigest()[:16]
    now = datetime.now(timezone.utc).isoformat()
    with _db() as con:
        con.execute(
            """INSERT OR REPLACE INTO discovery_cache
               (id, ticker, query_type, url, title, date, snippet, fetched_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (key, ticker.upper(), query_type,
             url, result.get("title", ""), result.get("date", ""),
             result.get("snippet", ""), now),
        )


# ─────────────────────────────────────────────
# PERPLEXITY API
# ─────────────────────────────────────────────

def _call_perplexity(query: str) -> list:
    """
    POST one query to Perplexity Sonar.
    Returns the raw search_results list, or [] on any failure.
    choices.message.content is intentionally ignored.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return []

    payload = json.dumps({
        "model":    "sonar",
        "messages": [{"role": "user", "content": query}],
    }).encode()

    req = urllib.request.Request(
        _PERPLEXITY_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as exc:
        log.warning("Perplexity request failed: %s", exc)
        return []

    return data.get("search_results") or []


def _parse_result(raw: dict) -> dict:
    """Normalise a single search_results entry."""
    return {
        "url":     (raw.get("url") or "").strip(),
        "title":   (raw.get("name") or raw.get("title") or "").strip(),
        "date":    (raw.get("date") or raw.get("published_date") or "").strip(),
        "snippet": (raw.get("snippet") or "").strip(),
    }


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINTS
# ─────────────────────────────────────────────

def perplexity_search(query: str) -> list:
    """
    General-purpose Perplexity search.

    Args:
        query: Natural-language search string.

    Returns:
        List of {url, title, date, snippet} dicts.
        Empty list if PERPLEXITY_API_KEY is not set or the request fails.
    """
    if not os.environ.get("PERPLEXITY_API_KEY", "").strip():
        log.debug("PERPLEXITY_API_KEY not set — skipping search")
        return []

    raw_results = _call_perplexity(query)
    parsed = [_parse_result(r) for r in raw_results if r.get("url")]
    log.debug("perplexity_search: query=%r → %d results", query[:60], len(parsed))
    return parsed


def discover_evidence(ticker: str, company_name: str) -> list:
    """
    Run six symmetric evidence queries (bull/bear across case, competitive,
    and sector dimensions) against Perplexity Sonar.
    Cache each result row in discovery_cache.

    Args:
        ticker:       Stock ticker (e.g. "NVDA").
        company_name: Full company name (e.g. "Nvidia Corp").

    Returns:
        List of discovery candidate dicts with query_type, source_type, and
        reliability. Empty list if PERPLEXITY_API_KEY is not set.
    """
    if not os.environ.get("PERPLEXITY_API_KEY", "").strip():
        log.info("PERPLEXITY_API_KEY not set — skipping evidence discovery for %s", ticker)
        return []

    _ensure_schema()

    # Keyed by URL so duplicate URLs across queries accumulate query_types
    by_url: dict = {}

    for query_type, tmpl in _EVIDENCE_QUERIES:
        query = tmpl.format(ticker=ticker.upper(), company_name=company_name)
        log.info("%s: [%s] query: %r", ticker, query_type, query[:80])

        raw_results = _call_perplexity(query)
        new_count = 0
        merged_count = 0

        for raw in raw_results:
            if not raw.get("url"):
                continue
            result = _parse_result(raw)
            url    = result["url"]
            _cache_write(ticker, query_type, result)

            if url not in by_url:
                by_url[url] = {
                    **result,
                    "query_types": [query_type],
                    "source_type": "discovery_candidate",
                    "reliability": 0.55,
                }
                new_count += 1
            else:
                if query_type not in by_url[url]["query_types"]:
                    by_url[url]["query_types"].append(query_type)
                    log.debug("%s: merged %s into existing candidate %s", ticker, query_type, url)
                merged_count += 1

        log.info("%s: [%s] → %d new, %d merged into existing", ticker, query_type, new_count, merged_count)

    candidates = list(by_url.values())

    # Update cache rows with the full comma-separated query_types for each URL
    with _db() as con:
        for c in candidates:
            if len(c["query_types"]) > 1:
                con.execute(
                    "UPDATE discovery_cache SET query_type=? WHERE ticker=? AND url=?",
                    (",".join(c["query_types"]), ticker.upper(), c["url"]),
                )

    log.info("%s: evidence discovery complete — %d unique candidates", ticker, len(candidates))
    return candidates
