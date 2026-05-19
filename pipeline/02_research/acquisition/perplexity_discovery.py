"""
perplexity_discovery.py
Perplexity Sonar search utilities for the DUKE acquisition layer.

Entry points:
    perplexity_search(query: str) -> list[dict]
        General-purpose search. Parses search_results array only.
        Returns list of {url, title, date, snippet}.

    discover_bearish(ticker: str, company_name: str) -> list[dict]
        Runs three bearish-evidence queries, caches results in
        discovery_cache, and returns discovery candidates.
"""

import hashlib
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("perplexity_discovery")

_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
_DB_PATH        = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

_BEARISH_QUERIES = [
    "bearish arguments against {ticker} {company_name} last 60 days",
    "analyst downgrade price target cut {ticker} last 30 days",
    "competitive threat {company_name} recent news",
]


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _cache_write(ticker: str, query_type: str, result: dict) -> None:
    url   = result.get("url", "")
    key   = hashlib.sha256(f"{ticker}:{query_type}:{url}".encode()).hexdigest()[:16]
    now   = datetime.now(timezone.utc).isoformat()
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
    Choices.message.content is intentionally ignored.
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


def discover_bearish(ticker: str, company_name: str) -> list:
    """
    Run three bearish-evidence queries against Perplexity Sonar.
    Cache each result row in discovery_cache.

    Args:
        ticker:       Stock ticker (e.g. "NVDA").
        company_name: Full company name (e.g. "Nvidia Corp").

    Returns:
        List of discovery candidate dicts with source_type and reliability.
        Empty list if PERPLEXITY_API_KEY is not set.
    """
    if not os.environ.get("PERPLEXITY_API_KEY", "").strip():
        log.info("PERPLEXITY_API_KEY not set — skipping bearish discovery for %s", ticker)
        return []

    candidates = []
    for tmpl in _BEARISH_QUERIES:
        query      = tmpl.format(ticker=ticker.upper(), company_name=company_name)
        query_type = tmpl.split()[0][:20]   # short label for the cache row
        log.info("%s: bearish discovery query: %r", ticker, query[:80])

        for raw in _call_perplexity(query):
            if not raw.get("url"):
                continue
            result = _parse_result(raw)
            _cache_write(ticker, query_type, result)
            candidates.append({
                **result,
                "source_type": "discovery_candidate",
                "reliability": 0.55,
            })

    seen_urls = set()
    deduped   = []
    for c in candidates:
        if c["url"] not in seen_urls:
            seen_urls.add(c["url"])
            deduped.append(c)

    log.info("%s: bearish discovery → %d candidates (%d unique)",
             ticker, len(candidates), len(deduped))
    return deduped
