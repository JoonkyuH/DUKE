#!/usr/bin/env python3
"""
data_fetcher.py
Fetches real market data for a single ticker via yfinance and returns a dict
conforming to the Stage 01 raw_signal_record schema (schemas/input.json).

Entry point:
    fetch_market_data(ticker: str) -> dict

Only keys with actual values are included in price_data, relative_strength,
and earnings_data — absent keys let the screener's .get() defaults fire
cleanly rather than exploding on None comparisons.

Extended fields not in the schema (market_cap, 52-week range, 30-day volume
average) are nested under "extended_data".
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timezone, date
from typing import Optional

log = __import__("logging").getLogger("data_fetcher")


SECTOR_ETF_MAP = {
    "Technology":             "XLK",
    "Financial Services":     "XLF",
    "Energy":                 "XLE",
    "Healthcare":             "XLV",
    "Industrials":            "XLI",
    "Consumer Cyclical":      "XLY",
    "Consumer Defensive":     "XLP",
    "Basic Materials":        "XLB",
    "Communication Services": "XLC",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
}


def _nonempty(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def _rsi(closes, period: int = 14) -> Optional[float]:
    """Wilder's smoothed RSI from a pandas Series of closing prices."""
    if len(closes) < period + 1:
        return None
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = float(gain.iloc[:period].mean())
    avg_loss = float(loss.iloc[:period].mean())
    for i in range(period, len(gain)):
        avg_gain = (avg_gain * (period - 1) + float(gain.iloc[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(loss.iloc[i])) / period
    if avg_loss == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 2)


def _pct_change(series, n: int) -> Optional[float]:
    """n-day percentage return from the last data point."""
    if len(series) < n + 1:
        return None
    start = float(series.iloc[-(n + 1)])
    end   = float(series.iloc[-1])
    if start == 0:
        return None
    return round((end - start) / start * 100, 2)


def _atr(hist, period: int = 14) -> Optional[float]:
    """Average True Range over the trailing period."""
    if len(hist) < period + 1:
        return None
    highs  = hist["High"]
    lows   = hist["Low"]
    closes = hist["Close"]
    tr_vals = []
    for i in range(1, len(hist)):
        hl  = float(highs.iloc[i]) - float(lows.iloc[i])
        hpc = abs(float(highs.iloc[i]) - float(closes.iloc[i - 1]))
        lpc = abs(float(lows.iloc[i])  - float(closes.iloc[i - 1]))
        tr_vals.append(max(hl, hpc, lpc))
    if len(tr_vals) < period:
        return None
    return round(sum(tr_vals[-period:]) / period, 4)


def fetch_next_earnings_date(ticker: str) -> Optional[int]:
    """
    Return days from today to the nearest future earnings date via yfinance calendar.

    Primary path: returns the actual next earnings date from the calendar.

    Estimation fallback: when yfinance has only a past date (e.g., earnings just
    reported), estimates the next date as last_earnings_date + 91 days and logs
    the estimation. The fallback fires only when:
      - A past earnings date is present in the calendar
      - The estimated date is strictly in the future
      - The estimated date is no more than 120 days away (prevents stale data
        from producing absurd estimates)

    Returns None if no future date can be determined (actual or estimated).
    Handles both datetime.date and datetime.datetime objects returned by yfinance.
    """
    from datetime import timedelta
    try:
        cal = yf.Ticker(ticker.upper()).calendar
        if not isinstance(cal, dict):
            return None
        ed_val = cal.get("Earnings Date", [])
        if not isinstance(ed_val, list):
            ed_val = [ed_val]
        today_d = date.today()
        future = []
        past = []
        for d in ed_val:
            if hasattr(d, "date"):
                d = d.date()
            if isinstance(d, date):
                if d > today_d:
                    future.append(d)
                else:
                    past.append(d)
        if future:
            future.sort()
            return (future[0] - today_d).days
        # Estimation fallback: no future date found
        if past:
            past.sort(reverse=True)
            last_date = past[0]
            estimated = last_date + timedelta(days=91)
            days_est = (estimated - today_d).days
            if 0 < days_est <= 120:
                log.warning(
                    "%s: estimating next earnings ~91 days from last reported date %s",
                    ticker, last_date.isoformat(),
                )
                return days_est
        return None
    except Exception:
        log.warning("%s: fetch_next_earnings_date failed", ticker)
        return None


def _close_yf_ticker(t) -> None:
    """Release the curl_cffi/requests session that yf.Ticker keeps open.

    yfinance ≥0.2 backs each Ticker with a per-instance session (curl_cffi
    on the installed build) whose connection pool keeps idle HTTPS sockets
    alive. Without an explicit close those sockets persisted in the process,
    leaking ~3 IPv6 FDs per ticker on the screening loop.
    """
    try:
        t.session.close()
    except Exception:
        pass


def fetch_market_data(ticker: str) -> dict:
    """
    Fetch market data for ticker and return a raw_signal_record dict.

    Raises ValueError if yfinance returns no price history for the ticker.
    """
    ticker = ticker.upper()
    t = yf.Ticker(ticker)
    try:
        return _fetch_market_data_inner(ticker, t)
    finally:
        _close_yf_ticker(t)


def _fetch_market_data_inner(ticker: str, t) -> dict:
    hist = t.history(period="1y")
    if hist.empty:
        raise ValueError(f"No price history returned for {ticker!r}")

    info    = t.info or {}
    closes  = hist["Close"]
    volumes = hist["Volume"]
    today_d = date.today()

    current_price = float(closes.iloc[-1])

    # ── Moving averages ──────────────────────────────
    ma_20  = round(float(closes.tail(20).mean()),  4) if len(closes) >= 20  else None
    ma_50  = round(float(closes.tail(50).mean()),  4) if len(closes) >= 50  else None
    ma_200 = round(float(closes.tail(200).mean()), 4) if len(closes) >= 200 else None

    # ── Volume ───────────────────────────────────────
    vol = volumes.iloc[-1]
    if pd.isna(vol):
        log.warning("%s: volume_today is NaN — defaulting to 0", ticker)
        volume_today = 0
    else:
        volume_today = int(vol)
    volume_avg_20d = int(volumes.tail(20).mean()) if len(volumes) >= 20 else None
    volume_avg_30d = int(volumes.tail(30).mean()) if len(volumes) >= 30 else None
    volume_ratio   = round(volume_today / volume_avg_20d, 4) if volume_avg_20d else None

    # ── RSI and ATR ──────────────────────────────────
    rsi_14 = _rsi(closes, 14)
    atr_14 = _atr(hist, 14)

    # ── Price changes ────────────────────────────────
    change_1d_pct  = _pct_change(closes, 1)
    change_5d_pct  = _pct_change(closes, 5)
    change_20d_pct = _pct_change(closes, 20)

    # ── 52-week range ─────────────────────────────────
    week_52_high = round(float(closes.max()), 4)
    week_52_low  = round(float(closes.min()), 4)

    # ── Sector ───────────────────────────────────────
    sector_name = (info.get("sector") or "Unknown").strip()
    industry    = (info.get("industry") or "Unknown").strip()
    sector_etf  = SECTOR_ETF_MAP.get(sector_name)

    # ── Relative strength vs SPY ──────────────────────
    # SPY is currently re-fetched per ticker. A future optimization is to
    # hoist the SPY (and sector-ETF) fetch out of the per-ticker loop in
    # run_screening.py so we fetch them once per run. For now we still create
    # the Ticker per call but explicitly close its session afterwards.
    rs_vs_spy_10d = rs_vs_spy_20d = None
    spy_t = yf.Ticker("SPY")
    try:
        spy_closes = spy_t.history(period="1y")["Close"]
        if not spy_closes.empty:
            ticker_10d = _pct_change(closes, 10)
            ticker_20d = _pct_change(closes, 20)
            spy_10d    = _pct_change(spy_closes, 10)
            spy_20d    = _pct_change(spy_closes, 20)
            if ticker_10d is not None and spy_10d is not None:
                rs_vs_spy_10d = round(ticker_10d - spy_10d, 2)
            if ticker_20d is not None and spy_20d is not None:
                rs_vs_spy_20d = round(ticker_20d - spy_20d, 2)
    except Exception:
        pass
    finally:
        _close_yf_ticker(spy_t)

    # ── Relative strength vs sector ETF ───────────────
    rs_vs_sector_10d = rs_vs_sector_20d = None
    if sector_etf:
        sect_t = yf.Ticker(sector_etf)
        try:
            sect_closes = sect_t.history(period="1y")["Close"]
            if not sect_closes.empty:
                ticker_10d  = _pct_change(closes, 10)
                ticker_20d  = _pct_change(closes, 20)
                sect_10d    = _pct_change(sect_closes, 10)
                sect_20d    = _pct_change(sect_closes, 20)
                if ticker_10d is not None and sect_10d is not None:
                    rs_vs_sector_10d = round(ticker_10d - sect_10d, 2)
                if ticker_20d is not None and sect_20d is not None:
                    rs_vs_sector_20d = round(ticker_20d - sect_20d, 2)
        except Exception:
            pass
        finally:
            _close_yf_ticker(sect_t)

    # ── Earnings ─────────────────────────────────────
    next_earnings_date = days_to_earnings = None
    last_earnings_date = days_since_earnings = last_eps_surprise = None

    # Strategy 1: earnings_dates DataFrame (requires lxml)
    try:
        edates = t.earnings_dates
        if edates is not None and not edates.empty:
            future_dates = []
            past_dates   = []
            for idx in edates.index:
                d = idx.date() if hasattr(idx, "date") else idx
                if d > today_d:
                    future_dates.append((d, edates.loc[idx]))
                else:
                    past_dates.append((d, edates.loc[idx]))

            if future_dates:
                future_dates.sort(key=lambda x: x[0])
                next_d             = future_dates[0][0]
                next_earnings_date = next_d.isoformat()
                days_to_earnings   = (next_d - today_d).days

            if past_dates:
                past_dates.sort(key=lambda x: x[0], reverse=True)
                last_d, last_row    = past_dates[0]
                last_earnings_date  = last_d.isoformat()
                days_since_earnings = (today_d - last_d).days
                try:
                    surp = last_row["Surprise(%)"]
                    if surp is not None and str(surp) not in ("nan", "None", "NaN"):
                        last_eps_surprise = round(float(surp), 2)
                except (KeyError, TypeError, ValueError):
                    pass
    except Exception:
        pass

    # Strategy 2: calendar dict (no lxml needed)
    # Normalize datetime.datetime → datetime.date before comparison; yfinance
    # may return either type, and mixing them raises TypeError caught silently.
    if next_earnings_date is None:
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed_val = cal.get("Earnings Date", [])
                if not isinstance(ed_val, list):
                    ed_val = [ed_val]
                cal_dates = []
                for d in ed_val:
                    if hasattr(d, "date"):
                        d = d.date()
                    if isinstance(d, date):
                        cal_dates.append(d)
                future = sorted(d for d in cal_dates if d > today_d)
                if future:
                    next_d             = future[0]
                    next_earnings_date = next_d.isoformat()
                    days_to_earnings   = (next_d - today_d).days
                # Past calendar dates → last earnings proxy
                if last_earnings_date is None:
                    past = sorted(
                        (d for d in cal_dates if d <= today_d),
                        reverse=True,
                    )
                    if past:
                        last_d              = past[0]
                        last_earnings_date  = last_d.isoformat()
                        days_since_earnings = (today_d - last_d).days
        except Exception:
            pass

    # Strategy 3: info timestamps (earningsTimestamp / mostRecentQuarter)
    if next_earnings_date is None:
        try:
            ts = info.get("earningsTimestamp")
            if ts:
                next_d = datetime.utcfromtimestamp(int(ts)).date()
                if next_d >= today_d:
                    next_earnings_date = next_d.isoformat()
                    days_to_earnings   = (next_d - today_d).days
        except Exception:
            pass

    if last_earnings_date is None:
        try:
            ts = info.get("mostRecentQuarter")
            if ts:
                last_d = datetime.utcfromtimestamp(int(ts)).date()
                if last_d < today_d:
                    last_earnings_date  = last_d.isoformat()
                    days_since_earnings = (today_d - last_d).days
        except Exception:
            pass

    # Strategy 4: estimation fallback (+91 days from last reported date)
    # Fires when all strategies above failed to find a future earnings date but
    # a past date is known — e.g., earnings just reported and calendar not yet
    # updated with the next date.
    if days_to_earnings is None and last_earnings_date is not None:
        try:
            from datetime import timedelta
            last_d    = date.fromisoformat(last_earnings_date)
            estimated = last_d + timedelta(days=91)
            days_est  = (estimated - today_d).days
            if 0 < days_est <= 120:
                log.warning(
                    "%s: estimating next earnings ~91 days from last reported date %s",
                    ticker, last_earnings_date,
                )
                next_earnings_date = estimated.isoformat()
                days_to_earnings   = days_est
        except Exception:
            pass

    # ── Assemble output ───────────────────────────────
    price_data_raw = {
        "current_price":  round(current_price, 4),
        "change_1d_pct":  change_1d_pct,
        "change_5d_pct":  change_5d_pct,
        "change_20d_pct": change_20d_pct,
        "ma_20":          ma_20,
        "ma_50":          ma_50,
        "ma_200":         ma_200,
        "above_ma_20":    bool(current_price > ma_20)  if ma_20  is not None else None,
        "above_ma_50":    bool(current_price > ma_50)  if ma_50  is not None else None,
        "above_ma_200":   bool(current_price > ma_200) if ma_200 is not None else None,
        "volume_today":   volume_today,
        "volume_avg_20d": volume_avg_20d,
        "volume_ratio":   volume_ratio,
        "rsi_14":         rsi_14,
        "atr_14":         atr_14,
    }
    # current_price and volume_ratio are schema-required; keep them even if None
    price_data = {
        **_nonempty(price_data_raw),
        "current_price": price_data_raw["current_price"],
    }
    if volume_ratio is not None:
        price_data["volume_ratio"] = volume_ratio

    return {
        "ticker":      ticker,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "sector":      sector_etf,
        "sector_name": sector_name,
        "industry":    industry,
        "price_data": price_data,
        "relative_strength": _nonempty({
            "rs_vs_spy_10d":    rs_vs_spy_10d,
            "rs_vs_spy_20d":    rs_vs_spy_20d,
            "rs_vs_sector_10d": rs_vs_sector_10d,
            "rs_vs_sector_20d": rs_vs_sector_20d,
        }),
        "earnings_data": _nonempty({
            "next_earnings_date":    next_earnings_date,
            "days_to_earnings":      days_to_earnings,
            "last_earnings_date":    last_earnings_date,
            "days_since_earnings":   days_since_earnings,
            "last_eps_surprise_pct": last_eps_surprise,
        }),
        "extended_data": _nonempty({
            "market_cap":     info.get("marketCap"),
            "week_52_high":   week_52_high,
            "week_52_low":    week_52_low,
            "volume_avg_30d": volume_avg_30d,
            "sector_name":    sector_name,
        }),
    }


if __name__ == "__main__":
    import sys
    import json

    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = fetch_market_data(ticker_arg)
    print(json.dumps(result, indent=2, default=str))
