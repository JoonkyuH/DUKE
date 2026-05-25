"""
economic_profile_classifier.py
Classifies a ticker's economic profile and returns per-profile scoring multipliers.

Classification priority order:
  1. ticker_override       (confidence 1.0)  — manually curated exceptions
  2. gics_industry_pattern (confidence 0.85) — yfinance industry string lookup
  3. financial_signature   (confidence 0.60) — hard-threshold fallback on metrics
  4. unknown               (confidence 0.0)  — neutral multipliers, review queue

Public API:
  classify(ticker, metrics=None) -> dict
  get_multipliers(economic_profile) -> dict
  get_disabled_signals(economic_profile) -> list[str]
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("economic_profile_classifier")

_DIR = Path(__file__).resolve().parent
_PROFILES_PATH   = _DIR / "economic_profiles.json"
_ADJUSTMENTS_PATH = _DIR / "scoring_adjustments.json"
_CACHE_DB        = _DIR / "duke_cache.db"

# ── In-memory JSON cache ─────────────────────────────────────────────────────

_profiles_data:     dict = {}
_adjustments_data:  dict = {}
_profiles_mtime:    float = 0.0
_adjustments_mtime: float = 0.0


def _reload_if_stale() -> None:
    global _profiles_data, _adjustments_data, _profiles_mtime, _adjustments_mtime

    try:
        mt = _PROFILES_PATH.stat().st_mtime
        if mt != _profiles_mtime:
            with open(_PROFILES_PATH) as f:
                _profiles_data = json.load(f)
            _profiles_mtime = mt
    except Exception as exc:
        log.error("Failed to load economic_profiles.json: %s", exc)

    try:
        mt = _ADJUSTMENTS_PATH.stat().st_mtime
        if mt != _adjustments_mtime:
            with open(_ADJUSTMENTS_PATH) as f:
                _adjustments_data = json.load(f)
            _adjustments_mtime = mt
    except Exception as exc:
        log.error("Failed to load scoring_adjustments.json: %s", exc)


# ── SQLite cache ─────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_sector_cache (
            ticker       TEXT PRIMARY KEY,
            gics_sector  TEXT,
            gics_industry TEXT,
            fetched_at   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS classification_review_queue (
            ticker                   TEXT,
            classification_method    TEXT,
            economic_profile         TEXT,
            classification_confidence REAL,
            queued_at                TEXT,
            reviewed                 INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def _cache_gics(ticker: str, sector: Optional[str], industry: Optional[str]) -> None:
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO ticker_sector_cache "
            "(ticker, gics_sector, gics_industry, fetched_at) VALUES (?, ?, ?, datetime('now'))",
            (ticker, sector, industry),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("%s: failed to cache GICS data: %s", ticker, exc)


def _read_gics_cache(ticker: str) -> Optional[tuple]:
    try:
        conn = _get_conn()
        row = conn.execute(
            "SELECT gics_sector, gics_industry FROM ticker_sector_cache WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        conn.close()
        return row
    except Exception:
        return None


def _enqueue_review(ticker: str, method: str, profile: str, confidence: float) -> None:
    try:
        conn = _get_conn()
        if conn.execute(
            "SELECT 1 FROM classification_review_queue WHERE ticker = ?",
            (ticker,),
        ).fetchone():
            conn.close()
            return
        conn.execute(
            "INSERT INTO classification_review_queue "
            "(ticker, classification_method, economic_profile, classification_confidence, queued_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (ticker, method, profile, confidence),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("%s: failed to enqueue review: %s", ticker, exc)


# ── GICS fetch with retry ────────────────────────────────────────────────────

def fetch_gics(ticker: str) -> tuple:
    """
    Return (gics_sector, gics_industry) for ticker.
    Checks SQLite cache first; fetches from yfinance on miss.
    Three attempts with 1s/2s/4s backoff on failure.
    Returns (None, None) if all attempts fail.
    """
    cached = _read_gics_cache(ticker)
    if cached is not None:
        return cached

    import yfinance as yf

    delays = [1, 2, 4]
    for attempt, delay in enumerate(delays, start=1):
        try:
            info = yf.Ticker(ticker.upper()).info or {}
            sector   = (info.get("sector")   or "").strip() or None
            industry = (info.get("industry") or "").strip() or None
            _cache_gics(ticker, sector, industry)
            return (sector, industry)
        except Exception as exc:
            if attempt < len(delays):
                log.warning(
                    "%s: fetch_gics attempt %d failed (%s) — retrying in %ds",
                    ticker, attempt, exc, delay,
                )
                time.sleep(delay)
            else:
                log.warning("%s: fetch_gics failed after %d attempts: %s", ticker, attempt, exc)

    _cache_gics(ticker, None, None)
    return (None, None)


# ── Classification ───────────────────────────────────────────────────────────

def _financial_signature_match(metrics: dict) -> Optional[str]:
    """
    Check financial_signature_fallback rules from economic_profiles.json.
    Evaluates all profiles against the metrics dict and returns the first match,
    or None if no profile matches.
    Metrics values are percentages (e.g., gm_ann=65.0 not 0.65).
    """
    fallback = _profiles_data.get("financial_signature_fallback", {})

    for profile, rules in fallback.items():
        match = True
        for rule_key, rule_val in rules.items():
            if rule_key == "gross_margin_min":
                gm = metrics.get("gm_ann")
                if gm is None or (gm / 100.0) < rule_val:
                    match = False; break
            elif rule_key == "gross_margin_max":
                gm = metrics.get("gm_ann")
                if gm is None or (gm / 100.0) > rule_val:
                    match = False; break
            elif rule_key == "revenue_growth_min":
                rg = metrics.get("rev_growth")
                if rg is None or (rg / 100.0) < rule_val:
                    match = False; break
            elif rule_key == "revenue_growth_max":
                rg = metrics.get("rev_growth")
                if rg is None or (rg / 100.0) > rule_val:
                    match = False; break
            elif rule_key == "fcf_margin_min":
                fm = metrics.get("fcf_margin")
                if fm is None or (fm / 100.0) < rule_val:
                    match = False; break
            elif rule_key == "fcf_margin_max":
                fm = metrics.get("fcf_margin")
                if fm is None or (fm / 100.0) > rule_val:
                    match = False; break
        if match:
            return profile

    return None


def classify(ticker: str, metrics: Optional[dict] = None) -> dict:
    """
    Classify ticker's economic profile. Returns an explainable classification dict.

    Args:
        ticker  — uppercase ticker symbol
        metrics — optional output of compute_fundamental_metrics() (needed only
                  for financial_signature fallback path)

    Returns:
        {
          "economic_profile":          str,
          "classification_method":     str,
          "classification_confidence": float,
          "classification_rationale":  str,
          "raw_gics_sector":           str | None,
          "raw_gics_industry":         str | None,
        }
    """
    _reload_if_stale()
    ticker = ticker.upper()

    # ── 1. Ticker override ───────────────────────────────────────────────────
    overrides = _profiles_data.get("ticker_overrides", {})
    if ticker in overrides:
        ov = overrides[ticker]
        return {
            "economic_profile":          ov["profile"],
            "classification_method":     "ticker_override",
            "classification_confidence": 1.0,
            "classification_rationale":  ov.get("rationale", "Manual override"),
            "raw_gics_sector":           None,
            "raw_gics_industry":         None,
        }

    # ── 2. GICS industry pattern match ──────────────────────────────────────
    gics_sector, gics_industry = fetch_gics(ticker)
    patterns = _profiles_data.get("gics_industry_patterns", {})

    if gics_industry and gics_industry in patterns:
        profile = patterns[gics_industry]
        return {
            "economic_profile":          profile,
            "classification_method":     "gics_pattern",
            "classification_confidence": 0.85,
            "classification_rationale":  (
                f"GICS industry '{gics_industry}' maps to {profile}"
            ),
            "raw_gics_sector":           gics_sector,
            "raw_gics_industry":         gics_industry,
        }

    # ── 3. Financial signature fallback (advisory only) ──────────────────────
    # Logs the suggested profile and enqueues it for review, but does NOT use
    # it for scoring. The ticker resolves to unknown with neutral multipliers.
    # This prevents confidently-wrong classifications (e.g. UNH scoring as
    # semiconductor_platform because its gross margin passes the threshold)
    # from corrupting signal scores. Add the ticker's GICS industry string to
    # gics_industry_patterns to resolve it correctly on the next run.
    if metrics:
        sig_profile = _financial_signature_match(metrics)
        if sig_profile:
            log.warning(
                "%s: financial signature suggests %s "
                "(GICS: %s / %s) — resolving to unknown. "
                "Add to gics_industry_patterns to fix.",
                ticker, sig_profile,
                gics_sector or "unknown", gics_industry or "unknown",
            )
            _enqueue_review(ticker, "financial_signature", sig_profile, 0.60)
            # Fall through to unknown — financial_signature is advisory only.

    # ── 4. Unknown ───────────────────────────────────────────────────────────
    log.warning(
        "%s: economic profile unknown — neutral multipliers applied",
        ticker,
    )
    _enqueue_review(ticker, "unknown", "unknown", 0.0)
    return {
        "economic_profile":          "unknown",
        "classification_method":     "unknown",
        "classification_confidence": 0.0,
        "classification_rationale":  (
            f"No match found (GICS: {gics_sector or 'unknown'} / {gics_industry or 'unknown'})"
        ),
        "raw_gics_sector":           gics_sector,
        "raw_gics_industry":         gics_industry,
    }


# ── Multiplier access ────────────────────────────────────────────────────────

def get_multipliers(economic_profile: str) -> dict:
    """
    Return the scoring adjustments dict for the given economic profile.
    Null values are returned as Python None so callers can skip disabled signals.
    Falls back to 'unknown' (all 1.0) if the profile is not found.
    """
    _reload_if_stale()
    adjustments = _adjustments_data.get("adjustments", {})
    profile_adj = adjustments.get(economic_profile) or adjustments.get("unknown", {})
    return {k: v for k, v in profile_adj.items()}


def get_disabled_signals(economic_profile: str) -> list:
    """
    Return list of signal names that are structurally invalid for this profile.
    e.g., ["gross_margin", "fcf_margin"] for banking.
    Returns empty list if no special handling.
    """
    _reload_if_stale()
    special = _profiles_data.get("special_handling", {})
    return special.get(economic_profile, {}).get("disabled_signals", [])


def is_commodity_cyclical(economic_profile: str) -> bool:
    """
    Return True if the profile is a commodity price-taker (energy upstream,
    integrated, or midstream). These businesses cannot be long-term compounders:
    cash flows are driven by a commodity price the company does not control, so
    peak-cycle FCF must never be scored as durable compounding.

    Sourced from economic_profiles.json -> commodity_cyclical_profiles.
    """
    _reload_if_stale()
    cyclical = _profiles_data.get("commodity_cyclical_profiles", [])
    return economic_profile in cyclical
