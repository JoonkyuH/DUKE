"""
sp500_historical.py
Point-in-time S&P 500 constituent loader.

Data sources (vendored at a pinned commit):
  sp500_historical.csv   — daily snapshots 1996-01-02 to 2019-01-11
  sp500_since_2019.csv   — change-log (add/remove) 2019-01-18 to present

Both files sourced from fja05680/sp500 (MIT License, Farrell J. Aultman).
Pinned commit: 1bfcb10f2743108de671021ea78217ab07bab2ad (2026-02-01)

Ticker encoding in sp500_historical.csv:
  Tickers appear as BASE or BASE-YYYYMM where the suffix marks the final
  trading date of that symbol (not necessarily the S&P 500 removal date).
  Companies that reused a ticker symbol appear as both BASE-YYYYMM (old
  entity) and BASE (current entity) within the same snapshot; after suffix
  stripping, set() deduplication resolves these to a single symbol. This
  is a known data-quality limitation for ~12 reused tickers in 1996,
  declining to 0 by 2019.

Entry point:
    get_sp500_tickers_as_of(date_str: str) -> list[str]
"""

import csv
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_HIST_CSV  = _HERE / "sp500_historical.csv"   # snapshots 1996-01-02 to 2019-01-11
_DELTA_CSV = _HERE / "sp500_since_2019.csv"   # changes   2019-01-18 to present

_HIST_CUTOFF = "2019-01-11"   # last date covered by snapshot file
_SUFFIX_RE   = re.compile(r"-\d{6}$")


def _clean(ticker: str) -> str:
    """Strip -YYYYMM suffix and whitespace from a raw ticker token."""
    return _SUFFIX_RE.sub("", ticker.strip())


def _load_snapshot(date_str: str) -> set:
    """
    Return the clean constituent set for the last snapshot on or before date_str.
    Covers 1996-01-02 to 2019-01-11.
    """
    best_row = None
    with open(_HIST_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row["date"] <= date_str:
                best_row = row
            elif best_row is not None:
                break   # rows are in ascending date order; past target, stop
    if best_row is None:
        raise ValueError(f"No historical snapshot available on or before {date_str!r} "
                         f"(earliest is 1996-01-02)")
    tickers = {_clean(t) for t in best_row["tickers"].split(",") if t.strip()}
    return tickers


def _apply_deltas(base: set, through_date: str) -> set:
    """
    Apply add/remove delta entries from sp500_since_2019.csv where
    delta_date <= through_date. Returns a new set (does not mutate base).
    """
    current = set(base)
    with open(_DELTA_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row["date"] > through_date:
                break
            # add and remove fields may be comma-separated multi-ticker strings
            for t in row["add"].split(","):
                t = t.strip()
                if t:
                    current.add(t)
            for t in row["remove"].split(","):
                t = t.strip()
                if t:
                    current.discard(t)
    return current


def get_sp500_tickers_as_of(date_str: str) -> list:
    """
    Return a sorted list of S&P 500 ticker symbols as of date_str (YYYY-MM-DD).

    For dates on or before 2019-01-11: returns the nearest snapshot.
    For dates after 2019-01-11: starts from the 2019-01-11 snapshot and
    applies all add/remove deltas through date_str.

    Raises ValueError if date_str is before 1996-01-02 (no data).
    """
    if date_str <= _HIST_CUTOFF:
        members = _load_snapshot(date_str)
    else:
        members = _load_snapshot(_HIST_CUTOFF)
        members = _apply_deltas(members, date_str)
    return sorted(members)
