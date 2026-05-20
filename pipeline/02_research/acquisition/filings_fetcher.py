"""
filings_fetcher.py
SEC EDGAR filing acquisition for Stage 02.

Entry point:
    fetch_filings(ticker: str) -> tuple[list[dict], dict]

Returns:
    passages: list of passage dicts, each with:
        ticker, filing_type, filing_date, accession, section,
        passage_idx, passage_text, doc_url, reliability,
        source_type, source_priority, item_class
    metadata: {
        "10-K": {accession, filing_date, doc_url, passage_count} or None,
        "10-Q": {accession, filing_date, doc_url, passage_count} or None,
        "8-K":  [{accession, filing_date, doc_url, passage_count}, ...],
    }

Acquires:
    - Most recent 10-K (Item 1, 1A, 7, 7A)
    - Most recent 10-Q (Item 2, 3)
    - All earnings 8-Ks (item 2.02) filed after the most recent 10-Q date

Caching:
    filings_cache is a forever-cache — SEC filings are immutable once filed.
    Cache key: (ticker, accession, section, passage_idx)
"""

import json
import logging
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("filings_fetcher")

_DB_PATH      = Path(__file__).resolve().parent / "cache" / "duke_cache.db"
_REPO_ROOT    = Path(__file__).resolve().parent.parent.parent.parent
_HEADERS      = {"User-Agent": "DUKE-research contact@duke-research.ai"}
_EDGAR_SUBMIT = "https://data.sec.gov/submissions/CIK{cik}.json"

_MIN_PASSAGE = 1_000
_MAX_PASSAGE = 8_000

# 10-K sections: (item_id, section_key)
_SECTIONS_10K = [
    ("1",  "item_1_business"),
    ("1A", "item_1a_risk_factors"),
    ("7",  "item_7_mda"),
    ("7A", "item_7a_market_risk"),
]

# 10-Q sections: (item_id, section_key)
_SECTIONS_10Q = [
    ("2",  "item_2_mda"),
    ("3",  "item_3_market_risk"),
]

# All standard 10-K item IDs (used as stop boundaries)
_ALL_10K_IDS = [
    "1", "1A", "1B", "2", "3", "4", "5", "6",
    "7", "7A", "8", "9", "9A", "9B", "10", "11", "12", "13", "14", "15",
]

# All standard 10-Q Part II item IDs for stop boundaries
_ALL_10Q_IDS = ["1", "1A", "2", "3", "4", "5", "6"]

_RELIABILITY = {"sec_10k": 0.95, "sec_10q": 0.95, "sec_8k": 0.95}


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _ensure_table() -> None:
    with _db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS filings_cache (
                ticker       TEXT NOT NULL,
                accession    TEXT NOT NULL,
                section      TEXT NOT NULL,
                passage_idx  INTEGER NOT NULL,
                passage_text TEXT,
                filing_type  TEXT,
                filing_date  TEXT,
                doc_url      TEXT,
                fetched_at   TEXT,
                PRIMARY KEY (ticker, accession, section, passage_idx)
            )
        """)


def _cache_get_filing(ticker: str, accession: str) -> list:
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM filings_cache "
            "WHERE ticker=? AND accession=? ORDER BY section, passage_idx",
            (ticker.upper(), accession),
        ).fetchall()
    return [dict(r) for r in rows]


def _cache_write_passages(ticker: str, accession: str, passages: list) -> None:
    now = datetime.now(timezone.utc).isoformat()
    t   = ticker.upper()
    with _db() as con:
        for p in passages:
            con.execute(
                """INSERT OR IGNORE INTO filings_cache
                   (ticker, accession, section, passage_idx, passage_text,
                    filing_type, filing_date, doc_url, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    t, accession, p["section"], p["passage_idx"], p["passage_text"],
                    p.get("filing_type", ""), p.get("filing_date", ""),
                    p.get("doc_url", ""), now,
                ),
            )


# ─────────────────────────────────────────────
# EDGAR HELPERS
# ─────────────────────────────────────────────

def _get_cik(ticker: str) -> Optional[str]:
    try:
        sys.path.insert(0, str(_REPO_ROOT))
        from common.edgar_client import _cik
        return _cik(ticker)
    except Exception as exc:
        log.debug("CIK lookup failed for %s: %s", ticker, exc)
        return None


def _fetch_raw(url: str, max_bytes: int = 5_000_000) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(max_bytes)
    except Exception as exc:
        log.debug("fetch failed (%s): %s", url, exc)
        return None


def _get_submissions(cik: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(
            _EDGAR_SUBMIT.format(cik=cik), headers=_HEADERS
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as exc:
        log.warning("EDGAR submissions fetch failed: %s", exc)
        return None


# ─────────────────────────────────────────────
# SECTION EXTRACTION
# ─────────────────────────────────────────────

def _item_pat(item_id: str) -> re.Pattern:
    escaped = re.escape(item_id)
    return re.compile(rf"\bITEM\s+{escaped}(?=[.\s—–])", re.I)


def _extract_section(text: str, item_id: str, all_ids_after: list) -> Optional[str]:
    """
    Find the content block for item_id. Skips TOC entries (< 1,000 chars
    before the next boundary). Returns the first valid occurrence or None.
    """
    pat      = _item_pat(item_id)
    end_pats = [_item_pat(nid) for nid in all_ids_after]

    for m in pat.finditer(text):
        start = m.end()
        end   = len(text)
        for ep in end_pats:
            em = ep.search(text, start)
            if em and em.start() < end:
                end = em.start()

        content = text[start:end].strip()
        if len(content) < _MIN_PASSAGE:
            continue  # TOC entry — try next occurrence
        return content

    return None


def _split_passages(
    text: str, section: str, filing_type: str,
    filing_date: str, accession: str, doc_url: str,
) -> list:
    """
    Split section text into passages of 1K–8K chars at paragraph boundaries.
    """
    paragraphs = re.split(r"\n\n+", text.strip())
    passages   = []
    current    = []
    current_len = 0

    def _flush():
        chunk = "\n\n".join(current).strip()
        if len(chunk) >= _MIN_PASSAGE:
            passages.append({
                "section":      section,
                "passage_idx":  len(passages),
                "passage_text": chunk,
                "filing_type":  filing_type,
                "filing_date":  filing_date,
                "accession":    accession,
                "doc_url":      doc_url,
            })

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) > _MAX_PASSAGE and current:
            _flush()
            current     = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)

    if current:
        _flush()

    return passages


# ─────────────────────────────────────────────
# FILING-TYPE FETCHERS
# ─────────────────────────────────────────────

def _fetch_annual_or_quarterly(
    ticker: str, cik_bare: str, acc: str,
    form_type: str, filing_date: str, primary_doc: str,
) -> list:
    """Fetch, strip, section-extract, and split a 10-K or 10-Q filing."""
    acc_nodash = acc.replace("-", "")
    doc_url    = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_bare}"
        f"/{acc_nodash}/{primary_doc}"
    )
    log.info("%s: fetching %s %s → %s", ticker, form_type, acc, doc_url)

    raw = _fetch_raw(doc_url, max_bytes=8_000_000)
    if not raw:
        log.warning("%s: could not fetch %s primary doc", ticker, form_type)
        return []

    text = raw.decode("utf-8", errors="replace")

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transcript_fetcher import _strip_html
    if text.lstrip()[:100].lstrip().startswith("<"):
        text = _strip_html(text)

    sections_cfg = _SECTIONS_10K if form_type == "10-K" else _SECTIONS_10Q
    all_ids      = _ALL_10K_IDS   if form_type == "10-K" else _ALL_10Q_IDS

    passages = []
    for item_id, section_key in sections_cfg:
        idx_in_all  = all_ids.index(item_id) if item_id in all_ids else len(all_ids)
        ids_after   = all_ids[idx_in_all + 1:]
        content     = _extract_section(text, item_id, ids_after)
        if not content:
            log.debug("%s: %s %s — not found", ticker, form_type, section_key)
            continue
        log.info("%s: %s %s → %d chars", ticker, form_type, section_key, len(content))
        passages.extend(
            _split_passages(content, section_key, form_type, filing_date, acc, doc_url)
        )

    return passages


def _fetch_8k_passages(
    ticker: str, cik_bare: str, acc: str,
    filing_date: str, primary_doc: str,
) -> list:
    """
    Fetch an earnings 8-K. Tries the filing index for EX-99.1 first;
    falls back to primary doc.
    """
    acc_nodash = acc.replace("-", "")
    base       = f"https://www.sec.gov/Archives/edgar/data/{cik_bare}/{acc_nodash}/"

    # Try filing index for EX-99.1
    idx_url = f"{base}{acc}-index.htm"
    idx_raw = _fetch_raw(idx_url, max_bytes=200_000)
    doc_url = f"{base}{primary_doc}"  # default

    if idx_raw:
        idx_html = idx_raw.decode("utf-8", errors="replace")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from transcript_fetcher import _parse_filing_index
        docs = _parse_filing_index(idx_html)
        if docs:
            best_score, best_path, _, _ = docs[0]
            if best_score > 0:
                doc_url = "https://www.sec.gov" + best_path

    log.info("%s: fetching 8-K %s → %s", ticker, acc, doc_url)
    raw = _fetch_raw(doc_url, max_bytes=1_000_000)
    if not raw:
        return []

    text = raw.decode("utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from transcript_fetcher import _strip_html
    if text.lstrip()[:100].lstrip().startswith("<"):
        text = _strip_html(text)

    if len(text) < _MIN_PASSAGE:
        return []

    return _split_passages(text, "full_document", "8-K", filing_date, acc, doc_url)


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def fetch_filings(ticker: str) -> tuple:
    """
    Acquire SEC filings for ticker:
      - Most recent 10-K
      - Most recent 10-Q
      - All earnings 8-Ks (item 2.02) filed after the most recent 10-Q

    Returns:
        (passages, metadata)
    """
    _ensure_table()

    t   = ticker.upper()
    cik = _get_cik(t)
    if not cik:
        log.warning("%s: CIK not found — skipping filings", t)
        return [], {}

    cik_bare = str(int(cik))

    subs = _get_submissions(cik)
    if not subs:
        return [], {}

    filings      = subs.get("filings", {}).get("recent", {})
    forms        = filings.get("form", [])
    accessions   = filings.get("accessionNumber", [])
    primary_docs = filings.get("primaryDocument", [])
    filing_dates = filings.get("filingDate", [])
    items_list   = filings.get("items", [])

    # ── Locate most recent 10-K, 10-Q, and post-10-Q earnings 8-Ks ───
    latest_10k: Optional[dict] = None
    latest_10q: Optional[dict] = None

    for i, form in enumerate(forms):
        if form == "10-K" and latest_10k is None:
            latest_10k = {
                "accession":   accessions[i],
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
            }
        elif form == "10-Q" and latest_10q is None:
            latest_10q = {
                "accession":   accessions[i],
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
            }
        if latest_10k and latest_10q:
            break

    cutoff_date = latest_10q["filing_date"] if latest_10q else ""
    post_10q_8ks = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        item_str = items_list[i] if i < len(items_list) else ""
        if "2.02" not in item_str:
            continue
        fd = filing_dates[i] if i < len(filing_dates) else ""
        if cutoff_date and fd <= cutoff_date:
            break  # reverse-chrono — stop when we hit filings older than 10-Q
        post_10q_8ks.append({
            "accession":   accessions[i],
            "filing_date": fd,
            "primary_doc": primary_docs[i] if i < len(primary_docs) else "",
        })

    # ── Fetch / cache each filing ──────────────────────────────────────
    all_passages: list = []
    metadata: dict = {"10-K": None, "10-Q": None, "8-K": []}

    for form_type, filing_info in [("10-K", latest_10k), ("10-Q", latest_10q)]:
        if not filing_info:
            log.info("%s: no %s found in recent submissions", t, form_type)
            continue

        acc    = filing_info["accession"]
        cached = _cache_get_filing(t, acc)

        if cached:
            log.info("%s: %s %s — cache hit (%d passages)", t, form_type, acc, len(cached))
            raw_passages = cached
        else:
            raw_passages = _fetch_annual_or_quarterly(
                t, cik_bare, acc, form_type,
                filing_info["filing_date"], filing_info["primary_doc"],
            )
            if raw_passages:
                _cache_write_passages(t, acc, raw_passages)

        source_type = "sec_10k" if form_type == "10-K" else "sec_10q"
        enriched    = [
            {
                "ticker":          t,
                "filing_type":     form_type,
                "filing_date":     p.get("filing_date") or filing_info["filing_date"],
                "accession":       acc,
                "section":         p.get("section", ""),
                "passage_idx":     p.get("passage_idx", 0),
                "passage_text":    p.get("passage_text", ""),
                "doc_url":         p.get("doc_url", ""),
                "source_type":     source_type,
                "source_priority": "primary_sec",
                "item_class":      "filing_quote",
                "reliability":     _RELIABILITY[source_type],
            }
            for p in raw_passages
        ]
        all_passages.extend(enriched)
        first_url = enriched[0]["doc_url"] if enriched else ""
        metadata[form_type] = {
            "accession":    acc,
            "filing_date":  filing_info["filing_date"],
            "doc_url":      first_url,
            "passage_count": len(enriched),
        }
        log.info("%s: %s → %d passages", t, form_type, len(enriched))

    for filing_info in post_10q_8ks:
        acc    = filing_info["accession"]
        cached = _cache_get_filing(t, acc)

        if cached:
            log.info("%s: 8-K %s — cache hit (%d passages)", t, acc, len(cached))
            raw_passages = cached
        else:
            raw_passages = _fetch_8k_passages(
                t, cik_bare, acc,
                filing_info["filing_date"], filing_info["primary_doc"],
            )
            if raw_passages:
                _cache_write_passages(t, acc, raw_passages)

        enriched = [
            {
                "ticker":          t,
                "filing_type":     "8-K",
                "filing_date":     p.get("filing_date") or filing_info["filing_date"],
                "accession":       acc,
                "section":         p.get("section", ""),
                "passage_idx":     p.get("passage_idx", 0),
                "passage_text":    p.get("passage_text", ""),
                "doc_url":         p.get("doc_url", ""),
                "source_type":     "sec_8k",
                "source_priority": "primary_sec",
                "item_class":      "filing_quote",
                "reliability":     _RELIABILITY["sec_8k"],
            }
            for p in raw_passages
        ]
        all_passages.extend(enriched)
        first_url = enriched[0]["doc_url"] if enriched else ""
        metadata["8-K"].append({
            "accession":    acc,
            "filing_date":  filing_info["filing_date"],
            "doc_url":      first_url,
            "passage_count": len(enriched),
        })
        log.info("%s: 8-K %s → %d passages", t, acc, len(enriched))

    n_10k = sum(1 for p in all_passages if p["filing_type"] == "10-K")
    n_10q = sum(1 for p in all_passages if p["filing_type"] == "10-Q")
    n_8k  = sum(1 for p in all_passages if p["filing_type"] == "8-K")
    log.info(
        "%s: filings complete — %d passages total (10-K:%d  10-Q:%d  8-K:%d from %d filings)",
        t, len(all_passages), n_10k, n_10q, n_8k, len(post_10q_8ks),
    )
    return all_passages, metadata
