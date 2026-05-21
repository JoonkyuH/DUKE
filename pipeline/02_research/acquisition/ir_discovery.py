"""
ir_discovery.py
Discovers and caches IR quarterly results pages.

Entry points:
    get_ir_url(ticker: str) -> Optional[str]
    get_company_name(ticker: str) -> str
"""

import json
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

_EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
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


def _ensure_ir_table() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS ir_cache (
                ticker                   TEXT NOT NULL PRIMARY KEY,
                company_name             TEXT,
                ir_url                   TEXT,
                fiscal_year_end_month    INTEGER,
                calendar_quarter_offset  INTEGER,
                discovered_by            TEXT,
                last_verified_at         TEXT,
                status                   TEXT,
                confidence               REAL
            )
        """)


_ensure_ir_table()


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
    """Return company name from SEC EDGAR company_tickers.json; fall back to ticker."""
    try:
        req = urllib.request.Request(_EDGAR_TICKERS_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        tk_upper = ticker.upper()
        for entry in data.values():
            if entry.get("ticker", "").upper() == tk_upper:
                return entry.get("title", ticker)
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


def _significant_words(company_name: str) -> list:
    cleaned = re.sub(r"\b(inc|corp|corporation|ltd|co|the|technologies|technology)\b", "",
                     company_name.lower())
    words = re.sub(r"[^a-z0-9\s]", " ", cleaned).split()
    return [w for w in words if len(w) > 2]


def _domain_matches(url: str, ticker: str, company_name: str) -> bool:
    try:
        domain = re.search(r"https?://([^/]+)", url)
        if not domain:
            return False
        d = domain.group(1).lower()
        tk = ticker.lower()
        significant = _significant_words(company_name)
        if tk in d:
            return True
        if any(w in d for w in significant):
            return True
        # Companies like Alphabet use non-obvious holding-company domains (abc.xyz);
        # accept if the URL path explicitly signals an IR section.
        if re.search(r"/(investor|investors|ir)(/|$)", url, re.I):
            return True
        return False
    except Exception:
        return False


def _validate_url(url: str, ticker: str, company_name: str) -> bool:
    """Return True if URL passes all validation checks."""
    body = None
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            if r.status != 200:
                return False
            body = r.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        # 403: server is live and refused us — if domain matches, accept it.
        # Many company IR sites block scrapers but are genuinely valid IR pages.
        if exc.code == 403 and _domain_matches(url, ticker, company_name):
            log.info("URL %s: 403 but domain matches — accepting", url)
            return True
        log.debug("Validation fetch failed for %s: %s", url, exc)
        return False
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

    # Official IR pages often render dates via JS; skip date check when
    # domain identity and keyword density are both high.
    if keyword_hits >= 10:
        return True

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
    # press-release wires — never the company's own IR page
    "prnewswire.com", "businesswire.com", "globenewswire.com", "accesswire.com",
    # financial aggregators / data resellers
    "wealthtender.com", "daloopa.com", "clickbalance.com", "landing.clickbalance.com",
    "marketwatch.com", "wsj.com", "seeking alpha.com", "seekingalpha.com",
    "fool.com", "motleyfool.com", "investopedia.com",
    # social / video — never an IR page
    "youtube.com", "twitter.com", "linkedin.com",
    # financial data / research aggregators
    "quartr.com",
}


def _score_candidate(result: dict, ticker: str, company_name: str) -> int:
    url     = (result.get("url") or "").lower()
    title   = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    score   = 0

    if any(d in url for d in _AGGREGATOR_DOMAINS):
        score -= 10

    tk = ticker.lower()
    sig = _significant_words(company_name)

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
    best_score = _score_candidate(best, ticker, company_name)
    url    = best.get("url") or ""
    log.info("Perplexity top candidate for %s: %s (score=%d)",
             ticker, url, best_score)
    if best_score < 3:
        log.warning("%s: best candidate score %d below threshold (3), skipping", ticker, best_score)
        return None
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
