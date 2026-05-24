"""
seed_ir_cache.py
Idempotent seed script for ir_cache rows that Perplexity cannot discover reliably.
Also provides seed_transcript_url() for seeding known-good earnings event page URLs
directly into transcript_cache (bypassing discovery).

Run from any directory:
    python3 pipeline/02_research/acquisition/seed_ir_cache.py
"""

import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

# ticker, company_name, ir_url, fiscal_year_end_month, calendar_quarter_offset, confidence
_SEEDS = [
    ("NVDA", "NVIDIA Corporation",
     "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx",
     1, 1, 0.99),
    ("PLTR", "Palantir Technologies Inc.",
     "https://investors.palantir.com/financials/quarterly-results",
     12, 0, 0.99),
    ("AVGO", "Broadcom Inc.",
     "https://investors.broadcom.com",
     10, 0, 0.99),
]


def seed() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with sqlite3.connect(_DB_PATH) as con:
        for ticker, company_name, ir_url, fye_month, cal_offset, confidence in _SEEDS:
            con.execute(
                """INSERT OR IGNORE INTO ir_cache
                   (ticker, company_name, ir_url, fiscal_year_end_month,
                    calendar_quarter_offset, discovered_by, last_verified_at,
                    status, confidence)
                   VALUES (?, ?, ?, ?, ?, 'seed', ?, 'active', ?)""",
                (ticker, company_name, ir_url, fye_month, cal_offset, today, confidence),
            )
            print(f"  {ticker}: seeded (or already present)")
    print("Done.")


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
    p = _S()
    p.feed(html)
    text = "".join(p.parts)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_SEED_HEADERS = {"User-Agent": "DUKE-research contact@duke-research.ai"}


def seed_transcript_url(
    ticker: str,
    url: str,
    fiscal_year: str,
    fiscal_quarter: str,
    source_type: str = "ir_earnings_event",
) -> None:
    """
    Write a known-good transcript/event-page URL directly into transcript_cache,
    bypassing discovery. Fetches the URL immediately to capture raw_text.

    If the fetch fails or returns < 2 000 chars, the entry is still written so
    that the cache key exists; the TTL (85 days) will force a waterfall re-fetch
    before the next quarter.

    Args:
        ticker:         Stock ticker (case-insensitive).
        url:            Direct URL to the earnings transcript or event page.
        fiscal_year:    e.g. "FY2026"
        fiscal_quarter: e.g. "Q1"
        source_type:    Cache source_type label (default: "ir_earnings_event").
    """
    ticker    = ticker.upper()
    cache_id  = f"{ticker}_{fiscal_year}_{fiscal_quarter}"

    # Best-effort calendar period from fiscal label
    try:
        fq_num  = int(fiscal_quarter.lstrip("Q"))
        fy_num  = int(fiscal_year.lstrip("FY"))
    except ValueError:
        fq_num, fy_num = 1, datetime.now().year
    end_month   = fq_num * 3
    cal_q       = (end_month - 1) // 3 + 1
    cal_period  = f"Q{cal_q} {fy_num}"
    rep_m       = end_month + 1 if end_month < 12 else 1
    rep_y       = fy_num if end_month < 12 else fy_num + 1
    reported_date = f"{rep_y}-{rep_m:02d}-15"

    # Fetch content
    raw_text = ""
    try:
        req = urllib.request.Request(url, headers=_SEED_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read(5_000_000)
        raw_text = _strip_html(raw.decode("utf-8", errors="replace"))
        print(f"  {ticker}: fetched {len(raw_text):,} chars from {url}")
    except Exception as exc:
        print(f"  {ticker}: WARNING — fetch failed ({exc}); seeding URL stub only")

    with sqlite3.connect(_DB_PATH) as con:
        con.execute(
            """INSERT OR REPLACE INTO transcript_cache
               (id, ticker, fiscal_year, fiscal_quarter, calendar_period,
                reported_date, source_type, source_url, raw_text, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cache_id, ticker, fiscal_year, fiscal_quarter, cal_period,
                reported_date, source_type, url, raw_text,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    print(
        f"  {ticker}: seeded transcript_cache [{cache_id}]"
        f"  source_type={source_type}  chars={len(raw_text):,}"
    )


if __name__ == "__main__":
    seed()
