"""
earningscall_fetcher.py
EarningsCall API integration for DUKE transcript acquisition.

Entry point:
    fetch_earningscall_transcript(ticker, company_name=None) -> dict | None

Returns a transcript dict compatible with fetch_transcript()'s return format,
plus a "speakers" list with per-segment speaker attribution.
"""

import logging
import os
import re
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("earningscall_fetcher")

_DB_PATH = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

# Module-level state
_api_key_warned: bool = False
_all_companies_cache = None          # populated at most once per process


# ─────────────────────────────────────────────
# API KEY
# ─────────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    global _api_key_warned
    key = os.environ.get("EARNINGSCALL_API_KEY")
    if not key and not _api_key_warned:
        log.warning(
            "EARNINGSCALL_API_KEY not set — EarningsCall Priority 0 disabled"
        )
        _api_key_warned = True
    return key


# ─────────────────────────────────────────────
# NAME NORMALISATION
# ─────────────────────────────────────────────

_LEGAL_SUFFIXES = re.compile(
    r"\b(incorporated|corporation|company|limited|inc|corp|ltd|llc|co)\b\.?",
    re.I,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE    = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    name = name.lower()
    name = _LEGAL_SUFFIXES.sub("", name)
    name = _PUNCT_RE.sub("", name)
    name = _WS_RE.sub(" ", name).strip()
    return name


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def _get_db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_alias_cache (
            original_ticker TEXT PRIMARY KEY,
            resolved_ticker TEXT,
            company_name    TEXT,
            cached_at       TEXT
        )
    """)
    conn.commit()
    return conn


def _read_alias_cache(ticker: str) -> Optional[str]:
    try:
        conn = _get_db_conn()
        row = conn.execute(
            "SELECT resolved_ticker FROM ticker_alias_cache WHERE original_ticker = ?",
            (ticker,),
        ).fetchone()
        conn.close()
        return row["resolved_ticker"] if row else None
    except Exception:
        return None


def _write_alias_cache(original: str, resolved: str, company_name: str) -> None:
    try:
        conn = _get_db_conn()
        conn.execute(
            "INSERT OR REPLACE INTO ticker_alias_cache "
            "(original_ticker, resolved_ticker, company_name, cached_at) "
            "VALUES (?, ?, ?, datetime('now'))",
            (original, resolved, company_name),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("%s: alias cache write failed: %s", original, exc)


# ─────────────────────────────────────────────
# COMPANY RESOLUTION
# ─────────────────────────────────────────────

def _resolve_company(ticker: str, company_name: Optional[str] = None):
    """
    Resolution order (design decision #5):
      a. earningscall.get_company(ticker) directly
      b. ticker_alias_cache lookup
      c. get_all_companies() name-matching (once per process)
      d. None — fall through
    Returns an earningscall Company object or None.
    """
    global _all_companies_cache
    import earningscall

    # a. Direct lookup
    company = earningscall.get_company(ticker)
    if company is not None:
        return company

    # b. Alias cache
    cached_alias = _read_alias_cache(ticker)
    if cached_alias:
        company = earningscall.get_company(cached_alias)
        if company is not None:
            log.info("%s: resolved via alias cache → %s", ticker, cached_alias)
            return company

    # c. Name-matching against full company list
    if company_name:
        if _all_companies_cache is None:
            try:
                _all_companies_cache = list(earningscall.get_all_companies() or [])
                log.info(
                    "EarningsCall: loaded %d companies from get_all_companies()",
                    len(_all_companies_cache),
                )
            except Exception as exc:
                log.warning("get_all_companies() failed: %s", exc)
                _all_companies_cache = []

        norm_target = _normalize_name(company_name)
        for co in _all_companies_cache:
            # Company objects may expose .name or .__str__
            co_name = getattr(co, "name", None) or str(co)
            norm_co = _normalize_name(co_name)
            if norm_co == norm_target or norm_co.startswith(norm_target):
                # Get the ticker from the company object
                co_info   = getattr(co, "company_info", None)
                co_ticker = getattr(co_info, "symbol", None) if co_info else None
                if co_ticker:
                    resolved = earningscall.get_company(co_ticker)
                    if resolved is not None:
                        log.info(
                            "%s: resolved via name match '%s' → %s",
                            ticker, co_name, co_ticker,
                        )
                        _write_alias_cache(ticker, co_ticker, company_name)
                        return resolved

    # d. Not found
    log.info("%s: EarningsCall company not found", ticker)
    return None


# ─────────────────────────────────────────────
# EVENT SELECTION
# ─────────────────────────────────────────────

def _get_latest_past_event(company):
    """
    Return the most recent event whose conference_date <= today.
    Handles both date and datetime objects from the SDK.
    """
    try:
        events = company.events()
    except Exception as exc:
        log.warning("company.events() failed: %s", exc)
        return None

    if not events:
        return None

    today = date.today()
    past_events = []
    for ev in events:
        conf = ev.conference_date
        if hasattr(conf, "date"):
            conf = conf.date()
        if isinstance(conf, date) and conf <= today:
            past_events.append((conf, ev))

    if not past_events:
        return None

    past_events.sort(key=lambda x: x[0], reverse=True)
    return past_events[0][1]


# ─────────────────────────────────────────────
# SPEAKER LIST BUILDER
# ─────────────────────────────────────────────

def _build_speakers_list(transcript) -> list:
    """
    Convert EarningsCall Speaker objects to DUKE speaker dicts (design decision #4).

    is_management = True when:
      - name is not "?" and not "Operator"
      - "Analyst" not in title
      - "Investor Relations" not in title

    is_qa = True for all segments from the first point where an analyst/unknown
    speaker appears AFTER at least one management segment.
    """
    speakers = getattr(transcript, "speakers", None)
    if not speakers:
        return []

    result = []
    seen_management = False
    qa_started = False

    for seg in speakers:
        info = getattr(seg, "speaker_info", None)
        name  = (getattr(info, "name",  None) or "?").strip()
        title = (getattr(info, "title", None) or "?").strip()
        text  = (getattr(seg,  "text",  None) or "").strip()

        is_mgmt = (
            name not in ("?", "Operator", "")
            and "Analyst" not in title
            and "Investor Relations" not in title
        )

        if is_mgmt:
            seen_management = True

        # Q&A starts at the first analyst/unknown segment after management has spoken
        if seen_management and not is_mgmt and not qa_started:
            qa_started = True

        result.append({
            "speaker_id":    getattr(seg, "speaker", "?"),
            "name":          name,
            "title":         title,
            "text":          text,
            "is_management": is_mgmt,
            "is_qa":         qa_started,
        })

    return result


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def fetch_earningscall_transcript(
    ticker: str,
    company_name: Optional[str] = None,
) -> Optional[dict]:
    """
    Fetch the most recent past earnings call transcript from EarningsCall API.

    Returns a transcript dict with a "speakers" field, or None on any failure.
    Never raises — all errors are caught and logged.
    """
    try:
        api_key = _get_api_key()
        if not api_key:
            return None

        import earningscall
        earningscall.api_key = api_key

        ticker_upper = ticker.upper()

        company = _resolve_company(ticker_upper, company_name)
        if company is None:
            return None

        event = _get_latest_past_event(company)
        if event is None:
            log.info("%s: no past EarningsCall events found", ticker_upper)
            return None

        transcript = company.get_transcript(
            year=event.year,
            quarter=event.quarter,
            level=2,
        )
        if transcript is None:
            log.info(
                "%s: EarningsCall returned None for FY%s Q%s",
                ticker_upper, event.year, event.quarter,
            )
            return None

        speakers_list = _build_speakers_list(transcript)

        # Conference date (normalise to date object)
        conf = event.conference_date
        if hasattr(conf, "date"):
            conf = conf.date()
        conf_str = conf.isoformat() if isinstance(conf, date) else str(conf)

        has_q_and_a = any(s["is_qa"] for s in speakers_list)

        raw_text = transcript.text or ""

        log.info(
            "%s: EarningsCall FY%s Q%s — %d chars, %d speaker segments, q_and_a=%s",
            ticker_upper, event.year, event.quarter,
            len(raw_text), len(speakers_list), has_q_and_a,
        )

        return {
            "ticker":           ticker_upper,
            "source_type":      "earningscall_api",
            "document_subtype": "earnings_call_transcript",
            "source_url":       "",
            "reliability":      0.95,
            "discovered_by":    "earningscall_api",
            "fiscal_year":      f"FY{event.year}",
            "fiscal_quarter":   f"Q{event.quarter}",
            "calendar_period":  None,
            "reported_date":    conf_str,
            "has_q_and_a":      has_q_and_a,
            "conference_date":  conf_str,
            "raw_text":         raw_text,
            "speakers":         speakers_list,
        }

    except Exception as exc:
        log.warning("%s: fetch_earningscall_transcript failed: %s", ticker, exc)
        return None
