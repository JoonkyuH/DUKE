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
        returns discovery candidates tagged with query_types.

discovery_cache schema (v2):
    PRIMARY KEY (ticker, url)   — one row per URL per ticker
    query_types TEXT            — comma-separated, merged across queries
"""

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


def _migrate_schema() -> None:
    """
    Migrate discovery_cache from hash-PK schema to (ticker, url) composite PK.
    Idempotent — safe to call on both old and already-migrated schema.

    Old schema: id TEXT PRIMARY KEY, query_type TEXT (single value)
    New schema: PRIMARY KEY (ticker, url), query_types TEXT (comma-joined)
    """
    with _db() as con:
        cols = {row[1] for row in con.execute("PRAGMA table_info(discovery_cache)")}
        if "id" not in cols:
            return  # already on new schema

        log.info("Migrating discovery_cache → v2 (ticker+url PK) …")

        con.execute("""
            CREATE TABLE IF NOT EXISTS discovery_cache_v2 (
                ticker      TEXT NOT NULL,
                url         TEXT NOT NULL,
                title       TEXT,
                date        TEXT,
                snippet     TEXT,
                query_types TEXT,
                fetched_at  TEXT,
                PRIMARY KEY (ticker, url)
            )
        """)

        # Read all old rows; query_type may already be comma-joined from
        # the prior UPDATE block in discover_evidence()
        rows = con.execute(
            "SELECT ticker, url, title, date, snippet, query_type, fetched_at "
            "FROM discovery_cache ORDER BY ticker, url, fetched_at"
        ).fetchall()

        merged: dict = {}
        for row in rows:
            key = (row["ticker"], row["url"])
            if key not in merged:
                merged[key] = {
                    "ticker":      row["ticker"],
                    "url":         row["url"],
                    "title":       row["title"] or "",
                    "date":        row["date"] or "",
                    "snippet":     row["snippet"] or "",
                    "query_types": [],
                    "fetched_at":  row["fetched_at"] or "",
                }
            # Expand comma-joined values from old UPDATE-merged rows
            for part in (row["query_type"] or "").split(","):
                part = part.strip()
                if part and part not in merged[key]["query_types"]:
                    merged[key]["query_types"].append(part)

        for m in merged.values():
            con.execute(
                """INSERT OR REPLACE INTO discovery_cache_v2
                   (ticker, url, title, date, snippet, query_types, fetched_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (m["ticker"], m["url"], m["title"], m["date"],
                 m["snippet"], ",".join(m["query_types"]), m["fetched_at"]),
            )

        con.execute("DROP TABLE discovery_cache")
        con.execute("ALTER TABLE discovery_cache_v2 RENAME TO discovery_cache")
        log.info("Migration complete — %d rows", len(merged))


def _cache_write(ticker: str, query_type: str, result: dict) -> None:
    """
    Upsert one discovery result into discovery_cache.
    (ticker, url) is the canonical key. query_type is merged into the
    comma-separated query_types field; duplicates are never written.
    """
    url = result.get("url", "")
    if not url:
        return
    now = datetime.now(timezone.utc).isoformat()
    t   = ticker.upper()

    with _db() as con:
        # Insert row if it doesn't exist yet
        con.execute(
            """INSERT OR IGNORE INTO discovery_cache
               (ticker, url, title, date, snippet, query_types, fetched_at)
               VALUES (?,?,?,?,?,?,?)""",
            (t, url, result.get("title", ""), result.get("date", ""),
             result.get("snippet", ""), query_type, now),
        )
        # Read back and merge query_type if the row already existed
        row = con.execute(
            "SELECT query_types FROM discovery_cache WHERE ticker=? AND url=?",
            (t, url),
        ).fetchone()
        existing = [qt.strip() for qt in (row["query_types"] or "").split(",") if qt.strip()]
        if query_type not in existing:
            existing.append(query_type)
            con.execute(
                "UPDATE discovery_cache SET query_types=?, fetched_at=? "
                "WHERE ticker=? AND url=?",
                (",".join(existing), now, t, url),
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
        List of discovery candidate dicts with query_types, source_type, and
        reliability. Empty list if PERPLEXITY_API_KEY is not set.
    """
    if not os.environ.get("PERPLEXITY_API_KEY", "").strip():
        log.info("PERPLEXITY_API_KEY not set — skipping evidence discovery for %s", ticker)
        return []

    _migrate_schema()

    # Keyed by URL so duplicate URLs across queries accumulate query_types
    by_url: dict = {}

    for query_type, tmpl in _EVIDENCE_QUERIES:
        query = tmpl.format(ticker=ticker.upper(), company_name=company_name)
        log.info("%s: [%s] query: %r", ticker, query_type, query[:80])

        raw_results = _call_perplexity(query)
        new_count    = 0
        merged_count = 0

        for raw in raw_results:
            if not raw.get("url"):
                continue
            result = _parse_result(raw)
            url    = result["url"]

            # _cache_write owns all merge logic for the DB
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
                merged_count += 1

        log.info("%s: [%s] → %d new, %d merged", ticker, query_type, new_count, merged_count)

    candidates = list(by_url.values())
    log.info("%s: evidence discovery complete — %d unique candidates", ticker, len(candidates))
    return candidates
