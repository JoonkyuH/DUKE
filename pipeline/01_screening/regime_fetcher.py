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

import warnings
import yfinance as yf
from datetime import date
from typing import Optional, Tuple


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


def _sector_metrics() -> Tuple[Optional[float], Optional[float]]:
    """
    Compute sector_dispersion and breadth_adv_decline from the 11 SPDR sector ETFs.

    sector_dispersion:
        Max-minus-min 20-day return across all sectors. Measures how far apart
        the best and worst-performing sectors are — high dispersion signals
        rotation or stress rather than broad-based moves.

    breadth_adv_decline:
        Laplace-smoothed ratio: (sectors_up_14d + 1) / (sectors_down_14d + 1).
        > 1.0  → more sectors advancing than declining (broad participation)
        < 1.0  → more declining sectors (narrow or deteriorating breadth)
        Uses +1 smoothing so all-up or all-down markets produce a finite ratio.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = yf.download(
            SECTOR_ETFS, period="3mo", auto_adjust=True, progress=False
        )["Close"]

    returns_20d = []
    pos_14d = neg_14d = 0

    for etf in SECTOR_ETFS:
        if etf not in data.columns:
            continue
        col = data[etf].dropna()
        if len(col) >= 21:
            r20 = (float(col.iloc[-1]) - float(col.iloc[-21])) / float(col.iloc[-21]) * 100
            returns_20d.append(r20)
        if len(col) >= 15:
            r14 = (float(col.iloc[-1]) - float(col.iloc[-15])) / float(col.iloc[-15]) * 100
            if r14 > 0:
                pos_14d += 1
            else:
                neg_14d += 1

    dispersion = round(max(returns_20d) - min(returns_20d), 2) if len(returns_20d) >= 2 else None
    breadth    = round((pos_14d + 1) / (neg_14d + 1), 3)      if (pos_14d + neg_14d) > 0 else None

    return dispersion, breadth


def fetch_regime_indicators() -> dict:
    """
    Fetch live market regime indicators for classify_regime().

    Makes three yfinance calls: SPY (1y history), ^VIX (5d history),
    and a batch download of all 11 sector ETFs (3mo history).
    """
    spy_hist       = yf.Ticker("SPY").history(period="1y")["Close"]
    spy_last       = float(spy_hist.iloc[-1])
    spy_20d_return = round((spy_last - float(spy_hist.iloc[-21])) / float(spy_hist.iloc[-21]) * 100, 2)
    spy_vs_ma200   = spy_last > float(spy_hist.tail(200).mean())

    vix = round(float(yf.Ticker("^VIX").history(period="5d")["Close"].iloc[-1]), 2)

    sector_dispersion = breadth_adv_decline = None
    try:
        sector_dispersion, breadth_adv_decline = _sector_metrics()
    except Exception:
        pass

    return {
        "vix":                 vix,
        "spy_20d_return":      spy_20d_return,
        "spy_vs_ma200":        spy_vs_ma200,
        "hy_spread":           None,
        "earnings_season":     _is_earnings_season(),
        "fed_action_recent":   None,
        "sector_dispersion":   sector_dispersion,
        "breadth_adv_decline": breadth_adv_decline,
    }


if __name__ == "__main__":
    import json
    import sys
    sys.path.insert(0, ".")
    from regime_classifier import classify_regime

    print("Fetching live regime indicators...")
    indicators = fetch_regime_indicators()

    print("\nIndicators:")
    for k, v in indicators.items():
        print(f"  {k:<25} {v}")

    regime = classify_regime(indicators)
    print(f"\nRegime:        {regime.regime.value}")
    print(f"Confidence:    {regime.confidence:.0%}")
    print(f"Min threshold: {regime.min_score_threshold}")
    print(f"Max shortlist: {regime.max_shortlist_size}")
    print(f"Description:   {regime.description}")
