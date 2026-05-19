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
from datetime import datetime, date, timezone
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
    with _db() as con:
        con.execute(
            """INSERT OR REPLACE INTO transcript_cache
               (id, ticker, fiscal_year, fiscal_quarter, calendar_period,
                reported_date, source_type, source_url, raw_text, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                row["id"], row["ticker"], row["fiscal_year"], row["fiscal_quarter"],
                row["calendar_period"], row["reported_date"], row["source_type"],
                row["source_url"], row["raw_text"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def _ir_cache_get(ticker: str) -> Optional[sqlite3.Row]:
    with _db() as con:
        return con.execute(
            "SELECT * FROM ir_cache WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()


# ─────────────────────────────────────────────
# FISCAL PERIOD MAPPING
# ─────────────────────────────────────────────

def _fiscal_periods(ticker: str) -> tuple:
    """
    Return (fiscal_year, fiscal_quarter, calendar_period, reported_date)
    for the most recently completed quarter, using ir_cache for fiscal calendar.
    """
    row          = _ir_cache_get(ticker)
    fy_end_month = (row["fiscal_year_end_month"] or 12) if row else 12

    today  = date.today()
    cal_m  = today.month
    cal_yr = today.year

    cur_q = (cal_m - 1) // 3 + 1   # current calendar quarter (1-based)

    # Step back to most recently completed quarter
    prev_q  = cur_q - 1
    prev_yr = cal_yr
    if prev_q < 1:
        prev_q  = 4
        prev_yr = cal_yr - 1

    cal_q_label = f"Q{prev_q}"
    cal_period  = f"{cal_q_label} {prev_yr}"

    if fy_end_month == 12:
        fq    = cal_q_label
        fy_yr = prev_yr
    elif fy_end_month == 1:
        # FY ends Jan: cal Q1→FQ4 same year, cal Q2/3/4 → FQ1/2/3 next FY
        fq_map = {1: ("Q4", 0), 2: ("Q1", 1), 3: ("Q2", 1), 4: ("Q3", 1)}
        fq, yr_add = fq_map[prev_q]
        fy_yr = prev_yr + yr_add
    else:
        shift  = (12 - fy_end_month) // 3
        fq_num = ((prev_q - 1 + shift) % 4) + 1
        fq     = f"Q{fq_num}"
        fy_yr  = prev_yr + (1 if fq_num < prev_q else 0)

    fiscal_year    = f"FY{fy_yr}"
    fiscal_quarter = fq

    q_end_month = prev_q * 3
    try:
        rep_month = q_end_month + 1 if q_end_month < 12 else 1
        rep_year  = prev_yr if q_end_month < 12 else prev_yr + 1
        reported  = date(rep_year, rep_month, 15).isoformat()
    except ValueError:
        reported = date(prev_yr, 12, 15).isoformat()

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

def _try_perplexity_transcript(
    ir_url: Optional[str],
    ticker: str,
    company_name: str,
) -> Optional[tuple]:
    """
    Query Perplexity Sonar for a direct transcript URL.
    Returns (raw_text, source_url) or None.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        log.debug("PERPLEXITY_API_KEY not set — skipping 1A for %s", ticker)
        return None

    ir_hint = f"from official investor relations site {ir_url}" if ir_url else ""
    query   = (
        f"most recent earnings call transcript PDF download link for "
        f"{company_name} {ticker} {ir_hint}"
    )
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
        return None

    search_results = data.get("search_results") or []
    if not search_results:
        log.debug("No search_results from Perplexity for %s", ticker)
        return None

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

        # PDF path
        if _PDF_RE.search(url_lower):
            text = _extract_pdf_text(raw)
            if text and _is_allowed_domain(url, ir_url, title, snippet, text):
                log.info("1A: Perplexity PDF hit for %s → %s", ticker, url)
                return text, url
            continue

        # HTML path
        html = raw.decode("utf-8", errors="replace")
        text = _strip_html(html)
        if (len(text) >= 500
                and re.search(r"revenue|earnings|quarter|operator", text, re.I)
                and _is_allowed_domain(url, ir_url, title, snippet, text)):
            log.info("1A: Perplexity HTML hit for %s → %s", ticker, url)
            return text, url

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
    return (text, url) if len(text) >= 200 else None


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
        "ir_transcript_pdf":              0.95,
        "sec_8k_exhibit":                 0.95,
        "sec_8k_exhibit_press_release":   0.95,
        "ir_press_release":               0.90,
        "fmp_transcript":                 0.85,
        "youtube_transcript":             0.70,
    }.get(source_type, 0.75)


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def fetch_transcript(ticker: str) -> Optional[dict]:
    """
    Fetch the most recent earnings transcript via priority waterfall.
    Returns None only if every source fails.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ir_discovery import get_ir_url, get_company_name

    ticker = ticker.upper()
    fiscal_year, fiscal_quarter, cal_period, reported_date = _fiscal_periods(ticker)

    # ── Cache check ──────────────────────────
    cached = _cache_get(ticker, fiscal_year, fiscal_quarter)
    if cached:
        log.info("%s: transcript cache hit (%s %s)", ticker, fiscal_year, fiscal_quarter)
        return {
            "ticker":          cached["ticker"],
            "source_type":     cached["source_type"],
            "source_url":      cached["source_url"],
            "raw_text":        cached["raw_text"],
            "fiscal_year":     cached["fiscal_year"],
            "fiscal_quarter":  cached["fiscal_quarter"],
            "calendar_period": cached["calendar_period"],
            "reported_date":   cached["reported_date"],
            "reliability":     _source_reliability(cached["source_type"]),
            "discovered_by":   "cache",
        }

    ir_url       = get_ir_url(ticker)
    company_name = get_company_name(ticker)

    result_text  = None
    source_type  = None
    source_url   = None
    discovered_by = None

    # 1A — Perplexity direct discovery
    log.info("%s: [1A] Perplexity transcript discovery …", ticker)
    out = _try_perplexity_transcript(ir_url, ticker, company_name)
    if out:
        result_text, source_url = out
        source_type   = "ir_transcript_pdf"
        discovered_by = "perplexity"

    # 1B — Static IR page HTML scraping
    if result_text is None and ir_url:
        log.info("%s: [1B] static IR page PDF scraping …", ticker)
        out = _try_ir_pdf(ir_url, ticker)
        if out:
            result_text, source_url = out
            source_type   = "ir_transcript_pdf"
            discovered_by = "direct"

    # 2 — IR press release
    if result_text is None and ir_url:
        log.info("%s: [2] IR press release …", ticker)
        out = _try_ir_press_release(ir_url, ticker)
        if out:
            result_text, source_url = out
            source_type   = "ir_press_release"
            discovered_by = "direct"

    # 3 — SEC 8-K (returns 3-tuple with source_type)
    if result_text is None:
        log.info("%s: [3] SEC 8-K exhibit …", ticker)
        out = _try_sec_8k(ticker)
        if out:
            result_text, source_url, source_type = out
            discovered_by = "sec_edgar"

    # 4 — FMP API
    if result_text is None:
        log.info("%s: [4] FMP API …", ticker)
        out = _try_fmp(ticker)
        if out:
            result_text, source_url = out
            source_type   = "fmp_transcript"
            discovered_by = "fmp"

    # 5 — YouTube
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

    reliability = _source_reliability(source_type)

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
        "ticker":          ticker,
        "source_type":     source_type,
        "source_url":      source_url,
        "raw_text":        result_text,
        "fiscal_year":     fiscal_year,
        "fiscal_quarter":  fiscal_quarter,
        "calendar_period": cal_period,
        "reported_date":   reported_date,
        "reliability":     reliability,
        "discovered_by":   discovered_by,
    }
