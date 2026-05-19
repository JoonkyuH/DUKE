#!/usr/bin/env python3
"""
edgar_fetcher.py
Fetches financial statement data from SEC EDGAR (data.sec.gov).
No API key required. Respects EDGAR's 10-req/sec guideline.

Entry point:
    fetch_financials(ticker: str) -> dict

Returns last 2 annual periods and last 4 quarters for each of:
    revenue, gross_profit, operating_income, net_income,
    operating_cash_flow, capex, free_cash_flow,
    total_debt, cash_and_equivalents, shares_outstanding

Each metric is a dict: {"annual": [...], "quarterly": [...]}
Each period entry: {"period": "Q1 FY2026", "end": "2025-04-27", "val": <int>}
Values are in USD (or shares for shares_outstanding).
"""

import json
import time
import urllib.request
import urllib.error
from datetime import date
from typing import Optional

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL      = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_HEADERS        = {"User-Agent": "DUKE-research contact@duke-research.ai"}

_ticker_cache: dict = {}   # ticker → zero-padded CIK str, populated on first call


# ─────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _cik(ticker: str) -> str:
    """Zero-padded 10-digit CIK for a ticker. Fetches the bulk map once."""
    t = ticker.upper()
    if not _ticker_cache:
        for entry in _get(_TICKER_MAP_URL).values():
            _ticker_cache[entry["ticker"]] = str(entry["cik_str"]).zfill(10)
    if t not in _ticker_cache:
        raise ValueError(f"Ticker {t!r} not found in SEC EDGAR company list")
    return _ticker_cache[t]


# ─────────────────────────────────────────────
# ENTRY CLASSIFICATION
# ─────────────────────────────────────────────

def _days(entry: dict) -> int:
    """Calendar days spanned by a flow entry. Returns 0 for instantaneous."""
    try:
        return (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
    except (KeyError, ValueError):
        return 0


def _is_standalone(entry: dict) -> bool:
    """
    True if entry represents exactly one quarter (not a YTD span).
      - Instantaneous (balance sheet): no 'start' field
      - Flow standalone: has a 'Q'-containing frame tag (SEC-confirmed)
      - Fallback: period between 60 and 110 calendar days
    """
    if "start" not in entry:
        return True
    frame = entry.get("frame", "")
    if frame and "Q" in frame:
        return True
    d = _days(entry)
    return 60 <= d <= 110


# ─────────────────────────────────────────────
# EXTRACTION
# ─────────────────────────────────────────────

def _entries(facts: dict, *concepts: str, unit: str = "USD") -> list:
    """Return the first non-empty entry list matching one of the concept names."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for name in concepts:
        vals = us_gaap.get(name, {}).get("units", {}).get(unit, [])
        if vals:
            return vals
    return []


def _extract(raw: list, n_annual: int = 2, n_quarterly: int = 4) -> dict:
    """
    Extract last n_annual annual periods and last n_quarterly individual
    quarters from a raw EDGAR entry list.

    Annual: 10-K filings with fp="FY".
    Quarterly strategy (in order):
      1. Frame-tagged standalone entries (SEC-confirmed single quarter).
      2. For Q2/Q3 flow gaps: individual = YTD_curr − YTD_prev.
      3. Q4 for flow items: Annual − YTD_Q3.
      4. Q4 for balance sheet: the FY/10-K entry itself.
    Deduplication: EDGAR includes prior-year comparatives in each filing with
    the same (fy, fp) but an earlier end date. For any (fy, fp) collision, the
    entry with the LATEST end date is the current period's own data; ties are
    broken by latest filed date (handles amendments).
    """
    valid = [e for e in raw if e.get("form") in ("10-K", "10-Q")]

    # ── Annual ────────────────────────────────
    # Two-pass: (1) dedup by (fy, end) keeping latest filed;
    # (2) per fy, keep the entry with the latest end date.
    ann_by_fy_end: dict = {}
    for e in valid:
        if e.get("fp") == "FY" and e.get("form") == "10-K":
            key = (e.get("fy"), e.get("end", ""))
            if key not in ann_by_fy_end or e.get("filed", "") > ann_by_fy_end[key].get("filed", ""):
                ann_by_fy_end[key] = e
    ann_by_fy: dict = {}
    for (fy, end), e in ann_by_fy_end.items():
        if fy not in ann_by_fy or end > ann_by_fy[fy].get("end", ""):
            ann_by_fy[fy] = e
    annual = sorted(ann_by_fy.values(), key=lambda x: x["end"], reverse=True)[:n_annual]

    # ── Quarterly: standalone entries ─────────
    # Same two-pass dedup: collect by (fy, fp, end), then pick latest end per (fy, fp).
    q: dict = {}    # {(fy, fp): standalone entry}
    ytd: dict = {}  # {(fy, fp): YTD entry} — for differencing flow gaps

    q_by_end: dict = {}    # {(fy, fp, end): entry}
    ytd_by_end: dict = {}

    for e in valid:
        fp = e.get("fp")
        if fp not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        fy = e.get("fy")
        end = e.get("end", "")

        if _is_standalone(e):
            key = (fy, fp, end)
            if key not in q_by_end or e.get("filed", "") > q_by_end[key].get("filed", ""):
                q_by_end[key] = e
        elif "start" in e and fp in ("Q1", "Q2", "Q3"):
            # YTD entry (Q2/Q3 have period > 110 days; Q1 same as standalone)
            if fp == "Q1" or _days(e) > 110:
                key = (fy, fp, end)
                if key not in ytd_by_end or e.get("filed", "") > ytd_by_end[key].get("filed", ""):
                    ytd_by_end[key] = e

    for (fy, fp, end), e in q_by_end.items():
        key2 = (fy, fp)
        if key2 not in q or end > q[key2].get("end", ""):
            q[key2] = e

    for (fy, fp, end), e in ytd_by_end.items():
        key2 = (fy, fp)
        if key2 not in ytd or end > ytd[key2].get("end", ""):
            ytd[key2] = e

    # Balance sheet FY entry = end-of-year balance (Q4 equivalent)
    for fy, e in ann_by_fy.items():
        key = (fy, "Q4")
        if key not in q and "start" not in e:   # instantaneous
            q[key] = {**e, "fp": "Q4"}

    # Fill flow gaps: Q2 = YTD_Q2 − YTD_Q1, Q3 = YTD_Q3 − YTD_Q2
    all_fy = {e.get("fy") for e in valid if e.get("fy")}
    for fy in all_fy:
        for fp, prev_fp in [("Q2", "Q1"), ("Q3", "Q2")]:
            key = (fy, fp)
            if key in q:
                continue
            curr = ytd.get((fy, fp))
            prev = ytd.get((fy, prev_fp)) or (q.get((fy, prev_fp)) if prev_fp == "Q1" else None)
            if curr and prev and "val" in curr and "val" in prev:
                q[key] = {
                    "fy": fy, "fp": fp, "end": curr["end"],
                    "val": curr["val"] - prev["val"],
                    "form": curr["form"], "filed": curr.get("filed", ""),
                }

        # Q4 flow: Annual − YTD_Q3
        key_q4 = (fy, "Q4")
        if key_q4 not in q:
            ytd_q3 = ytd.get((fy, "Q3"))
            ann    = ann_by_fy.get(fy)
            if ytd_q3 and ann and "start" in ytd_q3 and "start" in ann:
                q[key_q4] = {
                    "fy": fy, "fp": "Q4", "end": ann["end"],
                    "val": ann["val"] - ytd_q3["val"],
                    "form": "10-K", "filed": ann.get("filed", ""),
                }

    quarterly = sorted(q.values(), key=lambda x: x.get("end", ""), reverse=True)[:n_quarterly]

    def _qa(e):
        return {"period": f"FY{e['fy']}", "end": e["end"], "val": e["val"]}

    def _qq(e):
        return {"period": f"{e['fp']} FY{e['fy']}", "end": e["end"], "val": e["val"]}

    return {
        "annual":    [_qa(e) for e in annual],
        "quarterly": [_qq(e) for e in quarterly],
    }


def _fcf(cf: dict, capex: dict) -> dict:
    """Free cash flow = operating CF − capex, matched by period label."""
    result = {}
    for window in ("annual", "quarterly"):
        cf_map    = {e["period"]: e for e in cf.get(window, [])}
        capex_map = {e["period"]: e for e in capex.get(window, [])}
        entries   = []
        for period, cf_e in cf_map.items():
            if period in capex_map:
                entries.append({
                    "period": period,
                    "end":    cf_e["end"],
                    "val":    cf_e["val"] - capex_map[period]["val"],
                })
        result[window] = sorted(entries, key=lambda x: x["end"], reverse=True)
    return result


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def fetch_financials(ticker: str) -> dict:
    """
    Fetch EDGAR financial facts for ticker and return structured metrics.

    Raises:
        ValueError  — ticker not in SEC company list
        urllib.error.HTTPError — EDGAR returned 404 (no XBRL data for CIK)
    """
    cik_str = _cik(ticker)
    time.sleep(0.15)    # polite rate-limiting; EDGAR allows 10 req/sec
    facts = _get(_FACTS_URL.format(cik=cik_str))

    def usd(*concepts):
        return _entries(facts, *concepts, unit="USD")

    def shares(*concepts):
        return _entries(facts, *concepts, unit="shares")

    revenue = _extract(usd(
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ))
    gross_profit     = _extract(usd("GrossProfit"))
    operating_income = _extract(usd("OperatingIncomeLoss"))
    net_income       = _extract(usd("NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"))

    operating_cf = _extract(usd(
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ))
    capex = _extract(usd(
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsForCapitalImprovements",
    ))
    free_cash_flow = _fcf(operating_cf, capex)

    total_debt = _extract(usd(
        "LongTermDebt",                # combined current + noncurrent for most filers
        "DebtAndCapitalLeaseObligations",
    ))
    cash = _extract(usd(
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ))
    shares_out = _extract(shares(
        "CommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ))

    return {
        "ticker":               ticker.upper(),
        "cik":                  cik_str,
        "revenue":              revenue,
        "gross_profit":         gross_profit,
        "operating_income":     operating_income,
        "net_income":           net_income,
        "operating_cash_flow":  operating_cf,
        "capex":                capex,
        "free_cash_flow":       free_cash_flow,
        "total_debt":           total_debt,
        "cash_and_equivalents": cash,
        "shares_outstanding":   shares_out,
    }


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    print(f"Fetching EDGAR financials for {ticker_arg} …")
    data = fetch_financials(ticker_arg)

    M = 1_000_000

    def _fmt(val, is_shares=False):
        if val is None:
            return "      —"
        if is_shares:
            return f"{val / 1_000_000:>8.0f}M"
        if abs(val) >= 1_000_000_000:
            return f"${val / 1_000_000_000:>7.2f}B"
        return f"${val / M:>7.0f}M"

    metrics = [
        ("revenue",              "Revenue",           False),
        ("gross_profit",         "Gross Profit",      False),
        ("operating_income",     "Operating Income",  False),
        ("net_income",           "Net Income",        False),
        ("operating_cash_flow",  "Operating CF",      False),
        ("capex",                "CapEx",             False),
        ("free_cash_flow",       "Free Cash Flow",    False),
        ("total_debt",           "Total Debt",        False),
        ("cash_and_equivalents", "Cash & Equiv",      False),
        ("shares_outstanding",   "Shares Out",        True),
    ]

    print(f"\n{'═'*72}")
    print(f"  {ticker_arg}  —  EDGAR Financial Summary")
    print(f"{'═'*72}")

    for key, label, is_shares in metrics:
        m = data[key]
        ann = m.get("annual", [])
        qtrs = m.get("quarterly", [])
        print(f"\n  {label}")

        if ann:
            row = "  ".join(
                f"{e['period']:>12}:{_fmt(e['val'], is_shares)}" for e in ann
            )
            print(f"    Annual:    {row}")

        if qtrs:
            row = "  ".join(
                f"{e['period']:>12}:{_fmt(e['val'], is_shares)}" for e in qtrs
            )
            print(f"    Quarterly: {row}")

    print(f"\n{'═'*72}\n")
