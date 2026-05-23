#!/usr/bin/env python3
"""
backtest_runner.py
Stage 01 screener backtest — every Friday, 2013-01-01 to 2024-12-31.

Design:
  Universe:  Point-in-time S&P 500 (get_sp500_tickers_as_of) every date.
  EDGAR:     as_of filter on every date — no lookahead from later filings.
  Cadence:   Every Friday; ~625 test dates across 12 calendar years.
  Horizons:  1, 3, 6, 12 months (equal-weighted shortlist vs SPY total return).
  Cost:      0.2% one-time entry per position, deducted from shortlist return.
  Delisting: Three-way: priced / known-wipeout (−100%) / unresolved (flagged,
             excluded from average pending manual classification).

Entry-price discipline:
  Screening signals (price, 52w range, EDGAR fundamentals) are computed as-of
  Friday close — the last data available before the decision is made.
  Forward returns are measured from the NEXT trading day's adjusted close
  (normally Monday; Tuesday if Monday is a holiday; steps forward until a
  trading day is found). This prevents using Friday's close as both the
  signal and the entry price, which would be impossible to execute in practice.

Overlapping-window statistics:
  Consecutive weekly observations share (h − 1) weeks of return overlap for
  horizon h. They are NOT treated as independent.
  · Newey-West HAC standard errors, bandwidth = h − 1 (Bartlett kernel).
    Theoretically correct for overlapping returns (Hansen-Hodrick 1980).
  · Circular block bootstrap (B = 4999) for 95% confidence intervals on mean
    excess return. Block length = max(h_weeks, floor(T^(1/3))).
  · Effective sample size: ESS = T × S₀ / V_NW (ratio of naive to long-run
    variance), quantifying how many independent observations we effectively have.

Per-date outputs: regime classification, shortlist, four horizon returns.
Summary outputs: per-horizon mean excess / NW SE / CI / hit rate / max DD / IR,
                 plus a per-regime breakdown table (all 6 regimes × all 4 horizons).

Known limitation (inherited from v1): edgar_client._entries() requires a concept
  to have at least one filing with end >= "2020-01-01". Companies delisted or
  acquired before 2020 will return empty fundamentals and score ~0, effectively
  excluding them. This creates mild survivorship bias toward long-lived companies
  in pre-2020 test dates.

Secondary regime inputs held constant at documented defaults:
  hy_spread = 350 bps, sector_dispersion = 10.0%, breadth_adv_decline = 1.0.
  fed_action_recent = False for all dates (no per-date FOMC calendar available).
  earnings_season is inferred from the calendar date (peak reporting windows).

Requires: yfinance  (pip install yfinance)
Run:
    cd pipeline/01_screening
    python3 backtest_runner.py
"""

import sys
import math
import random
import calendar
from pathlib import Path
from datetime import date, timedelta
from typing import Optional

_HERE   = Path(__file__).resolve().parent
_COMMON = _HERE.parent.parent / "common"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_COMMON))


# ═══════════════════════════════════════════════════════════════════════════
# PRE-GATE — must pass before any backtest work
# ═══════════════════════════════════════════════════════════════════════════

from validate_historical_universe import validate

print("Validating historical S&P 500 constituent data …", flush=True)
if not validate(silent=True):
    print("\nABORT: Constituent data failed validation. "
          "Fix issues and re-run before running the backtest.")
    sys.exit(1)
print("Validation passed.\n", flush=True)


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════

from universe.sp500_historical import get_sp500_tickers_as_of
from edgar_client import fetch_financials, prefetch_facts
from screener import run_screening
from regime_classifier import MarketRegime

try:
    import yfinance as yf
    import pandas as pd
except ImportError as exc:
    print(f"ERROR: Missing dependency — {exc}")
    print("Install with: pip install yfinance pandas")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# PARAMETERS
# ═══════════════════════════════════════════════════════════════════════════

_START_DATE = date(2013, 1, 1)
_END_DATE   = date(2024, 12, 31)

# Forward-return horizons. weeks drives statistical calculations (NW bandwidth,
# block length, IR annualisation). Actual exit dates use calendar-month offsets.
_HORIZONS: dict[str, dict] = {
    "1m":  {"months": 1,  "weeks": 4,  "label": "1-month "},
    "3m":  {"months": 3,  "weeks": 13, "label": "3-month "},
    "6m":  {"months": 6,  "weeks": 26, "label": "6-month "},
    "12m": {"months": 12, "weeks": 52, "label": "12-month"},
}

_COST = 0.002  # 0.2% one-time entry per position

# Price history range: needs ~200 trading days of MA lookback before the first
# test date, and covers 12-month exits from the last test date (Dec 2024 + 12m).
_PRICE_START = "2012-03-01"
_PRICE_END   = "2026-02-01"

# Block bootstrap parameters (B = 4999 gives stable 95% CIs)
_BOOTSTRAP_REPS = 4999
_BOOTSTRAP_SEED = 42

# ── Secondary regime indicator defaults ──────────────────────────────────
# VIX, SPY 20-day return, and SPY vs 200-day MA are computed per date from
# price history. The three inputs below have no per-date weekly source.
_HY_SPREAD_DEFAULT  = 350    # bps — moderate-stress default
_DISPERSION_DEFAULT = 10.0   # % — neutral sector dispersion
_BREADTH_DEFAULT    = 1.0    # advance/decline ratio — neutral

# Known equity wipeouts within the test window (2013–2024 screening,
# exits through 2025-12).
# SIVB/SBNY collapsed Mar 2023; their 12-month exit dates for any 2022 or
# early 2023 screening date precede the collapse — they are NOT wipeouts
# here. Extend if confirmed wipeouts emerge during manual review.
_KNOWN_WIPEOUTS: frozenset[str] = frozenset()


# ═══════════════════════════════════════════════════════════════════════════
# DATE GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def _all_fridays(start: date, end: date) -> list[date]:
    """Return every Friday in [start, end] inclusive."""
    d = start
    while d.weekday() != 4:   # 4 = Friday
        d += timedelta(days=1)
    fridays: list[date] = []
    while d <= end:
        fridays.append(d)
        d += timedelta(weeks=1)
    return fridays


def _snap_trading(
    prices: "pd.DataFrame", d: date, direction: str = "prior"
) -> Optional[date]:
    """
    Return the nearest trading day to d.
      direction='prior': last trading day on or before d (entry dates).
      direction='next':  first trading day on or after d (exit dates).
    Returns None if no trading day found within 7 calendar days.
    """
    spy      = prices["SPY"].dropna()
    trading  = set(spy.index.date)
    for delta in range(8):
        candidate = d + timedelta(days=(-delta if direction == "prior" else delta))
        if candidate in trading:
            return candidate
    return None


# ═══════════════════════════════════════════════════════════════════════════
# CALENDAR HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _add_months(d: date, months: int) -> date:
    """Add calendar months, clamping day to end-of-month if necessary."""
    m    = d.month - 1 + months
    year = d.year + m // 12
    mon  = m % 12 + 1
    last = calendar.monthrange(year, mon)[1]
    return date(year, mon, min(d.day, last))


def _is_earnings_season(d: date) -> bool:
    """
    Approximate peak-reporting-window detection from calendar.
    Returns True for the mid-month periods when >30 S&P 500 companies
    typically report: Q4 (mid-Jan–mid-Feb), Q1 (mid-Apr–mid-May),
    Q2 (mid-Jul–mid-Aug), Q3 (mid-Oct–mid-Nov).
    """
    m, day = d.month, d.day
    if (m == 1 and day >= 15) or (m == 2 and day <= 15):
        return True
    if (m == 4 and day >= 15) or (m == 5 and day <= 15):
        return True
    if (m == 7 and day >= 15) or (m == 8 and day <= 15):
        return True
    if (m == 10 and day >= 15) or (m == 11 and day <= 15):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# PRICE DATA HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _fetch_prices(tickers: list[str]) -> "pd.DataFrame":
    """
    Download adjusted close prices for all tickers plus SPY and ^VIX in one
    batch. Returns a DataFrame indexed by date with tickers as columns.
    auto_adjust=True makes Close dividend-and-split-inclusive (total return proxy).
    """
    need = sorted(set(tickers) | {"SPY", "^VIX"})
    print(f"Downloading price history for {len(need)} symbols "
          f"({_PRICE_START} → {_PRICE_END}) …", flush=True)
    raw = yf.download(need, start=_PRICE_START, end=_PRICE_END,
                      auto_adjust=True, progress=False, threads=True)
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"]
    else:
        prices = raw[["Close"]].rename(columns={"Close": need[0]})
    for t in need:
        if t not in prices.columns:
            prices[t] = float("nan")
    print(f"  {len(prices)} trading days, {prices.shape[1]} symbols.\n", flush=True)
    return prices


def _price_on(prices: "pd.DataFrame", ticker: str, d: date) -> Optional[float]:
    """
    Adjusted close on d, or the nearest prior trading day if d has no row.
    Returns None if the ticker has no price at all on or before d.
    """
    col = prices.get(ticker)
    if col is None:
        return None
    col = col.dropna()
    candidates = col[col.index.date <= d]
    return float(candidates.iloc[-1]) if not candidates.empty else None


def _52w_range(
    prices: "pd.DataFrame", ticker: str, d: date
) -> tuple[Optional[float], Optional[float]]:
    """52-week high and low adjusted close ending on d."""
    col = prices.get(ticker)
    if col is None:
        return None, None
    col = col.dropna()
    start  = d - timedelta(days=366)
    window = col[(col.index.date >= start) & (col.index.date <= d)]
    if window.empty:
        return None, None
    return float(window.max()), float(window.min())


def _forward_return(
    prices: "pd.DataFrame", ticker: str, entry: date, exit_d: date
) -> Optional[float]:
    """
    Adjusted-close total return from entry to exit_d.
    Uses last available price if the ticker was delisted before exit_d
    (acquisition exit or bankruptcy recovery — whatever the market recorded).
    Returns None only if the entry price itself is unavailable.
    """
    p0 = _price_on(prices, ticker, entry)
    p1 = _price_on(prices, ticker, exit_d)
    if p0 is None or p0 == 0 or p1 is None:
        return None
    return (p1 - p0) / p0


# ═══════════════════════════════════════════════════════════════════════════
# REGIME INDICATORS
# ═══════════════════════════════════════════════════════════════════════════

def _regime_indicators(prices: "pd.DataFrame", d: date) -> dict:
    """
    Build regime_indicators for classify_regime() at a historical date.

    Computed from price history (no lookahead):
      vix, spy_20d_return, spy_vs_ma200.
    Inferred from calendar:
      earnings_season (peak reporting window approximation).
    Held at documented defaults for all dates:
      hy_spread, sector_dispersion, breadth_adv_decline, fed_action_recent.
    """
    spy = prices["SPY"].dropna()
    vix = prices["^VIX"].dropna()

    spy_hist = spy[spy.index.date <= d]
    vix_hist = vix[vix.index.date <= d]

    vix_now = float(vix_hist.iloc[-1]) if not vix_hist.empty else 20.0

    if not spy_hist.empty:
        spy_now   = float(spy_hist.iloc[-1])
        spy_20d_p = float(spy_hist.iloc[-21]) if len(spy_hist) > 20 else float(spy_hist.iloc[0])
        spy_20d_r = (spy_now - spy_20d_p) / spy_20d_p if spy_20d_p != 0 else 0.0
        window    = spy_hist.iloc[-200:] if len(spy_hist) >= 200 else spy_hist
        spy_ma200 = spy_now >= float(window.mean())
    else:
        spy_20d_r = 0.0
        spy_ma200 = True

    return {
        "vix":                 vix_now,
        "spy_20d_return":      spy_20d_r,
        "spy_vs_ma200":        spy_ma200,
        "hy_spread":           _HY_SPREAD_DEFAULT,
        "earnings_season":     _is_earnings_season(d),
        "fed_action_recent":   False,
        "sector_dispersion":   _DISPERSION_DEFAULT,
        "breadth_adv_decline": _BREADTH_DEFAULT,
    }


# ═══════════════════════════════════════════════════════════════════════════
# RAW RECORD BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _build_record(
    ticker: str, test_date: date, prices: "pd.DataFrame"
) -> Optional[dict]:
    """
    Build one raw screener record for a single ticker at test_date.
    EDGAR fundamentals are filtered to filed <= test_date (point-in-time).
    Returns None if the ticker has no price on or before test_date.
    """
    current_price = _price_on(prices, ticker, test_date)
    if current_price is None:
        return None

    w52_high, w52_low = _52w_range(prices, ticker, test_date)

    try:
        fund_d = fetch_financials(ticker, as_of=test_date.isoformat())
    except Exception:
        fund_d = {}

    shares_ann = fund_d.get("shares_outstanding", {}).get("annual", [])
    shares     = shares_ann[0]["val"] if shares_ann else None
    market_cap = (current_price * shares) if (current_price and shares) else None

    return {
        "ticker":           ticker,
        "fundamental_data": fund_d,
        "price_data":       {"current_price": current_price},
        "extended_data":    {
            "market_cap":   market_cap,
            "week_52_high": w52_high,
            "week_52_low":  w52_low,
        },
        "earnings_data":    {},
    }


# ═══════════════════════════════════════════════════════════════════════════
# PER-DATE RUN
# ═══════════════════════════════════════════════════════════════════════════

def _run_date(test_date: date, prices: "pd.DataFrame") -> dict:
    """
    Run the Stage 01 screener for one historical test date (Friday).

    test_date is the screening date: signals and EDGAR data are as-of this day.
    entry_date is the next trading day after test_date: forward returns start
    here, reflecting the earliest realistic execution time.
    Forward returns are computed separately in _add_returns().
    """
    test_str   = test_date.isoformat()
    universe   = get_sp500_tickers_as_of(test_str)
    regime_ind = _regime_indicators(prices, test_date)

    raw_records: list[dict] = []
    skipped = 0
    for ticker in universe:
        rec = _build_record(ticker, test_date, prices)
        if rec is not None:
            raw_records.append(rec)
        else:
            skipped += 1

    output    = run_screening(raw_records, regime_ind)
    shortlist = [e.ticker for e in output.shortlist]

    # Next trading day after the Friday screening date. Normally Monday;
    # steps forward through holidays until a trading day is found (≤7 days).
    entry_date = _snap_trading(prices, test_date + timedelta(days=1), direction="next")

    return {
        "test_date":         test_date,
        "entry_date":        entry_date,   # p0 for all forward-return calculations
        "regime":            output.market_regime,
        "universe_size":     len(universe),
        "universe_no_price": skipped,
        "shortlist_tickers": shortlist,
        "shortlist_size":    len(shortlist),
    }


# ═══════════════════════════════════════════════════════════════════════════
# FORWARD RETURNS — four horizons, three-way delisting handling
# ═══════════════════════════════════════════════════════════════════════════

def _add_returns(result: dict, prices: "pd.DataFrame") -> dict:
    """
    Compute equal-weighted total returns at all four horizons.

    entry_date is the next trading day after the Friday screening date.
    All forward returns (p1/p0 − 1) use entry_date as p0. Exit dates are
    computed by adding the horizon in calendar months to entry_date, then
    snapping forward to the next trading day.

    Three-way delisting classification (per horizon):
      1. Valid exit price → priced normally; included in average.
      2. No exit price + ticker in _KNOWN_WIPEOUTS → scored −100%; included.
      3. No exit price + not in wipeout set → unresolved; excluded from average
         pending manual review. Flagged in output.

    Tickers with no entry price never reach this function (filtered in
    _build_record → not passed to the screener → not in shortlist).
    If entry_date is None (no trading day found within 7 days of the Monday
    after screening — extremely unlikely), all horizons are marked None.
    """
    entry   = result["entry_date"]
    tickers = result["shortlist_tickers"]

    if entry is None:
        null_h = {
            "shortlist_return": None, "spy_return": None, "excess_return": None,
            "exit_date": None, "tickers_priced": [], "tickers_wipeout": [],
            "tickers_unresolved": [],
        }
        return {**result, "horizons": {key: dict(null_h) for key in _HORIZONS}}

    horizon_data: dict[str, dict] = {}

    for key, h in _HORIZONS.items():
        raw_exit = _add_months(entry, h["months"])
        exit_d   = _snap_trading(prices, raw_exit, direction="next")

        if exit_d is None:
            horizon_data[key] = {
                "shortlist_return":   None,
                "spy_return":         None,
                "excess_return":      None,
                "exit_date":          None,
                "tickers_priced":     [],
                "tickers_wipeout":    [],
                "tickers_unresolved": [],
            }
            continue

        tick_rets:    list[float] = []
        t_priced:     list[str]   = []
        t_wipeout:    list[str]   = []
        t_unresolved: list[str]   = []

        for t in tickers:
            r = _forward_return(prices, t, entry, exit_d)
            if r is not None:
                tick_rets.append(r)
                t_priced.append(t)
            elif t in _KNOWN_WIPEOUTS:
                tick_rets.append(-1.0)
                t_wipeout.append(t)
            else:
                t_unresolved.append(t)

        sl_ret  = (sum(tick_rets) / len(tick_rets) - _COST) if tick_rets else None
        spy_ret = _forward_return(prices, "SPY", entry, exit_d)
        excess  = ((sl_ret - spy_ret)
                   if sl_ret is not None and spy_ret is not None else None)

        horizon_data[key] = {
            "shortlist_return":   sl_ret,
            "spy_return":         spy_ret,
            "excess_return":      excess,
            "exit_date":          exit_d,
            "tickers_priced":     t_priced,
            "tickers_wipeout":    t_wipeout,
            "tickers_unresolved": t_unresolved,
        }

    return {**result, "horizons": horizon_data}


# ═══════════════════════════════════════════════════════════════════════════
# OVERLAPPING-WINDOW STATISTICS
# ═══════════════════════════════════════════════════════════════════════════

def _newey_west(xs: list[float], bandwidth: int) -> tuple[float, float, float]:
    """
    Newey-West HAC estimator for the mean of xs.

    Returns (mean, nw_se, ess).
      nw_se: standard error of the mean, heteroskedasticity-and-autocorrelation
             consistent, using a Bartlett (triangular) kernel.
      ess:   effective sample size = T × S₀ / V_NW.
             Equals T when there is no autocorrelation; shrinks toward T/h for
             fully overlapping returns with horizon h.

    bandwidth: number of lags L.  For overlapping returns with horizon h periods,
      the theoretically correct choice is L = h − 1 (Hansen-Hodrick 1980).
      Bartlett weights w_j = 1 − j/(L+1) ensure the long-run variance V_NW is
      positive semi-definite regardless of sample size.
    """
    T = len(xs)
    if T == 0:
        return float("nan"), float("nan"), 0.0

    mean = sum(xs) / T
    u    = [x - mean for x in xs]

    S0 = sum(v * v for v in u) / T
    if S0 == 0.0:
        return mean, 0.0, float(T)

    lrv = S0
    for j in range(1, bandwidth + 1):
        w  = 1.0 - j / (bandwidth + 1)
        Sj = sum(u[t] * u[t - j] for t in range(j, T)) / T
        lrv += 2.0 * w * Sj

    # Guard against numerical negative long-run variance (rare with small T)
    lrv = max(lrv, S0 * 1e-9)

    nw_se = math.sqrt(lrv / T)
    ess   = S0 / lrv * T
    return mean, nw_se, ess


def _block_bootstrap_ci(
    xs: list[float],
    block_len: int,
    reps: int    = _BOOTSTRAP_REPS,
    alpha: float = 0.05,
    seed: int    = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """
    Circular block bootstrap 95% CI for the mean of xs.

    Draws reps bootstrap samples by resampling blocks of length block_len
    with circular wrap-around (avoids edge effects), then returns the
    (α/2, 1−α/2) empirical quantiles of the bootstrap mean distribution.

    Block length recommendation: max(h_weeks, floor(T^(1/3))).
    Circular bootstrap is asymptotically valid for stationary series.
    """
    T = len(xs)
    if T == 0:
        return float("nan"), float("nan")
    if T == 1:
        return xs[0], xs[0]

    rng      = random.Random(seed)
    n_blocks = math.ceil(T / block_len)
    boots: list[float] = []

    for _ in range(reps):
        sample: list[float] = []
        for _ in range(n_blocks):
            start = rng.randrange(T)
            for k in range(block_len):
                sample.append(xs[(start + k) % T])
        sample = sample[:T]
        boots.append(sum(sample) / T)

    boots.sort()
    lo = boots[max(0,        int(alpha / 2 * reps))]
    hi = boots[min(reps - 1, int((1.0 - alpha / 2) * reps))]
    return lo, hi


def _max_drawdown_non_overlapping(xs: list[float], step: int) -> float:
    """
    Max drawdown on a non-overlapping subseries to avoid overlap bias.

    Takes every step-th observation from xs (step = horizon_weeks) to form an
    approximately independent sequence, then computes the peak-to-trough
    drawdown on the cumulative sum of that sequence.

    Returns a non-positive float (0.0 = no drawdown observed).
    """
    non_ov = xs[::step]
    if len(non_ov) < 2:
        return 0.0

    peak   = 0.0
    cum    = 0.0
    max_dd = 0.0
    for r in non_ov:
        cum += r
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _information_ratio(xs: list[float], horizon_weeks: int) -> float:
    """
    Annualized information ratio: (mean_excess / std_excess) × √(52 / h).
    Computed on the full overlapping series (standard practice for reporting).
    """
    T = len(xs)
    if T < 2:
        return float("nan")
    mean = sum(xs) / T
    var  = sum((x - mean) ** 2 for x in xs) / (T - 1)
    if var <= 0.0:
        return float("nan")
    return mean / math.sqrt(var) * math.sqrt(52.0 / horizon_weeks)


def _hit_rate(xs: list[float]) -> float:
    """Fraction of weeks where excess return is strictly positive."""
    if not xs:
        return float("nan")
    return sum(1 for x in xs if x > 0.0) / len(xs)


def _horizon_stats(xs: list[float], horizon_key: str) -> dict:
    """
    Compute the full statistics bundle for one horizon's excess-return series.
    xs must be pre-filtered to non-None values only.
    """
    h       = _HORIZONS[horizon_key]
    h_weeks = h["weeks"]
    T       = len(xs)
    bw      = h_weeks - 1                           # NW bandwidth = h − 1
    bl      = max(h_weeks, int(T ** (1.0 / 3.0)))   # block length

    mean, nw_se, ess = _newey_west(xs, bandwidth=bw)
    ci_lo, ci_hi     = _block_bootstrap_ci(xs, block_len=bl)
    hit              = _hit_rate(xs)
    max_dd           = _max_drawdown_non_overlapping(xs, step=h_weeks)
    ir               = _information_ratio(xs, h_weeks)

    return {
        "n_obs":    T,
        "ess":      ess,
        "mean":     mean,
        "nw_se":    nw_se,
        "ci_lo":    ci_lo,
        "ci_hi":    ci_hi,
        "hit_rate": hit,
        "max_dd":   max_dd,
        "ir":       ir,
    }


def _regime_breakdown(
    results: list[dict], horizon_key: str
) -> dict[str, dict]:
    """
    Per-regime statistics for one horizon.
    Returns a dict keyed by regime value → {n, mean, hit_rate, vol}.
    """
    buckets: dict[str, list[float]] = {r.value: [] for r in MarketRegime}

    for r in results:
        xs = r["horizons"].get(horizon_key, {}).get("excess_return")
        if xs is not None:
            buckets[r["regime"]].append(xs)

    out: dict[str, dict] = {}
    for regime, xs in buckets.items():
        if not xs:
            out[regime] = {"n": 0, "mean": float("nan"),
                           "hit_rate": float("nan"), "vol": float("nan")}
            continue
        T    = len(xs)
        mean = sum(xs) / T
        hit  = _hit_rate(xs)
        vol  = math.sqrt(sum((x - mean) ** 2 for x in xs) / max(T - 1, 1))
        out[regime] = {"n": T, "mean": mean, "hit_rate": hit, "vol": vol}

    return out


# ═══════════════════════════════════════════════════════════════════════════
# OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

def _na(width: int) -> str:
    return f"{'N/A':>{width}}"


def _pp(v: Optional[float], w: int = 8) -> str:
    if v is None or math.isnan(v):
        return _na(w + 2)
    return f"{v * 100:+{w}.2f}pp"


def _pct(v: Optional[float], w: int = 5) -> str:
    if v is None or math.isnan(v):
        return _na(w + 1)
    return f"{v * 100:{w}.1f}%"


def _f2(v: float, w: int = 6) -> str:
    if math.isnan(v):
        return _na(w)
    return f"{v:{w}.2f}"


def _print_results(results: list[dict]) -> None:
    W   = 108
    SEP = "═" * W
    DIV = "─" * W

    print(f"\n{SEP}")
    print(f"  STAGE 01 SCREENER — WEEKLY BACKTEST  "
          f"2013-01-01 → 2024-12-31")
    print(f"  {len(results)} Friday test dates  ·  "
          f"4 forward-return horizons  ·  equal-weighted shortlist vs SPY")
    print(SEP)

    # ── Collect excess-return series per horizon ──────────────────────────
    xs_by_horizon: dict[str, list[float]] = {k: [] for k in _HORIZONS}
    for r in results:
        for key in _HORIZONS:
            xs = r["horizons"].get(key, {}).get("excess_return")
            if xs is not None:
                xs_by_horizon[key].append(xs)

    # ── Table 1: Per-horizon summary ──────────────────────────────────────
    print(f"\n  PER-HORIZON SUMMARY")
    print(f"  Newey-West HAC SE (bandwidth = h−1)  ·  "
          f"Block bootstrap 95% CI (B={_BOOTSTRAP_REPS})\n")

    col_hdr = (
        f"  {'Horizon':<9}  {'N Obs':>5}  {'ESS':>5}  "
        f"{'Mean XS':>9}  {'NW SE':>7}  "
        f"{'95% CI (bootstrap)':<25}  "
        f"{'Hit%':>5}  {'Max DD':>9}  {'IR':>6}"
    )
    print(col_hdr)
    print("  " + "─" * (W - 2))

    for key, h in _HORIZONS.items():
        xs = xs_by_horizon[key]
        if not xs:
            print(f"  {h['label']:<9}  (no data)")
            continue
        st   = _horizon_stats(xs, key)
        ci   = (f"[{st['ci_lo']*100:+.2f}pp,"
                f" {st['ci_hi']*100:+.2f}pp]")
        print(
            f"  {h['label']:<9}  "
            f"{st['n_obs']:>5}  "
            f"{st['ess']:>5.0f}  "
            f"{st['mean']*100:>+9.2f}pp  "
            f"{st['nw_se']*100:>6.2f}pp  "
            f"  {ci:<25}  "
            f"{st['hit_rate']*100:>4.1f}%  "
            f"{st['max_dd']*100:>+8.2f}pp  "
            f"{_f2(st['ir']):>6}"
        )

    print(f"\n  Methodology notes:")
    print(f"  · ESS = T × S₀ / V_NW.  Equals T if independent; ~T/h under full overlap.")
    print(f"  · NW bandwidth = h − 1 (theoretically correct for overlapping returns).")
    print(f"  · Block length = max(h_weeks, ⌊T^(1/3)⌋).  Circular wrap-around.")
    print(f"  · Max DD on non-overlapping sub-series (every h-th obs) to avoid bias.")
    print(f"  · IR = (mean/σ) × √(52/h).  Uses full overlapping series.")
    print(f"  · Cost: {_COST*100:.1f}% one-time entry per position, deducted per date.")

    # ── Table 2: Per-regime breakdown (one table per horizon) ─────────────
    for key, h in _HORIZONS.items():
        r_stats = _regime_breakdown(results, key)
        total_n = sum(st["n"] for st in r_stats.values())

        print(f"\n  {DIV}")
        print(f"  PER-REGIME BREAKDOWN  [{h['label'].strip()} horizon  ·  "
              f"{total_n} observations with valid returns]")
        print(f"  {DIV}")
        print(
            f"  {'Regime':<28}  "
            f"{'Weeks':>5}  {'Wt%':>5}  "
            f"{'Avg XS':>9}  "
            f"{'Hit%':>5}  "
            f"{'Volatility':>11}"
        )
        print(f"  {'─'*26}  {'─'*5}  {'─'*5}  {'─'*9}  {'─'*5}  {'─'*11}")

        for regime in sorted(r_stats):
            st  = r_stats[regime]
            n   = st["n"]
            wt  = f"{100*n/total_n:.1f}%" if total_n > 0 else " N/A"
            avg = _pp(st["mean"] if n > 0 else None, 7)
            hit = _pct(st["hit_rate"] if n > 0 else None, 4)
            vol = _pp(st["vol"] if n > 0 else None, 7)
            print(
                f"  {regime:<28}  "
                f"{n:>5}  {wt:>5}  "
                f"{avg:>11}  "
                f"{hit:>5}  "
                f"{vol:>11}"
            )

    # ── Table 3: Unresolved ticker log ────────────────────────────────────
    print(f"\n  {DIV}")
    print(f"  UNRESOLVED TICKERS  "
          f"(valid entry price; no exit price; not in wipeout set)")
    print(f"  Excluded from all averages pending manual classification.")
    print(f"  {DIV}")

    # Collect deduplicated (date, ticker) → horizons affected
    seen_unres: dict[tuple[str, str], list[str]] = {}
    for r in results:
        for key in _HORIZONS:
            h_data = r["horizons"].get(key, {})
            for t in h_data.get("tickers_unresolved", []):
                k = (r["test_date"].isoformat(), t)
                seen_unres.setdefault(k, []).append(key)

    if seen_unres:
        for (date_str, t), hkeys in sorted(seen_unres.items()):
            print(f"    {date_str}  {t:<8}  affects: {', '.join(hkeys)}"
                  f"  — classify: acquisition / wipeout (→ _KNOWN_WIPEOUTS) / data gap")
    else:
        print(f"  None.  All shortlist positions are fully classified at every horizon.")

    # ── Classification summary ────────────────────────────────────────────
    print(f"\n  {DIV}")
    print(f"  CLASSIFICATION SUMMARY  (shortlist position accounting)\n")
    total_priced = total_wipeout = total_unres = total_no_entry = 0
    for r in results:
        total_no_entry += r.get("universe_no_price", 0)
        h12 = r["horizons"].get("12m", {})
        total_priced   += len(h12.get("tickers_priced",     []))
        total_wipeout  += len(h12.get("tickers_wipeout",    []))
        total_unres    += len(h12.get("tickers_unresolved", []))

    print(f"  Across all {len(results)} screening dates (12-month horizon):")
    print(f"    Priced positions:    {total_priced:>6}  (exit price from yfinance)")
    print(f"    Wipeout positions:   {total_wipeout:>6}  (in _KNOWN_WIPEOUTS; scored −100%)")
    print(f"    Unresolved:         {total_unres:>6}  (excluded from average)")
    print(f"    Universe no-price:  {total_no_entry:>6}  (never reached screener)")

    # ── Footer ────────────────────────────────────────────────────────────
    print(f"\n  {DIV}")
    print(f"  Data: yfinance adjusted close (dividends + splits inclusive).  "
          f"Benchmark: SPY total return.")
    print(f"  Screening signals as-of Friday close.  "
          f"Entry price = next-trading-day close (Mon, or Tue+ if holiday).")
    print(f"  Exit prices = next-trading-day close on or after the calendar-month target.")
    print(f"  EDGAR as_of filter applied at every date — no fundamental lookahead.")
    print(f"  Secondary regime inputs (HY spread, breadth, dispersion, FOMC proximity)")
    print(f"  held at documented defaults — see module docstring for values.")
    print(f"{SEP}\n")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    # ── Step 1: Generate Friday test dates ────────────────────────────────
    fridays = _all_fridays(_START_DATE, _END_DATE)
    print(f"Test date range: {fridays[0]} → {fridays[-1]}  "
          f"({len(fridays)} Fridays)\n", flush=True)

    # ── Step 2: Collect all unique tickers across every weekly universe ───
    # Scan all Friday universe snapshots upfront so the price download and
    # EDGAR prefetch are complete before the per-date screener loop starts.
    print("Collecting S&P 500 universes for all weekly dates …", flush=True)
    all_tickers: set[str] = set()
    for i, d in enumerate(fridays):
        all_tickers.update(get_sp500_tickers_as_of(d.isoformat()))
        if (i + 1) % 52 == 0 or (i + 1) == len(fridays):
            print(f"  {i+1:>4}/{len(fridays)} dates scanned — "
                  f"{len(all_tickers)} unique tickers so far.", flush=True)
    print(f"  Total unique tickers across all weekly universes: "
          f"{len(all_tickers)}\n", flush=True)

    # ── Step 3: Download all price history in one batch ───────────────────
    prices = _fetch_prices(sorted(all_tickers))

    # ── Step 4: Snap Fridays to actual trading days ───────────────────────
    # Most Fridays are trading days. Where a Friday is a market holiday, snap
    # to the prior trading day (Thursday close) so we use the last available
    # price of the week as intended.
    raw_trading_days: list[date] = []
    for d in fridays:
        snapped = _snap_trading(prices, d, direction="prior")
        if snapped is not None:
            raw_trading_days.append(snapped)
        else:
            print(f"  WARNING: No trading day found near {d}; date skipped.", flush=True)

    # Deduplicate: adjacent Fridays that snap to the same date (holiday at
    # week boundary) should not produce duplicate screener runs.
    seen_td: set[date] = set()
    test_dates: list[date] = []
    for d in raw_trading_days:
        if d not in seen_td:
            seen_td.add(d)
            test_dates.append(d)

    print(f"Resolved {len(test_dates)} unique trading dates "
          f"from {len(fridays)} Fridays.\n", flush=True)

    # ── Step 5: Pre-fetch EDGAR companyfacts ─────────────────────────────
    # One HTTP request per ticker; fetch_financials() uses _facts_cache
    # thereafter, making all per-date as_of calls pure in-memory lookups.
    prefetch_facts(sorted(all_tickers))

    # ── Step 6: Run screener for each test date ────────────────────────────
    n = len(test_dates)
    print(f"\nRunning screener for {n} dates …\n", flush=True)
    date_results: list[dict] = []
    for i, test_date in enumerate(test_dates):
        if i % 26 == 0:
            print(f"  [{100*i/n:5.1f}%]  {test_date}  "
                  f"({i}/{n})", flush=True)
        date_results.append(_run_date(test_date, prices))

    print(f"  [100.0%]  Done. {len(date_results)} dates processed.\n", flush=True)

    # ── Step 7: Compute forward returns for all horizons ──────────────────
    print("Computing forward returns at 1, 3, 6, 12-month horizons …", flush=True)
    full_results = [_add_returns(r, prices) for r in date_results]
    print("  Done.\n", flush=True)

    # ── Step 8: Print results ─────────────────────────────────────────────
    _print_results(full_results)


if __name__ == "__main__":
    main()
