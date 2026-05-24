"""
transcript_fetcher.py
Waterfall transcript acquisition with caching.

Entry point:
    fetch_transcript(ticker: str) -> Optional[dict]

Return dict:
    ticker, source_type, source_url, raw_text,
    fiscal_year, fiscal_quarter, calendar_period,
    reported_date, reliability, discovered_by

Waterfall:
  1A. Perplexity discovers transcript URL directly
  1B. IR page HTML scraping (static pages)
  2.  IR press release HTML
  3.  SEC 8-K — full exhibit inspection per filing
  4.  FMP API
  5.  YouTube transcript (emergency fallback)
"""

import io
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

log = logging.getLogger("transcript_fetcher")

_DB_PATH          = Path(__file__).resolve().parent / "cache" / "duke_cache.db"
_REPO_ROOT        = Path(__file__).resolve().parent.parent.parent.parent
_EDGAR_SUBMIT     = "https://data.sec.gov/submissions/CIK{cik}.json"
_EDGAR_ARCHIVE    = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"
_FMP_URL          = "https://financialmodelingprep.com/stable/earning-call-transcript"
_PERPLEXITY_URL   = "https://api.perplexity.ai/chat/completions"
_HEADERS          = {"User-Agent": "DUKE-research contact@duke-research.ai"}

_LINK_RE       = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_PDF_RE        = re.compile(r'\.pdf(\?[^"\']*)?$', re.I)
_TRANSCRIPT_RE = re.compile(r'transcript', re.I)
_EARNINGS_RE   = re.compile(r'earnings|results|quarterly|Q[1-4]', re.I)
_YT_RE         = re.compile(r'(?:youtube\.com/watch\?.*?v=|youtu\.be/)([A-Za-z0-9_-]{11})')
_IX_STRIP      = re.compile(r'^/ix\?doc=', re.I)

# URL path signals that identify an earnings event/webcast page vs a plain press release
_EARNINGS_EVENT_PATH_RE = re.compile(
    r'event|events|earnings-call|earnings_call|webcast|call-details|call_details',
    re.I
)

# Transcript cache TTL: earnings happen every ~90 days; re-fetch after 85 days
# so a bad initial fetch doesn't persist for more than one quarter.
_TRANSCRIPT_CACHE_TTL_DAYS = 85

# Earnings content keywords — must match ≥2 for a document to be accepted
_EARNINGS_CONTENT_KW = re.compile(
    r'\b(revenue|quarter|earnings|guidance|growth|margin)\b', re.I
)

# Minimum text lengths for 8-K document acceptance
_MIN_LEN_PRESS_RELEASE = 2_000   # short press releases, summaries
_MIN_LEN_TRANSCRIPT    = 8_000   # transcript-like documents

# CDN content signal keywords
_CDN_CONTENT_KW = re.compile(
    r'transcript|earnings|quarterly|results|financial|webcast|presentation', re.I
)


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    # Add new columns introduced in DUKE-03; idempotent on existing databases.
    for col_ddl in (
        "ALTER TABLE transcript_cache ADD COLUMN conference_date TEXT",
        "ALTER TABLE transcript_cache ADD COLUMN has_q_and_a INTEGER DEFAULT 0",
        "ALTER TABLE transcript_cache ADD COLUMN speakers TEXT",
    ):
        try:
            con.execute(col_ddl)
            con.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
    return con


def _cache_key(ticker: str, fiscal_year: str, fiscal_quarter: str) -> str:
    return f"{ticker.upper()}_{fiscal_year}_{fiscal_quarter}"


def _cache_get(ticker: str, fiscal_year: str, fiscal_quarter: str) -> Optional[sqlite3.Row]:
    key = _cache_key(ticker, fiscal_year, fiscal_quarter)
    with _db() as con:
        return con.execute(
            "SELECT * FROM transcript_cache WHERE id = ?", (key,)
        ).fetchone()


def _cache_write(row: dict) -> None:
    import json as _json
    speakers_json = None
    if row.get("speakers") is not None:
        try:
            speakers_json = _json.dumps(row["speakers"])
        except Exception:
            pass
    with _db() as con:
        con.execute(
            """INSERT OR REPLACE INTO transcript_cache
               (id, ticker, fiscal_year, fiscal_quarter, calendar_period,
                reported_date, source_type, source_url, raw_text, fetched_at,
                conference_date, has_q_and_a, speakers)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["ticker"], row["fiscal_year"], row["fiscal_quarter"],
                row["calendar_period"], row["reported_date"], row["source_type"],
                row["source_url"], row["raw_text"],
                datetime.now(timezone.utc).isoformat(),
                row.get("conference_date"),
                1 if row.get("has_q_and_a") else 0,
                speakers_json,
            ),
        )


def _ir_cache_get(ticker: str) -> Optional[sqlite3.Row]:
    with _db() as con:
        return con.execute(
            "SELECT * FROM ir_cache WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()


def _read_transcript_cache(ticker: str) -> Optional[dict]:
    """
    Return the most recent transcript cache entry for ticker, or None.
    Searches across all fiscal periods — returns the entry with the latest
    conference_date (falling back to fetched_at for legacy entries).
    """
    import json as _json
    ticker = ticker.upper()
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM transcript_cache WHERE ticker = ? "
            "ORDER BY COALESCE(conference_date, fetched_at) DESC LIMIT 1",
            (ticker,),
        ).fetchall()
    if not rows:
        return None
    row = rows[0]
    d = dict(row)
    # Decode speakers JSON if present
    if d.get("speakers"):
        try:
            d["speakers"] = _json.loads(d["speakers"])
        except Exception:
            d["speakers"] = None
    return d


def _cache_transcript(ticker: str, transcript: dict) -> None:
    """
    Write a transcript dict (as returned by fetch_earningscall_transcript or
    fetch_transcript) into transcript_cache. Derives the cache id from ticker,
    fiscal_year, and fiscal_quarter.
    """
    ticker = ticker.upper()
    fiscal_year    = transcript.get("fiscal_year", "FY0000")
    fiscal_quarter = transcript.get("fiscal_quarter", "Q0")
    cache_id       = _cache_key(ticker, fiscal_year, fiscal_quarter)
    _cache_write({
        "id":               cache_id,
        "ticker":           ticker,
        "fiscal_year":      fiscal_year,
        "fiscal_quarter":   fiscal_quarter,
        "calendar_period":  transcript.get("calendar_period") or "",
        "reported_date":    transcript.get("reported_date") or "",
        "source_type":      transcript.get("source_type", ""),
        "source_url":       transcript.get("source_url", ""),
        "raw_text":         transcript.get("raw_text", ""),
        "conference_date":  transcript.get("conference_date"),
        "has_q_and_a":      transcript.get("has_q_and_a", False),
        "speakers":         transcript.get("speakers"),
    })


def _is_transcript_stale(cached: dict) -> bool:
    """
    Return True if the cached transcript should be re-fetched.
    conference_date-based check with TTL fallback for legacy entries.
    """
    conf_date_str = cached.get("conference_date")
    if conf_date_str:
        try:
            conf_date = date.fromisoformat(conf_date_str)
            return conf_date < date.today()
        except Exception:
            pass
    # Legacy entry — use TTL fallback
    fetched_at = cached.get("fetched_at", "")
    try:
        age_days = (
            datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
        ).days
        return age_days >= _TRANSCRIPT_CACHE_TTL_DAYS
    except Exception:
        return True  # Unknown age — treat as stale


# ─────────────────────────────────────────────
# FISCAL PERIOD MAPPING
# ─────────────────────────────────────────────

def _fiscal_periods(ticker: str) -> tuple:
    """
    Return (fiscal_year, fiscal_quarter, calendar_period, reported_date)
    for the most recently completed fiscal quarter.

    Finds the fiscal quarter whose end date most recently passed today, rather
    than proxying through calendar quarters. The prior calendar-quarter proxy
    was wrong for companies like AVGO (FY ends Oct): on May 20 the proxy
    returned FQ1 (ended Jan 31) even though FQ2 ended Apr 30 and is complete.

    Fiscal quarter end months for a FY ending in month M:
      FQ1: (M - 9) mod 12,  FQ2: (M - 6) mod 12,
      FQ3: (M - 3) mod 12,  FQ4: M
    """
    row          = _ir_cache_get(ticker)
    fy_end_month = (row["fiscal_year_end_month"] or 12) if row else 12

    today = date.today()

    # Build the four fiscal quarter end months (FQ1..FQ4), 1-based.
    fq_end_months = [((fy_end_month - 3 * (4 - n) - 1) % 12) + 1 for n in range(1, 5)]

    # Search this year and last year; pick the latest end date before today.
    best_end_date: Optional[date] = None
    best_fq_num:   Optional[int]  = None
    best_end_yr:   Optional[int]  = None

    for yr in (today.year, today.year - 1):
        for fq_num, end_m in enumerate(fq_end_months, 1):
            last = (
                date(yr + 1, 1, 1) - timedelta(days=1) if end_m == 12
                else date(yr, end_m + 1, 1) - timedelta(days=1)
            )
            if last < today and (best_end_date is None or last > best_end_date):
                best_end_date = last
                best_fq_num   = fq_num
                best_end_yr   = yr

    # Fallback: should never be reached for any real ticker
    if best_fq_num is None:
        best_fq_num = 4
        best_end_yr = today.year - 1

    fq_end_m = fq_end_months[best_fq_num - 1]

    # Fiscal year: if the FQ's end month is after fy_end_month in the calendar
    # year, it belongs to the *next* fiscal year (e.g. MSFT FQ1 ends Sep, FY
    # ends Jun → FY label uses best_end_yr + 1).
    fy_yr = best_end_yr + (1 if fq_end_m > fy_end_month else 0)

    fiscal_year    = f"FY{fy_yr}"
    fiscal_quarter = f"Q{best_fq_num}"

    # Calendar quarter for the FQ end month (display / cache label only)
    cal_q      = (fq_end_m - 1) // 3 + 1
    cal_period = f"Q{cal_q} {best_end_yr}"

    # Estimated reported date: one month after fiscal quarter end
    rep_m = fq_end_m + 1 if fq_end_m < 12 else 1
    rep_y = best_end_yr if fq_end_m < 12 else best_end_yr + 1
    try:
        reported = date(rep_y, rep_m, 15).isoformat()
    except ValueError:
        reported = date(best_end_yr, 12, 15).isoformat()

    return fiscal_year, fiscal_quarter, cal_period, reported


# ─────────────────────────────────────────────
# HTTP HELPERS
# ─────────────────────────────────────────────

def _get(url: str, timeout: int = 10, max_bytes: int = 500_000,
         decode: bool = True):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(max_bytes)
    return raw.decode("utf-8", errors="replace") if decode else raw


def _abs_url(href: str, base: str) -> str:
    return urllib.parse.urljoin(base, href)


def _strip_html(html: str) -> str:
    """Strip tags; collapse whitespace; preserve paragraph breaks."""
    class _S(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self._block = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}
        def handle_data(self, data):
            self.parts.append(data)
        def handle_starttag(self, tag, attrs):
            if tag.lower() in self._block:
                self.parts.append("\n")
        def handle_endtag(self, tag):
            if tag.lower() in self._block:
                self.parts.append("\n")
    p = _S(); p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ensure_package(pkg: str, import_name: Optional[str] = None) -> bool:
    name = import_name or pkg
    try:
        __import__(name)
        return True
    except ImportError:
        log.info("Installing %s …", pkg)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg, "--break-system-packages"],
            capture_output=True,
        )
        if result.returncode != 0:
            log.warning("pip install %s failed: %s", pkg, result.stderr.decode()[:200])
            return False
        return True


def _extract_pdf_text(raw_bytes: bytes) -> Optional[str]:
    if not _ensure_package("pdfplumber"):
        return None
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        text = "\n\n".join(p for p in pages if p.strip())
        return text if len(text) >= 500 else None
    except Exception as exc:
        log.debug("PDF extraction failed: %s", exc)
        return None


# ─────────────────────────────────────────────
# DOMAIN VALIDATION
# ─────────────────────────────────────────────

def _root_domain(url: str) -> str:
    """Return last-two-segment root domain, lowercased, without www."""
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        parts  = netloc.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else netloc
    except Exception:
        return ""


def _full_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_official_host(url: str, ir_url: Optional[str]) -> bool:
    """
    Always-allowed hosts:
      - company official domain (shares root with ir_url)
      - sec.gov
      - *.q4cdn.com
      - *.q4inc.com
    """
    host = _full_host(url)
    if not host:
        return False
    if "sec.gov" in host:
        return True
    if host.endswith(".q4cdn.com") or host == "q4cdn.com":
        return True
    if host.endswith(".q4inc.com") or host == "q4inc.com":
        return True
    if ir_url:
        ir_root   = _root_domain(ir_url)
        cand_root = _root_domain(url)
        if ir_root and ir_root == cand_root:
            return True
    return False


def _is_cdn_host(url: str) -> bool:
    """Conditionally-allowed CDN hosts: cloudfront.net, s3.amazonaws.com."""
    host = _full_host(url)
    return host.endswith(".cloudfront.net") or host.endswith(".s3.amazonaws.com")


def _cdn_content_signals(url: str, title: str = "", snippet: str = "") -> bool:
    """Return True if URL/title/snippet contain at least one CDN content keyword."""
    combined = f"{url} {title} {snippet}"
    return bool(_CDN_CONTENT_KW.search(combined))


def _is_allowed_domain(
    url: str,
    ir_url: Optional[str],
    title: str = "",
    snippet: str = "",
    fetched_text: str = "",
) -> bool:
    """
    Unified domain check:
      Official hosts: always allowed.
      CDN hosts (cloudfront.net, s3.amazonaws.com): allowed only when
        content signals pass AND fetched text passes earnings validation.
      Everything else: rejected.
    """
    if _is_official_host(url, ir_url):
        return True
    if _is_cdn_host(url):
        if not _cdn_content_signals(url, title, snippet):
            log.debug("CDN URL rejected — no content signals: %s", url)
            return False
        if fetched_text and not _is_earnings_content(fetched_text):
            log.debug("CDN URL rejected — earnings validation failed: %s", url)
            return False
        return True
    return False


# ─────────────────────────────────────────────
# EARNINGS CONTENT VALIDATION
# ─────────────────────────────────────────────

def _is_earnings_content(text: str) -> bool:
    """Require ≥2 distinct earnings keywords in the text."""
    found = set(_EARNINGS_CONTENT_KW.findall(text.lower()))
    return len(found) >= 2


def _8k_source_type(text: str) -> Optional[str]:
    """
    Returns:
      'sec_8k_exhibit'               if ≥ 8,000 chars AND earnings content
      'sec_8k_exhibit_press_release' if ≥ 2,000 chars AND earnings content
      None                           if too short or no earnings content
    """
    if not _is_earnings_content(text):
        return None
    if len(text) >= _MIN_LEN_TRANSCRIPT:
        return "sec_8k_exhibit"
    if len(text) >= _MIN_LEN_PRESS_RELEASE:
        return "sec_8k_exhibit_press_release"
    return None


# ─────────────────────────────────────────────
# PRIORITY 1A: Perplexity transcript discovery
# ─────────────────────────────────────────────

def _is_index_page(url: str, ir_url: Optional[str]) -> bool:
    """Return True if the URL is the known IR quarterly results landing/index page."""
    if not ir_url:
        return False
    return url.rstrip("/") == ir_url.rstrip("/")


def _perplexity_call(query: str, api_key: str, ticker: str) -> list:
    """Make one Perplexity Sonar call; return search_results list or []."""
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
        log.warning("Perplexity request failed for %s: %s", ticker, exc)
        return []
    results = data.get("search_results") or []
    if not results:
        log.debug("No search_results from Perplexity for %s", ticker)
    return results


def _accept_transcript_results(
    search_results: list,
    ir_url: Optional[str],
    ticker: str,
) -> Optional[tuple]:
    """
    Iterate Perplexity results; return (raw_text, url, source_type) for the
    first URL that passes all acceptance checks, or None.

    source_type is one of:
      "ir_transcript_pdf"   — PDF that passes earnings content validation
      "ir_earnings_event"   — HTML event/webcast page on the official IR domain
      "ir_press_release"    — any other accepted HTML on the official IR domain

    Rejection reasons logged:
      rejected_landing_page               — URL is the IR index/quarterly-results page
      rejected_too_short                  — stripped text < 2 000 chars
      rejected_not_pdf_for_transcript     — PDF extraction failed or too short
      rejected_failed_earnings_validation — text does not pass _is_earnings_content()
    """
    for result in search_results:
        url     = (result.get("url") or "").strip()
        title   = (result.get("name") or result.get("title") or "").lower()
        snippet = (result.get("snippet") or "").lower()

        if not url:
            continue

        url_lower = url.lower()

        # Must signal transcript or earnings content in metadata
        if not (_TRANSCRIPT_RE.search(url_lower) or _EARNINGS_RE.search(url_lower)
                or "transcript" in title or "earnings" in title):
            log.debug("1A: skipping non-transcript URL %s", url)
            continue

        # Domain pre-check (official hosts pass immediately; CDN checked after fetch)
        if not _is_official_host(url, ir_url) and not _is_cdn_host(url):
            log.debug("1A: skipping off-domain URL %s", url)
            continue

        # Reject the known IR quarterly results landing/index page immediately
        if _is_index_page(url, ir_url):
            log.info("1A: rejected_landing_page — URL is IR index page: %s", url)
            continue

        # Fetch
        try:
            req2 = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req2, timeout=10) as r2:
                if r2.status != 200:
                    continue
                raw = r2.read(5_000_000)
        except Exception as exc:
            log.debug("1A: URL unreachable (%s): %s", url, exc)
            continue

        # ── PDF path ──────────────────────────────────────────────────
        if _PDF_RE.search(url_lower):
            text = _extract_pdf_text(raw)
            if not text or len(text) < _MIN_LEN_PRESS_RELEASE:
                log.info("1A: rejected_not_pdf_for_transcript — extraction failed or too short: %s", url)
                continue
            if not _is_earnings_content(text):
                log.info("1A: rejected_failed_earnings_validation (PDF): %s", url)
                continue
            if not _is_allowed_domain(url, ir_url, title, snippet, text):
                log.debug("1A: domain not allowed (PDF): %s", url)
                continue
            log.info("1A: accepted ir_transcript_pdf for %s → %s", ticker, url)
            return text, url, "ir_transcript_pdf"

        # ── HTML path ─────────────────────────────────────────────────
        html = raw.decode("utf-8", errors="replace")
        text = _strip_html(html)

        if len(text) < _MIN_LEN_PRESS_RELEASE:
            log.info("1A: rejected_too_short (%d chars) for %s: %s", len(text), ticker, url)
            continue

        if not _is_earnings_content(text):
            log.info("1A: rejected_failed_earnings_validation (HTML) for %s: %s", ticker, url)
            continue

        if not _is_allowed_domain(url, ir_url, title, snippet, text):
            log.debug("1A: domain not allowed (HTML): %s", url)
            continue

        # Fix 1B: classify as ir_earnings_event when URL path signals an event page
        url_path = urllib.parse.urlparse(url).path
        if _EARNINGS_EVENT_PATH_RE.search(url_path) and _is_official_host(url, ir_url):
            log.info("1A: accepted ir_earnings_event for %s → %s", ticker, url)
            return text, url, "ir_earnings_event"

        log.info("1A: accepted ir_press_release for %s → %s", ticker, url)
        return text, url, "ir_press_release"

    return None


def _try_perplexity_transcript(
    ir_url: Optional[str],
    ticker: str,
    company_name: str,
    fiscal_year: str = "",
    fiscal_quarter: str = "",
) -> Optional[tuple]:
    """
    Query Perplexity Sonar for a direct transcript or earnings release URL.
    Returns (raw_text, source_url, source_type) or None.

    Makes up to two Perplexity calls:
      1. Primary broad query — transcript, event page, or earnings release
      2. Targeted fallback — fires only when the primary returned the IR landing page
         and nothing else useful; uses fiscal period + IR domain as context
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        log.debug("PERPLEXITY_API_KEY not set — skipping 1A for %s", ticker)
        return None

    ir_hint = f"from official investor relations site {ir_url}" if ir_url else ""

    # Fix 1A: broader query — not PDF-exclusive; includes event pages and releases
    primary_query = (
        f"most recent earnings call transcript, earnings event page, or earnings release "
        f"for {company_name} ({ticker}) {ir_hint}"
    ).strip()

    search_results = _perplexity_call(primary_query, api_key, ticker)
    if not search_results:
        return None

    out = _accept_transcript_results(search_results, ir_url, ticker)
    if out:
        return out

    # Fix 1C: if primary returned only the IR landing page, retry with a more
    # targeted query using fiscal period and IR domain for tighter context.
    found_landing_page = ir_url and any(
        _is_index_page((r.get("url") or "").strip(), ir_url)
        for r in search_results
        if (r.get("url") or "").strip()
    )
    if found_landing_page and (fiscal_quarter or fiscal_year):
        yr         = fiscal_year.replace("FY", "") if fiscal_year else ""
        ir_domain  = _root_domain(ir_url) if ir_url else ""
        fallback_q = (
            f"{company_name} {ticker} {fiscal_quarter} {yr} "
            f"earnings call event page investor relations {ir_domain}"
        ).strip()
        log.info("1A: primary returned landing page — retrying with targeted query for %s", ticker)
        retry_results = _perplexity_call(fallback_q, api_key, ticker)
        out = _accept_transcript_results(retry_results, ir_url, ticker)
        if out:
            return out

    log.debug("1A: no valid transcript URL found via Perplexity for %s", ticker)
    return None


# ─────────────────────────────────────────────
# PRIORITY 1B: IR page HTML scraping (static pages)
# ─────────────────────────────────────────────

def _try_ir_pdf(ir_url: str, ticker: str) -> Optional[tuple]:
    """Returns (raw_text, pdf_url) or None."""
    try:
        html = _get(ir_url)
    except Exception as exc:
        log.debug("IR page fetch failed: %s", exc)
        return None

    pdf_links = []
    for href in _LINK_RE.findall(html):
        if _PDF_RE.search(href) and _TRANSCRIPT_RE.search(href):
            pdf_links.append(_abs_url(href, ir_url))
    if not pdf_links:
        for m in re.finditer(
            r'href=["\']([^"\']+\.pdf[^"\']*)["\'][^>]*>[^<]*transcript[^<]*<',
            html, re.I,
        ):
            pdf_links.append(_abs_url(m.group(1), ir_url))

    if not pdf_links:
        log.debug("1B: no transcript PDFs on static IR page for %s", ticker)
        return None

    for pdf_url in pdf_links[:3]:
        try:
            raw  = _get(pdf_url, decode=False)
            text = _extract_pdf_text(raw)
            if text:
                return text, pdf_url
        except Exception as exc:
            log.debug("1B: PDF fetch/parse failed (%s): %s", pdf_url, exc)
    return None


# ─────────────────────────────────────────────
# PRIORITY 2: IR press release HTML
# ─────────────────────────────────────────────

def _try_ir_press_release(ir_url: str, ticker: str) -> Optional[tuple]:
    """Returns (raw_text, press_release_url) or None."""
    try:
        html = _get(ir_url)
    except Exception as exc:
        log.debug("IR page fetch failed: %s", exc)
        return None

    candidates = []
    for href in _LINK_RE.findall(html):
        if _EARNINGS_RE.search(href):
            abs_href = _abs_url(href, ir_url)
            if abs_href.startswith("http"):
                candidates.append(abs_href)

    for m in re.finditer(
        r'href=["\']([^"\']+)["\'][^>]*>([^<]*(?:earnings|results|quarterly|Q[1-4])[^<]*)<',
        html, re.I,
    ):
        candidates.append(_abs_url(m.group(1), ir_url))

    for pr_url in candidates[:3]:
        try:
            pr_html = _get(pr_url)
            text    = _strip_html(pr_html)
            if len(text) > 1000 and re.search(r"revenue|earnings|quarter", text, re.I):
                return text, pr_url
        except Exception:
            continue
    return None


# ─────────────────────────────────────────────
# PRIORITY 3: SEC 8-K — full exhibit inspection
# ─────────────────────────────────────────────

# Exhibit priority scores (higher = better)
_EXHIBIT_PRIORITY = [
    # (regex pattern for doc_type or description, score)
    (re.compile(r'\bEX-99\.1\b',           re.I),  10),
    (re.compile(r'\bEX-99\b',              re.I),   9),
    (re.compile(r'earnings.release',       re.I),   8),
    (re.compile(r'press.release',          re.I),   7),
    (re.compile(r'investor.presentation',  re.I),   6),
    (re.compile(r'\bEX-99\.',              re.I),   5),  # EX-99.2, etc.
    (re.compile(r'exhibit',               re.I),   3),
]

# Regex to match document rows in EDGAR filing index tables
_INDEX_ROW_RE = re.compile(
    r'href="(/[^"]+\.(htm[l]?|txt|pdf))"[^>]*>.*?</a>'
    r'(?:.*?<td[^>]*>(?P<desc>[^<]*)</td>)?'
    r'(?:.*?<td[^>]*>(?P<dtype>[^<]*)</td>)?',
    re.I | re.S,
)


def _parse_filing_index(html: str) -> list:
    """
    Parse EDGAR filing index HTML.
    Returns list of (score, href, description, doc_type) sorted by score desc.
    Each href is a full /Archives/... path (ix?doc= prefix stripped).
    """
    docs = []

    # Extract rows from the filing documents table
    # EDGAR index has rows like:
    #   <td><a href="/Archives/.../ex991.htm">ex991.htm</a></td>
    #   <td>Press Release</td><td>EX-99.1</td>
    for m in re.finditer(
        r'<tr[^>]*>(.*?)</tr>',
        html, re.I | re.S,
    ):
        row = m.group(1)
        # Find href
        href_m = re.search(r'href="(/[^"]+)"', row, re.I)
        if not href_m:
            continue
        href = _IX_STRIP.sub("/", href_m.group(1))
        if not re.search(r'\.(htm[l]?|txt|pdf)$', href, re.I):
            continue
        # Extract td text blocks as description / doc_type
        tds = re.findall(r'<td[^>]*>([^<]*)</td>', row, re.I)
        desc  = tds[1].strip() if len(tds) > 1 else ""
        dtype = tds[2].strip() if len(tds) > 2 else ""

        combined = f"{desc} {dtype}"
        score = 0
        for pat, s in _EXHIBIT_PRIORITY:
            if pat.search(combined):
                score = s
                break
        docs.append((score, href, desc, dtype))

    # Sort: highest score first, primary document (score=0) last
    docs.sort(key=lambda x: -x[0])
    return docs


def _get_cik(ticker: str) -> Optional[str]:
    try:
        sys.path.insert(0, str(_REPO_ROOT))
        from common.edgar_client import _cik
        return _cik(ticker)
    except Exception as exc:
        log.debug("CIK lookup failed for %s: %s", ticker, exc)
        return None


def _fetch_sec_doc(url: str) -> Optional[str]:
    """Fetch SEC HTML document; 10s timeout, 500KB max. Returns stripped text or None."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(500_000)
        text = _strip_html(raw.decode("utf-8", errors="replace"))
        return text if text else None
    except Exception as exc:
        log.debug("3: SEC doc fetch failed (%s): %s", url, exc)
        return None


def _try_sec_8k(ticker: str) -> Optional[tuple]:
    """
    Scan recent 8-K filings, skipping any without item 2.02 (Results of
    Operations). For each earnings 8-K (up to 3 scanned):
      1. Fetch filing index and parse all documents.
      2. Try each document in priority order (EX-99.1 first, primary last).
      3. Accept the first document that passes earnings-content validation.
    Returns (raw_text, url, source_type) or None.
    """
    cik = _get_cik(ticker)
    if not cik:
        return None

    try:
        req = urllib.request.Request(
            _EDGAR_SUBMIT.format(cik=cik), headers=_HEADERS
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            subs = json.loads(r.read())
    except Exception as exc:
        log.debug("EDGAR submissions fetch failed: %s", exc)
        return None

    filings      = subs.get("filings", {}).get("recent", {})
    forms        = filings.get("form", [])
    accessions   = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    items_list   = filings.get("items", [])
    cik_bare     = cik.lstrip("0")

    earnings_scanned = 0
    for i, form in enumerate(forms):
        if form != "8-K":
            continue

        # Only process earnings 8-Ks (item 2.02 = Results of Operations)
        item_str = items_list[i] if i < len(items_list) else ""
        if "2.02" not in item_str:
            log.debug("3: skipping 8-K %s (items=%r, no 2.02)",
                      accessions[i] if i < len(accessions) else "?", item_str)
            continue

        if earnings_scanned >= 3:
            break
        earnings_scanned += 1

        if i >= len(accessions):
            continue
        acc        = accessions[i]
        acc_nodash = acc.replace("-", "")
        primary    = primary_docs[i] if i < len(primary_docs) else ""

        log.debug("3: processing earnings 8-K %s (items=%r)", acc, item_str)

        # ── Fetch filing index ─────────────────────────────────────
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_bare}"
            f"/{acc_nodash}/{acc}-index.htm"
        )
        try:
            req2 = urllib.request.Request(index_url, headers=_HEADERS)
            with urllib.request.urlopen(req2, timeout=10) as r2:
                idx_html = r2.read(200_000).decode("utf-8", errors="replace")
        except Exception as exc:
            log.debug("3: index fetch failed (%s): %s", index_url, exc)
            idx_html = ""

        # ── Build prioritised document list ───────────────────────
        docs = _parse_filing_index(idx_html)

        # Ensure primary document appears at score=0 as last resort
        if primary:
            primary_path = (
                f"/Archives/edgar/data/{cik_bare}/{acc_nodash}/{primary}"
            )
            known_paths = {d[1] for d in docs}
            if primary_path not in known_paths:
                docs.append((0, primary_path, "primary document", ""))

        if not docs:
            log.debug("3: no documents in index for %s acc=%s", ticker, acc)
            continue

        # ── Try each document in priority order ────────────────────
        for score, path, desc, dtype in docs:
            doc_url = "https://www.sec.gov" + path
            log.debug("3: trying %s (score=%d desc=%r dtype=%r)",
                      doc_url, score, desc, dtype)

            text = _fetch_sec_doc(doc_url)
            if not text:
                continue

            stype = _8k_source_type(text)
            if stype:
                log.info(
                    "3: accepted %s — %s (%d chars, score=%d)",
                    doc_url, stype, len(text), score,
                )
                return text, doc_url, stype

            log.debug(
                "3: rejected %s — %d chars, kw_count=%d",
                doc_url, len(text),
                len(set(_EARNINGS_CONTENT_KW.findall(text.lower()))),
            )

    log.debug("3: no usable earnings 8-K document found for %s", ticker)
    return None


# ─────────────────────────────────────────────
# PRIORITY 4: FMP API
# ─────────────────────────────────────────────

def _try_fmp(ticker: str) -> Optional[tuple]:
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        return None

    url = f"{_FMP_URL}?symbol={ticker.upper()}&apikey={api_key}"
    try:
        data = json.loads(_get(url))
    except Exception as exc:
        log.debug("FMP fetch failed: %s", exc)
        return None

    if not data or not isinstance(data, list):
        return None

    text = data[0].get("content") or ""
    safe_url = re.sub(r"apikey=[^&]+", "apikey=REDACTED", url)
    return (text, safe_url) if len(text) >= 200 else None


# ─────────────────────────────────────────────
# PRIORITY 5: YouTube transcript (emergency)
# ─────────────────────────────────────────────

def _try_youtube(ir_url: Optional[str], ticker: str) -> Optional[tuple]:
    if not _ensure_package("youtube-transcript-api", "youtube_transcript_api"):
        return None

    video_id = None
    if ir_url:
        try:
            html     = _get(ir_url)
            m        = _YT_RE.search(html)
            if m:
                video_id = m.group(1)
        except Exception:
            pass

    if not video_id:
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        chunks = YouTubeTranscriptApi.get_transcript(video_id)
        parts  = []
        for c in chunks:
            ts   = c.get("start", 0)
            mins = int(ts) // 60
            secs = int(ts) % 60
            parts.append(f"[{mins:02d}:{secs:02d}] {c.get('text', '')}")
        text = "\n".join(parts)
        if len(text) < 200:
            return None
        return text, f"https://www.youtube.com/watch?v={video_id}"
    except Exception as exc:
        log.debug("YouTube transcript failed: %s", exc)
        return None


# ─────────────────────────────────────────────
# SOURCE METADATA
# ─────────────────────────────────────────────

def _source_reliability(source_type: str) -> float:
    return {
        "earningscall_api":               0.95,
        "ir_transcript_pdf":              0.95,
        "sec_8k_exhibit":                 0.95,
        "sec_8k_exhibit_press_release":   0.95,
        "ir_press_release":               0.90,
        "ir_earnings_event":              0.90,
        "fmp_transcript":                 0.85,
        "youtube_transcript":             0.70,
    }.get(source_type, 0.75)


def _document_subtype(source_type: str) -> str:
    if source_type == "earningscall_api":
        return "earnings_call_transcript"
    if source_type in (
        "sec_8k_exhibit", "sec_8k_exhibit_press_release",
        "ir_press_release", "ir_earnings_event",
    ):
        return "earnings_press_release"
    if source_type in ("ir_transcript_pdf", "fmp_transcript"):
        return "earnings_transcript"
    if source_type == "youtube_transcript":
        return "youtube_transcript"
    return ""


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def _build_transcript_return(cached: dict) -> dict:
    """Build the public return dict from a cached row or a fresh fetch result."""
    import json as _json
    st = cached.get("source_type", "")
    speakers = cached.get("speakers")
    if isinstance(speakers, str):
        try:
            speakers = _json.loads(speakers)
        except Exception:
            speakers = None
    return {
        "ticker":           cached.get("ticker", ""),
        "source_type":      st,
        "source_url":       cached.get("source_url", ""),
        "raw_text":         cached.get("raw_text", ""),
        "fiscal_year":      cached.get("fiscal_year", ""),
        "fiscal_quarter":   cached.get("fiscal_quarter", ""),
        "calendar_period":  cached.get("calendar_period"),
        "reported_date":    cached.get("reported_date", ""),
        "reliability":      _source_reliability(st),
        "discovered_by":    cached.get("discovered_by", "cache"),
        "document_subtype": _document_subtype(st),
        "source_priority":  "official_company_material",
        "has_q_and_a":      bool(cached.get("has_q_and_a")),
        "conference_date":  cached.get("conference_date"),
        "speakers":         speakers or [],
    }


def fetch_transcript(ticker: str) -> Optional[dict]:
    """
    Fetch the most recent earnings transcript via priority waterfall.
    Returns None only if every source fails.

    Waterfall order:
      0. EarningsCall API (primary — full transcript with speaker attribution)
      1A. Perplexity transcript discovery
      1B. Static IR page PDF scraping
      2.  IR press release HTML
      3.  SEC 8-K exhibit
      4.  FMP API
      5.  YouTube transcript
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ir_discovery import get_ir_url, get_company_name

    ticker = ticker.upper()
    fiscal_year, fiscal_quarter, cal_period, reported_date = _fiscal_periods(ticker)

    # ── Cache check ──────────────────────────────────────────────
    # Use the most-recent entry across all fiscal periods, then validate
    # staleness using conference_date (or TTL fallback for legacy entries).
    cached = _read_transcript_cache(ticker)
    if cached:
        if not _is_transcript_stale(cached):
            log.info(
                "%s: transcript cache hit (conference_date %s)",
                ticker, cached.get("conference_date", "unknown"),
            )
            return _build_transcript_return(cached)
        else:
            log.info("%s: transcript cache stale — re-fetching", ticker)

    ir_url       = get_ir_url(ticker)
    company_name = get_company_name(ticker)

    result_text   = None
    source_type   = None
    source_url    = None
    discovered_by = None
    ec_result     = None

    # ── Priority 0: EarningsCall API ─────────────────────────────
    log.info("%s: [0] EarningsCall API …", ticker)
    try:
        _STAGE_DIR = Path(__file__).resolve().parent
        sys.path.insert(0, str(_STAGE_DIR))
        from earningscall_fetcher import fetch_earningscall_transcript
        ec = fetch_earningscall_transcript(ticker, company_name)
        if ec and ec.get("raw_text"):
            log.info(
                "%s: EarningsCall transcript acquired (%d chars, %s %s)",
                ticker, len(ec["raw_text"]),
                ec.get("fiscal_year", "?"), ec.get("fiscal_quarter", "?"),
            )
            ec_result = ec
            _cache_transcript(ticker, ec)
            return _build_transcript_return(ec)
    except Exception as exc:
        log.warning("%s: EarningsCall Priority 0 failed: %s", ticker, exc)

    # ── Priority 1A: Perplexity direct discovery ──────────────────
    log.info("%s: [1A] Perplexity transcript discovery …", ticker)
    out = _try_perplexity_transcript(ir_url, ticker, company_name, fiscal_year, fiscal_quarter)
    if out:
        result_text, source_url, source_type = out
        discovered_by = "perplexity"

    # ── Priority 1B: Static IR page PDF scraping ──────────────────
    if result_text is None and ir_url:
        log.info("%s: [1B] static IR page PDF scraping …", ticker)
        out = _try_ir_pdf(ir_url, ticker)
        if out:
            result_text, source_url = out
            source_type   = "ir_transcript_pdf"
            discovered_by = "direct"

    # ── Priority 2: IR press release ──────────────────────────────
    if result_text is None and ir_url:
        log.info("%s: [2] IR press release …", ticker)
        out = _try_ir_press_release(ir_url, ticker)
        if out:
            result_text, source_url = out
            source_type   = "ir_press_release"
            discovered_by = "direct"

    # ── Priority 3: SEC 8-K (returns 3-tuple with source_type) ───
    if result_text is None:
        log.info("%s: [3] SEC 8-K exhibit …", ticker)
        out = _try_sec_8k(ticker)
        if out:
            result_text, source_url, source_type = out
            discovered_by = "sec_edgar"

    # ── Priority 4: FMP API ───────────────────────────────────────
    if result_text is None:
        log.info("%s: [4] FMP API …", ticker)
        out = _try_fmp(ticker)
        if out:
            result_text, source_url = out
            source_type   = "fmp_transcript"
            discovered_by = "fmp"

    # ── Priority 5: YouTube ───────────────────────────────────────
    if result_text is None:
        log.info("%s: [5] YouTube transcript …", ticker)
        out = _try_youtube(ir_url, ticker)
        if out:
            result_text, source_url = out
            source_type   = "youtube_transcript"
            discovered_by = "youtube"

    if result_text is None:
        log.warning("%s: all transcript sources exhausted", ticker)
        return None

    cache_id = _cache_key(ticker, fiscal_year, fiscal_quarter)
    _cache_write({
        "id":              cache_id,
        "ticker":          ticker,
        "fiscal_year":     fiscal_year,
        "fiscal_quarter":  fiscal_quarter,
        "calendar_period": cal_period,
        "reported_date":   reported_date,
        "source_type":     source_type,
        "source_url":      source_url,
        "raw_text":        result_text,
    })
    log.info(
        "%s: ✓ %s via %s (%d chars)",
        ticker, source_type, discovered_by, len(result_text),
    )

    return {
        "ticker":           ticker,
        "source_type":      source_type,
        "source_url":       source_url,
        "raw_text":         result_text,
        "fiscal_year":      fiscal_year,
        "fiscal_quarter":   fiscal_quarter,
        "calendar_period":  cal_period,
        "reported_date":    reported_date,
        "reliability":      _source_reliability(source_type),
        "discovered_by":    discovered_by,
        "document_subtype": _document_subtype(source_type),
        "source_priority":  "official_company_material",
        "has_q_and_a":      False,
        "conference_date":  None,
        "speakers":         [],
    }
