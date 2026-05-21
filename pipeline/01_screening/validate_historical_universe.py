#!/usr/bin/env python3
"""
validate_historical_universe.py
Pre-gate validation for the historical S&P 500 constituent data.
The backtest runner imports and calls validate() before executing any test.
Exits with code 1 on any failure so the backtest cannot proceed.

Run directly for a report:
    cd pipeline/01_screening
    python3 validate_historical_universe.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe.sp500_historical import get_sp500_tickers_as_of

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Snapshots to count-check (date, expected_min, expected_max, label)
_COUNT_CHECKS = [
    ("1996-01-02", 480, 510, "First row"),
    ("2000-01-03", 480, 510, "Y2K era"),
    ("2002-07-01", 480, 510, "Post dot-com"),
    ("2008-09-15", 480, 510, "Lehman day"),
    ("2013-06-03", 480, 510, "Mid-decade"),
    ("2019-01-09", 480, 510, "Last historical snapshot era"),
    ("2019-06-01", 480, 510, "First delta era"),
    ("2022-01-03", 480, 510, "Recent"),
    ("2025-01-02", 480, 510, "Near-present"),
]

# Hardcoded membership facts — includes both additions AND removals.
# Removals are critical: a missing removal silently reintroduces
# survivorship bias by keeping a failed company in the universe.
# Format: (date, ticker, expected_in_index, label)
_MEMBERSHIP_CHECKS = [
    # ── Survivorship-critical removals ─────────────────────────────────────
    # Enron: filed BK Nov 2001, removed from S&P 500 early 2002
    ("2001-09-10", "ENRNQ",        True,  "Enron still in index Sep 2001"),
    ("2002-04-01", "ENRNQ",        False, "Enron removed after Nov 2001 BK"),
    # WorldCom: fraud revealed Jun 2002, BK filed Jul 2002, removed ~Jul 2002
    # Dataset stores WorldCom as WCOEQ (bankruptcy OTC ticker)
    ("2001-06-01", "WCOEQ",        True,  "WorldCom in index mid-2001"),
    ("2002-08-01", "WCOEQ",        False, "WorldCom removed after Jul 2002 BK"),
    # Lehman Brothers: BK filed Sep 15, 2008, removed from S&P 500 Sep 2008
    # Dataset stores Lehman as LEHMQ (bankruptcy OTC ticker)
    ("2008-01-02", "LEHMQ",        True,  "Lehman in index Jan 2008"),
    ("2008-10-01", "LEHMQ",        False, "Lehman removed after Sep 15 2008 BK"),
    # BHGE (Baker Hughes GE) removed 2019-10-18, replaced by BKR.
    # Note: GE itself was NOT removed from the S&P 500 (it was removed
    # from the Dow Jones in 2018, which is a different index).
    ("2019-10-17", "BHGE",         True,  "BHGE in index day before removal"),
    ("2019-10-19", "BHGE",         False, "BHGE removed 2019-10-18"),
    ("2019-10-19", "BKR",          True,  "BKR added 2019-10-18"),
    ("2025-01-02", "GE",           True,  "GE still in S&P 500 as of 2025"),
    # PCG (PG&E): removed 2019-01-18, re-added later
    ("2019-01-17", "PCG",          True,  "PCG in index before removal"),
    ("2019-01-19", "PCG",          False, "PCG removed 2019-01-18"),

    # ── Known long-term members ────────────────────────────────────────────
    ("1996-01-02", "MSFT",         True,  "MSFT continuous since 1994"),
    ("1996-01-02", "AAPL",         True,  "AAPL in index 1996"),
    ("2010-01-04", "AAPL",         True,  "AAPL continuous 2010"),
    ("2019-01-09", "GE",           True,  "GE before removal"),
    ("2008-09-12", "AIG",          True,  "AIG in index pre-bailout"),

    # ── Known additions (delta era) ────────────────────────────────────────
    # TFX added 2019-01-18
    ("2019-01-17", "TFX",          False, "TFX not yet added"),
    ("2019-01-19", "TFX",          True,  "TFX added 2019-01-18"),
    # AMZN was added to S&P 500 in 2005; check it's present throughout
    ("2010-01-04", "AMZN",         True,  "AMZN in index 2010"),
    ("2025-01-02", "NVDA",         True,  "NVDA present 2025"),
]


# ─────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────

def validate(silent: bool = False) -> bool:
    """
    Run all validation checks. Returns True if all pass, False otherwise.
    Prints a report unless silent=True.
    Raises SystemExit(1) on failure when called as a gate (not silent).
    """
    failures = []

    def log(msg):
        if not silent:
            print(msg)

    log("\n─── Historical Universe Validation ───────────────────────────────────")

    # ── 1. Count checks ───────────────────────────────────────────────────
    log("\n  Count checks (expect 480–510 per snapshot):")
    for date, lo, hi, label in _COUNT_CHECKS:
        try:
            members = get_sp500_tickers_as_of(date)
            n = len(members)
            ok = lo <= n <= hi
            status = "OK  " if ok else "FAIL"
            log(f"    [{status}] {date}  {n:>4} tickers  ({label})")
            if not ok:
                failures.append(f"Count {date}: got {n}, expected {lo}–{hi} ({label})")
        except Exception as exc:
            log(f"    [FAIL] {date}  ERROR: {exc}  ({label})")
            failures.append(f"Count {date}: exception — {exc}")

    # ── 2. Membership checks ──────────────────────────────────────────────
    log("\n  Membership checks:")
    for date, ticker, expected, label in _MEMBERSHIP_CHECKS:
        try:
            members = set(get_sp500_tickers_as_of(date))
            found = ticker in members
            ok = found == expected
            status = "OK  " if ok else "FAIL"
            verdict = "IN " if found else "OUT"
            log(f"    [{status}] {date}  {ticker:<12} {verdict}  (expected {'IN ' if expected else 'OUT'})  {label}")
            if not ok:
                failures.append(
                    f"Membership {date} {ticker}: found={found}, expected={expected} ({label})"
                )
        except Exception as exc:
            log(f"    [FAIL] {date}  {ticker}  ERROR: {exc}  ({label})")
            failures.append(f"Membership {date} {ticker}: exception — {exc}")

    # ── 3. Within-snapshot duplicate check ───────────────────────────────
    log("\n  Duplicate-ticker checks (post-clean):")
    dup_dates = ["1996-01-02", "2001-09-10", "2008-09-15", "2019-01-09", "2022-06-01"]
    any_dup_fail = False
    for date in dup_dates:
        try:
            members = get_sp500_tickers_as_of(date)
            n_unique = len(set(members))
            n_total  = len(members)
            ok = n_unique == n_total
            status = "OK  " if ok else "FAIL"
            log(f"    [{status}] {date}  {n_total} tickers, {n_unique} unique")
            if not ok:
                dupes = [t for t in members if members.count(t) > 1]
                msg = f"Duplicates on {date}: {sorted(set(dupes))}"
                failures.append(msg)
                any_dup_fail = True
        except Exception as exc:
            log(f"    [FAIL] {date}  ERROR: {exc}")
            failures.append(f"Dup check {date}: exception — {exc}")

    # ── Summary ───────────────────────────────────────────────────────────
    log("\n──────────────────────────────────────────────────────────────────────")
    if failures:
        log(f"\n  VALIDATION FAILED — {len(failures)} issue(s):")
        for f in failures:
            log(f"    • {f}")
        log("")
        if not silent:
            sys.exit(1)
        return False
    else:
        log(f"\n  VALIDATION PASSED — {len(_COUNT_CHECKS)} count checks, "
            f"{len(_MEMBERSHIP_CHECKS)} membership checks, "
            f"{len(dup_dates)} duplicate checks\n")
        return True


if __name__ == "__main__":
    validate()
