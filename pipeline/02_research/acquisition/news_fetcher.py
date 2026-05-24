"""
news_fetcher.py
NewsAPI discovery for the DUKE acquisition layer.

Returns discovery metadata only — no full article text.

Entry point:
    fetch_news(ticker: str, company_name: str) -> list[dict]

Each item:
    {url, title, date, snippet, source, source_type, reliability}

Requires: NEWSAPI_KEY environment variable.
Stores results in discovery_cache table in duke_cache.db.
"""

import hashlib
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("news_fetcher")

_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_DB_PATH     = Path(__file__).resolve().parent / "cache" / "duke_cache.db"
_PAGE_SIZE   = 20


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _cache_write(ticker: str, item: dict) -> None:
    url = item.get("url", "")
    now = datetime.now(timezone.utc).isoformat()
    with _db() as con:
        con.execute(
            """INSERT OR REPLACE INTO discovery_cache
               (ticker, url, title, date, snippet, query_types, fetched_at)
               VALUES (?,?,?,?,?,?,?)""",
            (ticker.upper(), url,
             item.get("title", ""), item.get("date", ""),
             item.get("snippet", ""), "news_discovery", now),
        )


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def fetch_news(ticker: str, company_name: str) -> list:
    """
    Fetch recent news articles about ticker from NewsAPI.

    Args:
        ticker:       Stock ticker symbol (e.g. "NVDA").
        company_name: Company name for richer query (e.g. "Nvidia Corp").

    Returns:
        List of discovery metadata dicts. Empty list if NEWSAPI_KEY is not
        set or the request fails.
    """
    api_key = os.environ.get("NEWSAPI_KEY", "").strip()
    if not api_key:
        log.info("NEWSAPI_KEY not set — skipping news discovery for %s", ticker)
        return []

    # Use ticker + first word of company name (e.g. "NVDA NVIDIA") — short
    # queries are more reliable across NewsAPI tiers than full legal names.
    company_short = company_name.split()[0] if company_name else ticker
    query  = f"{ticker} {company_short}"
    params = urllib.parse.urlencode({
        "q":        query,
        "sortBy":   "publishedAt",
        "language": "en",
        "pageSize": _PAGE_SIZE,
    })
    url = f"{_NEWSAPI_URL}?{params}"

    try:
        req = urllib.request.Request(url)
        # add_unredirected_header preserves exact header-name case; the dict
        # form passed to Request() normalizes keys via .capitalize() which
        # produces "User-agent" (lowercase 'a') that some CDNs reject.
        req.add_unredirected_header("User-Agent", "DUKE/1.0")
        req.add_unredirected_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        log.warning("NewsAPI request failed for %s: HTTP %s — %s", ticker, exc.code, body)
        return []
    except Exception as exc:
        log.warning("NewsAPI request failed for %s: %s", ticker, exc)
        return []

    articles = data.get("articles") or []
    if not articles:
        log.info("%s: no articles returned from NewsAPI", ticker)
        return []

    results = []
    for art in articles:
        source_name = (art.get("source") or {}).get("name", "")
        item = {
            "url":         (art.get("url") or "").strip(),
            "title":       (art.get("title") or "").strip(),
            "date":        (art.get("publishedAt") or "")[:10],
            "snippet":     (art.get("description") or "").strip(),
            "source":      source_name,
            "source_type": "news_discovery",
            "reliability": 0.55,
        }
        if not item["url"]:
            continue
        _cache_write(ticker, item)
        results.append(item)

    log.info("%s: news discovery → %d articles", ticker, len(results))
    return results
