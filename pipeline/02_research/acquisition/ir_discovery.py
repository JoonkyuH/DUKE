"""
ir_discovery.py
Discovers and caches IR quarterly results pages.

Entry points:
    get_ir_url(ticker: str) -> Optional[str]
    get_company_name(ticker: str) -> str
"""

import logging
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
log = logging.getLogger("ir_discovery")

_DB_PATH = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

_EDGAR_SEARCH   = (
    "https://efts.sec.gov/LATEST/search-index?q={ticker}"
    "&dateRange=custom&startdt=2020-01-01&forms=10-K"
)
_HEADERS = {"User-Agent": "DUKE-research contact@duke-research.ai"}

_CACHE_TTL_DAYS = 60

_IR_KEYWORDS     = re.compile(r"ir|investor|investors|quarterly|results", re.I)
_BODY_KEYWORDS   = re.compile(r"investor|earnings|quarterly|financial|results", re.I)
_DATE_PATTERNS   = [
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}\b", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b(Q[1-4])\s+\d{4}\b", re.I),
    re.compile(r"\b20(2[2-9]|3\d)\b"),
]


# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _cache_get(ticker: str) -> Optional[sqlite3.Row]:
    with _db() as con:
        return con.execute(
            "SELECT * FROM ir_cache WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()


def _cache_write(
    ticker: str,
    company_name: str,
    ir_url: str,
    status: str,
    discovered_by: str = "perplexity",
    fiscal_year_end_month: Optional[int] = None,
    calendar_quarter_offset: Optional[bool] = None,
    confidence: float = 0.90,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _db() as con:
        con.execute(
            """INSERT INTO ir_cache
               (ticker, company_name, ir_url, fiscal_year_end_month,
                calendar_quarter_offset, discovered_by, last_verified_at,
                status, confidence)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ticker) DO UPDATE SET
                 ir_url               = excluded.ir_url,
                 status               = excluded.status,
                 last_verified_at     = excluded.last_verified_at,
                 discovered_by        = excluded.discovered_by,
                 confidence           = excluded.confidence,
                 company_name         = COALESCE(excluded.company_name, ir_cache.company_name),
                 fiscal_year_end_month = COALESCE(excluded.fiscal_year_end_month,
                                                   ir_cache.fiscal_year_end_month),
                 calendar_quarter_offset = COALESCE(excluded.calendar_quarter_offset,
                                                      ir_cache.calendar_quarter_offset)
            """,
            (
                ticker.upper(), company_name, ir_url,
                fiscal_year_end_month, calendar_quarter_offset,
                discovered_by, now, status, confidence,
            ),
        )


def _cache_mark(ticker: str, status: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _db() as con:
        con.execute(
            "UPDATE ir_cache SET status=?, last_verified_at=? WHERE ticker=?",
            (status, now, ticker.upper()),
        )


# ─────────────────────────────────────────────
# COMPANY NAME LOOKUP
# ─────────────────────────────────────────────

def get_company_name(ticker: str) -> str:
    """Return company name from SEC EDGAR full-text search; fall back to ticker."""
    try:
        url = _EDGAR_SEARCH.format(ticker=urllib.request.quote(ticker.upper()))
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            return ticker
        # display_names looks like "NVIDIA CORP  (NVDA)  (CIK 0001045810)"
        names = hits[0].get("_source", {}).get("display_names", [])
        if names:
            raw = names[0]
            # Strip the CIK suffix and ticker parenthetical
            name = re.split(r"\s+\(", raw)[0].strip().title()
            return name or ticker
    except Exception as exc:
        log.debug("Company name lookup failed for %s: %s", ticker, exc)
    return ticker


# ─────────────────────────────────────────────
# URL VALIDATION
# ─────────────────────────────────────────────

def _page_has_recent_date(text: str) -> bool:
    cutoff_year = datetime.now(timezone.utc).year - 1
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            hit = m.group(0)
            # Extract year from the match
            year_match = re.search(r"\d{4}", hit)
            if year_match and int(year_match.group(0)) >= cutoff_year:
                return True
    return False


def _domain_matches(url: str, ticker: str, company_name: str) -> bool:
    try:
        domain = re.search(r"https?://([^/]+)", url)
        if not domain:
            return False
        d = domain.group(1).lower()
        tk = ticker.lower()
        # Strip common words from company name for matching
        words = re.sub(r"\b(inc|corp|corporation|ltd|co|the|technologies|technology)\b", "",
                       company_name.lower()).split()
        significant = [w for w in words if len(w) > 2]
        if tk in d:
            return True
        return any(w in d for w in significant)
    except Exception:
        return False


def _validate_url(url: str, ticker: str, company_name: str) -> bool:
    """Return True if URL passes all validation checks."""
    try:
        req = urllib.request.Request(url, headers={**_HEADERS, "User-Agent": _HEADERS["User-Agent"]})
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                return False
            body = r.read(200_000).decode("utf-8", errors="replace")
    except Exception as exc:
        log.debug("Validation fetch failed for %s: %s", url, exc)
        return False

    keyword_hits = len(_BODY_KEYWORDS.findall(body))
    if keyword_hits < 2:
        log.debug("URL %s: only %d body keywords (need ≥2)", url, keyword_hits)
        return False

    if not _domain_matches(url, ticker, company_name):
        log.debug("URL %s: domain does not match %s / %s", url, ticker, company_name)
        return False

    if not _page_has_recent_date(body):
        log.debug("URL %s: no recent date found in page content", url)
        return False

    return True


# ─────────────────────────────────────────────
# PERPLEXITY DISCOVERY
# ─────────────────────────────────────────────

_AGGREGATOR_DOMAINS = {
    "alphaspread.com", "stocktitan.net", "public.com",
    "macrotrends.net", "wisesheets.io", "stockanalysis.com",
    "simplywall.st", "finance.yahoo.com",
}


def _score_candidate(result: dict, ticker: str, company_name: str) -> int:
    url     = (result.get("url") or "").lower()
    title   = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    score   = 0

    if any(d in url for d in _AGGREGATOR_DOMAINS):
        score -= 10

    tk = ticker.lower()
    words = re.sub(r"\b(inc|corp|corporation|ltd|co|the|technologies|technology)\b", "",
                   company_name.lower()).split()
    sig = [w for w in words if len(w) > 2]

    if tk in url or any(w in url for w in sig):
        score += 2
    if _IR_KEYWORDS.search(url):
        score += 2
    if "investor" in title or "investor relations" in title:
        score += 1
    for kw in ("earnings", "transcript", "quarterly", "results"):
        if kw in snippet:
            score += 1
            break

    return score


def _discover_via_perplexity(ticker: str, company_name: str) -> Optional[str]:
    from perplexity_discovery import perplexity_search

    query = (
        f"{company_name} ({ticker}) official investor relations page on the company's own "
        f"corporate website where quarterly earnings results are published. "
        f"Not third-party financial data sites."
    )
    results = perplexity_search(query)
    if not results:
        log.warning("No search_results from Perplexity for %s", ticker)
        return None

    scored = sorted(results, key=lambda r: _score_candidate(r, ticker, company_name), reverse=True)
    best   = scored[0]
    url    = best.get("url") or ""
    log.info("Perplexity top candidate for %s: %s (score=%d)",
             ticker, url, _score_candidate(best, ticker, company_name))
    return url or None


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def get_ir_url(ticker: str) -> Optional[str]:
    """
    Discover and return the IR quarterly results page URL for ticker.
    Returns None if discovery and validation both fail.
    """
    ticker = ticker.upper()

    # ── Step 1: cache hit ────────────────────
    row = _cache_get(ticker)
    if row and row["status"] == "active":
        age_days = (
            datetime.now(timezone.utc).date()
            - datetime.fromisoformat(row["last_verified_at"]).date()
        ).days
        if age_days < _CACHE_TTL_DAYS:
            log.info("%s: cache hit (age=%dd) → %s", ticker, age_days, row["ir_url"])
            return row["ir_url"]

        # Age ≥ 60 days: revalidate cached URL before returning
        log.info("%s: cache stale (age=%dd), revalidating …", ticker, age_days)
        company_name = row["company_name"] or get_company_name(ticker)
        if _validate_url(row["ir_url"], ticker, company_name):
            _cache_mark(ticker, "active")
            log.info("%s: cached URL revalidated OK", ticker)
            return row["ir_url"]
        # Cached URL failed revalidation — fall through to rediscovery
        log.warning("%s: cached URL failed revalidation, marking stale", ticker)
        _cache_mark(ticker, "stale")

    # ── Step 2: discover via Perplexity ─────
    company_name = (row["company_name"] if row else None) or get_company_name(ticker)
    log.info("%s: running Perplexity discovery (company=%s)", ticker, company_name)
    candidate = _discover_via_perplexity(ticker, company_name)

    if not candidate:
        if row:
            _cache_mark(ticker, "failed")
        return None

    # ── Step 3: validate candidate ──────────
    if not _validate_url(candidate, ticker, company_name):
        log.warning("%s: Perplexity candidate failed validation: %s", ticker, candidate)
        if row:
            _cache_mark(ticker, "failed")
        return None

    old_url = row["ir_url"] if row else None
    _cache_write(ticker, company_name, candidate, status="active")
    if old_url and old_url != candidate:
        log.info(
            "%s: IR URL updated  old=%s  new=%s  at=%s",
            ticker, old_url, candidate,
            datetime.now(timezone.utc).isoformat(),
        )
    return candidate
