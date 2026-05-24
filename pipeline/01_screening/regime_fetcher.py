#!/usr/bin/env python3
"""
regime_fetcher.py
Fetches live market regime indicators via yfinance and returns a dict
conforming to the regime_indicators contract expected by classify_regime().

Entry point:
    fetch_regime_indicators() -> dict

Indicators fetchable from yfinance:
  vix                — ^VIX spot price
  spy_20d_return     — SPY 20-day percentage return
  spy_vs_ma200       — bool: SPY above its 200-day simple MA
  sector_dispersion  — max-minus-min 20-day return across all 11 SPDR sector ETFs (%)
  breadth_adv_decline— (advancing_sectors + 1) / (declining_sectors + 1) on 14-day window
  earnings_season    — date heuristic: True during peak reporting weeks (Jan/Apr/Jul/Oct)

Not available from yfinance (returned as None; classifier defaults apply):
  hy_spread          — HY credit OAS in bps. yfinance exposes only HYG's distribution
                       yield (~120 bps implied spread), which systematically understates
                       the real OAS by 150-200 bps and would never trigger the 420+ bps
                       threshold. Needs a dedicated credit data feed (FRED, Bloomberg).
  fed_action_recent  — Recent Fed speech/decision. Needs a news or FOMC calendar feed.
"""

import logging
import os
import warnings
import yfinance as yf
from datetime import date, timedelta
from typing import Optional, Tuple

log = logging.getLogger(__name__)


SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLB", "XLC", "XLRE", "XLU"]

_EARNINGS_MONTHS = {1, 4, 7, 10}   # Jan/Apr/Jul/Oct are peak S&P 500 reporting months
_EARNINGS_WEEKS  = {2, 3, 4}        # weeks 2-4 of those months (1-indexed)


def _is_earnings_season() -> bool:
    """True during peak reporting weeks of Jan, Apr, Jul, Oct."""
    today = date.today()
    if today.month not in _EARNINGS_MONTHS:
        return False
    week_of_month = (today.day - 1) // 7 + 1
    return week_of_month in _EARNINGS_WEEKS


def _sector_metrics() -> Tuple[Optional[float], Optional[float], dict]:
    """
    Compute sector_dispersion, breadth_adv_decline, and per-ETF sector data
    from the 11 SPDR sector ETFs.

    sector_dispersion:
        Max-minus-min 20-day return across all sectors.

    breadth_adv_decline:
        Laplace-smoothed ratio: (sectors_up_14d + 1) / (sectors_down_14d + 1).

    sector_etf_data:
        Dict keyed by ETF ticker conforming to the screener's sector_data
        parameter: {"XLK": {"sector_rs_vs_spy_20d": 8.6}, "XLF": {...}, ...}
        SPY is included in the batch download to compute RS values in one call.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = yf.download(
            SECTOR_ETFS + ["SPY"], period="3mo", auto_adjust=True, progress=False
        )["Close"]

    spy_col  = data["SPY"].dropna() if "SPY" in data.columns else None
    spy_20d  = (
        (float(spy_col.iloc[-1]) - float(spy_col.iloc[-21])) / float(spy_col.iloc[-21]) * 100
        if spy_col is not None and len(spy_col) >= 21 else None
    )

    returns_20d    = {}
    pos_14d = neg_14d = 0
    sector_etf_data = {}

    for etf in SECTOR_ETFS:
        if etf not in data.columns:
            continue
        col = data[etf].dropna()
        if len(col) >= 21:
            r20 = (float(col.iloc[-1]) - float(col.iloc[-21])) / float(col.iloc[-21]) * 100
            returns_20d[etf] = r20
            if spy_20d is not None:
                sector_etf_data[etf] = {"sector_rs_vs_spy_20d": round(r20 - spy_20d, 2)}
        if len(col) >= 15:
            r14 = (float(col.iloc[-1]) - float(col.iloc[-15])) / float(col.iloc[-15]) * 100
            if r14 > 0:
                pos_14d += 1
            else:
                neg_14d += 1

    dispersion = (
        round(max(returns_20d.values()) - min(returns_20d.values()), 2)
        if len(returns_20d) >= 2 else None
    )
    breadth = round((pos_14d + 1) / (neg_14d + 1), 3) if (pos_14d + neg_14d) > 0 else None

    return dispersion, breadth, sector_etf_data


# Announcement dates (day 2 of each two-day FOMC meeting) for 2025–2027.
# Source: Federal Reserve published calendar.
_FOMC_DATES = [
    # 2025
    date(2025,  1, 29), date(2025,  3, 19), date(2025,  5,  7),
    date(2025,  6, 18), date(2025,  7, 30), date(2025,  9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    # 2026
    date(2026,  1, 28), date(2026,  3, 18), date(2026,  4, 29),
    date(2026,  6, 10), date(2026,  7, 29), date(2026,  9, 16),
    date(2026, 10, 28), date(2026, 12,  9),
    # 2027
    date(2027,  1, 27), date(2027,  3, 17), date(2027,  4, 28),
    date(2027,  6, 16), date(2027,  7, 28), date(2027,  9, 15),
    date(2027, 10, 27), date(2027, 12,  8),
]


def _is_fed_action_recent() -> Tuple[bool, Optional[str]]:
    """
    Return (True, meeting_date_iso) if today falls within the 14-day window
    [meeting_date, meeting_date + 14 days] for any scheduled FOMC date.
    Otherwise return (False, None).
    """
    today = date.today()
    for meeting in _FOMC_DATES:
        if meeting <= today <= meeting + timedelta(days=14):
            return True, str(meeting)
    return False, None


def fetch_regime_indicators() -> Tuple[dict, dict]:
    """
    Fetch live market regime indicators for classify_regime().

    Returns:
        (regime_indicators, sector_etf_data)

        regime_indicators — dict for classify_regime()
        sector_etf_data   — dict for the screener's sector_data parameter:
                            {"XLK": {"sector_rs_vs_spy_20d": 8.6}, ...}

    Makes three yfinance calls: SPY (1y history), ^VIX (5d history),
    and a batch download of all 11 sector ETFs + SPY (3mo history).
    """
    spy_hist       = yf.Ticker("SPY").history(period="1y")["Close"]
    spy_last       = float(spy_hist.iloc[-1])
    spy_20d_return = round((spy_last - float(spy_hist.iloc[-21])) / float(spy_hist.iloc[-21]) * 100, 2)
    spy_vs_ma200   = spy_last > float(spy_hist.tail(200).mean())

    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")["Close"]
        if vix_hist.empty:
            log.warning("VIX history empty — using default 20.0")
            vix = 20.0
        else:
            vix = round(float(vix_hist.iloc[-1]), 2)
    except Exception as exc:
        log.warning("VIX fetch failed (%s) — using default 20.0", exc)
        vix = 20.0

    sector_dispersion = breadth_adv_decline = None
    sector_etf_data: dict = {}
    try:
        sector_dispersion, breadth_adv_decline, sector_etf_data = _sector_metrics()
    except Exception as exc:
        log.warning("Sector metrics fetch failed: %s — regime classification using defaults", exc)

    # HY spread — live from FRED (BAMLH0A0HYM2)
    from fred_fetcher import fetch_hy_spread
    hy_spread = fetch_hy_spread()
    if hy_spread is not None:
        print(f"  HY spread: {hy_spread:.0f} bps (FRED)")
    else:
        reason = "FRED_API_KEY not set" if not os.environ.get("FRED_API_KEY") else "FRED fetch failed"
        print(f"  HY spread: None ({reason})")

    # Fed action — FOMC calendar window
    fed_recent, fomc_date = _is_fed_action_recent()
    if fed_recent:
        print(f"  Fed action recent: True (FOMC {fomc_date})")
    else:
        print(f"  Fed action recent: False")

    regime_indicators = {
        "vix":                 vix,
        "spy_20d_return":      spy_20d_return,
        "spy_vs_ma200":        spy_vs_ma200,
        "hy_spread":           hy_spread,
        "earnings_season":     _is_earnings_season(),
        "fed_action_recent":   fed_recent,
        "sector_dispersion":   sector_dispersion,
        "breadth_adv_decline": breadth_adv_decline,
    }
    return regime_indicators, sector_etf_data


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, ".")
    from regime_classifier import classify_regime

    print("Fetching live regime indicators...")
    indicators, sector_etf_data = fetch_regime_indicators()

    print("\nIndicators:")
    for k, v in indicators.items():
        print(f"  {k:<25} {v}")

    print("\nSector ETF RS vs SPY (20d):")
    for etf, d in sorted(sector_etf_data.items()):
        print(f"  {etf:<6}  {d['sector_rs_vs_spy_20d']:+.2f}%")

    regime = classify_regime(indicators)
    print(f"\nRegime:        {regime.regime.value}")
    print(f"Confidence:    {regime.confidence:.0%}")
    print(f"Min threshold: {regime.min_score_threshold}")
    print(f"Max shortlist: {regime.max_shortlist_size}")
    print(f"Description:   {regime.description}")
