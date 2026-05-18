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

import yfinance as yf
from datetime import datetime, timezone, date
from typing import Optional


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


def fetch_market_data(ticker: str) -> dict:
    """
    Fetch market data for ticker and return a raw_signal_record dict.

    Raises ValueError if yfinance returns no price history for the ticker.
    """
    ticker = ticker.upper()
    t = yf.Ticker(ticker)

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
    volume_today   = int(volumes.iloc[-1])
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
    sector_name = info.get("sector", "")
    sector_etf  = SECTOR_ETF_MAP.get(sector_name)

    # ── Relative strength vs SPY ──────────────────────
    rs_vs_spy_10d = rs_vs_spy_20d = None
    try:
        spy_closes = yf.Ticker("SPY").history(period="1y")["Close"]
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

    # ── Relative strength vs sector ETF ───────────────
    rs_vs_sector_10d = rs_vs_sector_20d = None
    if sector_etf:
        try:
            sect_closes = yf.Ticker(sector_etf).history(period="1y")["Close"]
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

    # ── Earnings ─────────────────────────────────────
    next_earnings_date = days_to_earnings = None
    last_earnings_date = days_since_earnings = last_eps_surprise = None
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
        "ticker":    ticker,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sector":    sector_etf,
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
            "sector_name":    sector_name or None,
        }),
    }


if __name__ == "__main__":
    import sys
    import json

    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    result = fetch_market_data(ticker_arg)
    print(json.dumps(result, indent=2, default=str))
