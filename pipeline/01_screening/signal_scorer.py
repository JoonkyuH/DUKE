"""
signal_scorer.py
Six fundamental quality-and-value screening signals (0–100 each).

Each ticker is scored under two archetype weight sets (defined in screener.py);
the higher composite wins and determines the screening_archetype tag.

  long_term_compounder:  BQ 30 / VG 25 / EQ 25 / EF 12 / HD  0 / BR 8
  quality_compounder:    BQ 35 / EQ 25 / VG 20 / EF 12 / HD  5 / BR 3
  deep_value:            BQ 25 / HD 25 / EQ 20 / VG 15 / EF 12 / BR 3

VG signal variants per archetype:
  long_term_compounder → score_valuation_vs_growth_compounder()
      rewards high absolute revenue growth (40 pts) over multiple discipline
  quality_compounder   → score_valuation_vs_growth_quality_compounder()
      relaxed P/FCF thresholds; rewards steady 5–15% growth + high gross margin
  deep_value           → score_valuation_vs_growth()  (standard)

Inputs:
  fund_d     — common.edgar_client.fetch_financials() output dict
  market_d   — {"market_cap", "current_price", "week_52_high", "week_52_low"}
  earnings_d — data_fetcher earnings sub-dict (for binary_event_risk only)

Call compute_fundamental_metrics(fund_d, market_d) once per ticker, then pass
the result to each score_* function and to build_mispricing_hypothesis().
"""

import logging

from dataclasses import dataclass
from typing import Optional

from economic_profile_classifier import (
    classify,
    get_multipliers,
    get_disabled_signals,
    is_commodity_cyclical,
)

log = logging.getLogger("signal_scorer")


@dataclass
class SignalScores:
    business_quality:      Optional[float]
    valuation_vs_growth:   Optional[float]
    historical_discount:   Optional[float]
    earnings_quality:      Optional[float]
    entry_vs_fundamentals: Optional[float]
    binary_event_risk:     Optional[float]


# ─────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────

def _ttm(metric: dict) -> Optional[float]:
    """Trailing twelve months: sum of last 4 quarterly values (≥2 required)."""
    vals = [
        q["val"] for q in metric.get("quarterly", [])[:4]
        if isinstance(q.get("val"), (int, float))
    ]
    return sum(vals) if len(vals) >= 2 else None


def _ann(metric: dict, n: int = 0) -> Optional[float]:
    """nth annual value (0 = most recent). None if unavailable."""
    annual = metric.get("annual", [])
    if n < len(annual) and isinstance(annual[n].get("val"), (int, float)):
        return float(annual[n]["val"])
    return None


def _qtr(metric: dict, n: int = 0) -> Optional[float]:
    """nth quarterly value (0 = most recent). None if unavailable."""
    quarterly = metric.get("quarterly", [])
    if n < len(quarterly) and isinstance(quarterly[n].get("val"), (int, float)):
        return float(quarterly[n]["val"])
    return None


def _margin(num: Optional[float], den: Optional[float]) -> Optional[float]:
    """Safe percentage ratio. None if inputs are invalid or denominator ≤ 0."""
    if num is None or den is None or den <= 0:
        return None
    return num / den * 100


def _yoy(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    """Safe YoY percentage growth."""
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100


def _latest_annual_fy(metric: dict) -> Optional[int]:
    """Return the fiscal year integer of the most recent annual entry, or None."""
    annual = metric.get("annual", [])
    if not annual:
        return None
    latest = max(annual, key=lambda x: x.get("end", ""))
    try:
        return int(latest.get("period", "").replace("FY", "").strip())
    except (ValueError, AttributeError):
        return None


def _mid_cycle_fcf(
    fcf_annual:   list,
    capex_annual: list,
    rev_ttm:      Optional[float] = None,
    min_years:    int = 3,
    max_years:    int = 5,
) -> tuple[Optional[float], int]:
    """
    Trailing mid-cycle FCF average for commodity-cyclical normalization.

    Walks back from the most recent fiscal year, including only CONSECUTIVE
    years where FCF is present AND CapEx is present and positive. Deep EDGAR
    history has XBRL concept-switch gaps (e.g. CapEx tagged 0 or missing in
    some years), which would corrupt a naive average; stopping at the first
    gap keeps the window contiguous and recent. Caps the window at max_years.

    Returns (mean_fcf, n_years_used). mean_fcf is None — caller falls back to
    TTM FCF and does NOT normalize — when any of:
      - fewer than min_years clean consecutive years are available;
      - the mean is <= 0 or near-zero relative to revenue (a near-zero
        denominator makes P/FCF and FCF/NI explode or flip sign — worse than
        not normalizing; ALB's lithium FCF straddled zero, 5yr mean ≈ −$0.1B
        → −10× ratios. This guard also protects the energy profiles);
      - the clean series straddles zero and the mean is tiny relative to the
        boom/bust spread, so the average is not a meaningful mid-cycle figure.

    Both lists are expected most-recent-first (as _fcf / _extract return them).
    """
    capex_by_period = {e.get("period"): e.get("val") for e in (capex_annual or [])}
    clean: list[float] = []
    for e in (fcf_annual or []):
        cx  = capex_by_period.get(e.get("period"))
        val = e.get("val")
        if cx is None or cx <= 0 or val is None:
            break                          # gap → window ends here (stay contiguous)
        clean.append(val)
        if len(clean) >= max_years:
            break
    if len(clean) < min_years:
        return None, len(clean)

    mean = sum(clean) / len(clean)
    # Denominator guards (see docstring): positive, above a revenue-relative
    # floor, and not a meaningless boom/bust straddle.
    if mean <= 0:
        return None, len(clean)
    if rev_ttm is not None and rev_ttm > 0 and mean < 0.01 * rev_ttm:
        return None, len(clean)
    spread = max(clean) - min(clean)
    if min(clean) < 0 < max(clean) and spread > 0 and mean < 0.10 * spread:
        return None, len(clean)
    return mean, len(clean)


# ─────────────────────────────────────────────
# METRICS COMPUTATION (single pass per ticker)
# ─────────────────────────────────────────────

def compute_fundamental_metrics(
    fund_d: dict,
    market_d: dict,
    economic_profile: str = "unknown",
) -> dict:
    """
    Derive all fundamental metrics from common.edgar_client output and market price data.
    Called once per ticker; the result dict is passed to all six score functions
    and to build_mispricing_hypothesis().

    fund_d           — common.edgar_client.fetch_financials() output
    market_d         — {"market_cap": int, "current_price": float,
                        "week_52_high": float, "week_52_low": float}
    economic_profile — profile string from economic_profile_classifier.classify()
    """
    rev   = fund_d.get("revenue", {})
    gp    = fund_d.get("gross_profit", {})
    ni    = fund_d.get("net_income", {})
    fcf   = fund_d.get("free_cash_flow", {})
    capex = fund_d.get("capex", {})
    debt  = fund_d.get("total_debt", {})
    cash  = fund_d.get("cash_and_equivalents", {})
    shr   = fund_d.get("shares_outstanding", {})

    # ── Revenue ──────────────────────────────
    rev_ttm  = _ttm(rev)
    rev_ann0 = _ann(rev, 0)
    rev_ann1 = _ann(rev, 1)
    rev_growth = _yoy(rev_ann0, rev_ann1)       # annual YoY %

    # Quarterly trend: how many of the 3 consecutive QoQ pairs are increasing?
    rev_qtrs = [_qtr(rev, i) for i in range(4)]  # [newest, ..., oldest]
    increasing_pairs = sum(
        1 for i in range(3)
        if rev_qtrs[i + 1] is not None and rev_qtrs[i] is not None
        and rev_qtrs[i] > rev_qtrs[i + 1]          # newer > older
    )

    # ── Gross margin ─────────────────────────
    gm_q0   = _margin(_qtr(gp, 0), _qtr(rev, 0))  # most recent quarter
    gm_q3   = _margin(_qtr(gp, 3), _qtr(rev, 3))  # 4 quarters ago
    gm_trend = (gm_q0 - gm_q3) if (gm_q0 is not None and gm_q3 is not None) else None
    gm_ann   = _margin(_ann(gp, 0), rev_ann0)      # most recent annual

    # ── Period alignment guard: revenue vs gross_profit ──
    rev_fy = _latest_annual_fy(fund_d.get("revenue", {}))
    gp_fy  = _latest_annual_fy(fund_d.get("gross_profit", {}))
    if (rev_fy is not None
            and gp_fy is not None
            and abs(rev_fy - gp_fy) > 1):
        log.warning(
            "PERIOD MISMATCH: revenue is FY%s but gross_profit is FY%s — "
            "setting gm_ann and gm_trend to None to prevent corrupted "
            "gross margin calculation",
            rev_fy, gp_fy,
        )
        gm_ann   = None
        gm_trend = None

    # ── FCF ──────────────────────────────────
    fcf_ttm  = _ttm(fcf)
    fcf_ann0 = _ann(fcf, 0)
    fcf_ann1 = _ann(fcf, 1)
    fcf_margin = _margin(fcf_ttm, rev_ttm)

    # ── Period alignment guard: revenue vs free_cash_flow ──
    fcf_fy = _latest_annual_fy(fund_d.get("free_cash_flow", {}))
    if (rev_fy is not None
            and fcf_fy is not None
            and abs(fcf_fy - rev_fy) > 1):
        log.warning(
            "PERIOD MISMATCH: revenue is FY%s but free_cash_flow is FY%s — "
            "setting fcf_margin to None",
            rev_fy, fcf_fy,
        )
        fcf_margin = None

    # ── Net income ───────────────────────────
    ni_ttm  = _ttm(ni)
    ni_ann0 = _ann(ni, 0)

    # ── FCF quality ratio ─────────────────────
    fcf_to_ni = None
    if fcf_ttm is not None and ni_ttm is not None and ni_ttm > 0:
        fcf_to_ni = fcf_ttm / ni_ttm

    # ── Balance sheet ─────────────────────────
    cash_v = _qtr(cash, 0) if _qtr(cash, 0) is not None else _ann(cash, 0)
    debt_v = _qtr(debt, 0) if _qtr(debt, 0) is not None else _ann(debt, 0)
    net_cash = (cash_v - debt_v) if (cash_v is not None and debt_v is not None) else None

    # ── Market cap ───────────────────────────
    mc = market_d.get("market_cap")
    if not mc or mc <= 0:
        price  = market_d.get("current_price")
        sh_ann = _ann(shr, 0)
        mc = (price * sh_ann) if (price and sh_ann) else None
    market_cap = float(mc) if mc else None

    net_cash_pct = _margin(net_cash, market_cap)   # % of mktcap; negative = net debt

    # ── Valuation multiples ───────────────────
    pe_ratio   = (market_cap / ni_ttm)   if (market_cap and ni_ttm  and ni_ttm  > 0) else None
    pfcf_ratio = (market_cap / fcf_ttm)  if (market_cap and fcf_ttm and fcf_ttm > 0) else None
    ps_ratio   = (market_cap / rev_ttm)  if (market_cap and rev_ttm and rev_ttm > 0) else None

    # PEG = P/E / revenue_growth_pct (revenue growth as growth proxy, capped at reasonable range)
    peg_ratio = None
    if pe_ratio and rev_growth and rev_growth > 1:
        peg_ratio = pe_ratio / rev_growth

    # ── Price position ───────────────────────
    current_price = market_d.get("current_price")
    week_52_high  = market_d.get("week_52_high")
    week_52_low   = market_d.get("week_52_low")

    pct_from_high = None
    if current_price and week_52_high and week_52_high > 0:
        pct_from_high = (current_price - week_52_high) / week_52_high * 100  # ≤ 0

    # ── Implied P/FCF at 52-week high (historical peak multiple proxy) ─────
    implied_pfcf_at_high = None
    if (week_52_high and current_price and current_price > 0
            and market_cap and fcf_ttm and fcf_ttm > 0):
        implied_mktcap_high  = week_52_high / current_price * market_cap
        implied_pfcf_at_high = implied_mktcap_high / fcf_ttm

    # ── Profile-aware signal nulling ──────────
    # Metrics tied to a signal this economic profile marks structurally invalid
    # are nulled here, at the single source. Every downstream consumer (the six
    # scorers, reason_codes, build_mispricing_hypothesis) already handles None,
    # so nulling once here keeps scores, reason codes and hypothesis text
    # consistent instead of guarding each call site separately.
    disabled = get_disabled_signals(economic_profile)
    if "gross_margin" in disabled:
        gm_q0 = gm_q3 = gm_trend = gm_ann = None
    if "fcf_margin" in disabled:
        fcf_margin = fcf_to_ni = pfcf_ratio = implied_pfcf_at_high = None
        fcf_ttm = fcf_ann0 = fcf_ann1 = None
    if "net_cash" in disabled:
        net_cash = net_cash_pct = None

    # ── Commodity-cyclical FCF normalization ──────
    # A commodity price-taker's TTM FCF reflects where it sits in the price
    # cycle, not durable earning power. Peak-cycle FCF makes P/FCF look cheap,
    # fcf_margin look high, and FCF/NI look like exemplary cash conversion — the
    # value-trap signature that ranks a peak cyclical (EQT) #1. For these
    # profiles only — gated on is_commodity_cyclical, the SAME predicate that
    # force-routes the archetype and fires FLAG_CYCLICAL_PEAK_RISK — substitute
    # a trailing mid-cycle FCF average into the FCF-derived ratios the scorers
    # read. Non-cyclical profiles (compounders) are untouched. Raw TTM values
    # (fcf_ttm, mid_cycle_fcf) are preserved alongside for traceability.
    #
    # NOTE: peg_ratio is intentionally NOT normalized here — in this codebase
    # PEG is P/E ÷ revenue-growth (earnings-based), with no FCF term, so an
    # FCF substitution is mechanically a no-op on it. Normalizing PEG would
    # require normalizing net income, which is outside this FCF-only fix.
    mid_cycle_fcf, fcf_norm_years = _mid_cycle_fcf(
        fcf.get("annual", []) if isinstance(fcf, dict) else [],
        capex.get("annual", []) if isinstance(capex, dict) else [],
        rev_ttm=rev_ttm,
    )
    fcf_normalized = False
    fcf_peak_ratio = None
    if (is_commodity_cyclical(economic_profile)
            and "fcf_margin" not in disabled
            and mid_cycle_fcf is not None
            and mid_cycle_fcf > 0):
        fcf_normalized = True
        if fcf_ttm is not None:
            fcf_peak_ratio = fcf_ttm / mid_cycle_fcf
        # Substitute mid-cycle FCF into the ratios the signal functions read.
        pfcf_ratio = (market_cap / mid_cycle_fcf) if market_cap else None
        fcf_margin = _margin(mid_cycle_fcf, rev_ttm)
        fcf_to_ni  = (mid_cycle_fcf / ni_ttm) if (ni_ttm is not None and ni_ttm > 0) else None

    return {
        # Revenue
        "rev_ttm":              rev_ttm,
        "rev_ann0":             rev_ann0,
        "rev_ann1":             rev_ann1,
        "rev_growth":           rev_growth,             # annual YoY %
        "rev_qtrs":             rev_qtrs,               # [newest…oldest], may contain None
        "rev_increasing_pairs": increasing_pairs,       # 0–3
        # Margins
        "gm_q0":                gm_q0,                  # current-quarter gross margin %
        "gm_q3":                gm_q3,                  # 4-quarter-ago gross margin %
        "gm_trend":             gm_trend,               # pp change over 4 quarters
        "gm_ann":               gm_ann,                 # most recent annual gross margin %
        "fcf_margin":           fcf_margin,             # TTM FCF / TTM revenue %
        # FCF / NI
        "fcf_ttm":              fcf_ttm,
        "fcf_ann0":             fcf_ann0,
        "fcf_ann1":             fcf_ann1,
        "ni_ttm":               ni_ttm,
        "ni_ann0":              ni_ann0,
        "fcf_to_ni":            fcf_to_ni,              # quality ratio; >1 = high quality
        # Commodity-cyclical FCF normalization (cyclicals only; else passthrough)
        "mid_cycle_fcf":        mid_cycle_fcf,          # trailing clean-year FCF avg, or None
        "fcf_normalized":       fcf_normalized,         # True → ratios above use mid-cycle FCF
        "fcf_peak_ratio":       fcf_peak_ratio,         # fcf_ttm / mid_cycle_fcf (>1 = peak)
        "fcf_normalization_years": fcf_norm_years,      # clean consecutive years averaged
        # Balance sheet
        "net_cash":             net_cash,               # absolute (negative = net debt)
        "net_cash_pct":         net_cash_pct,           # % of mktcap (negative = net debt)
        # Valuation
        "market_cap":           market_cap,
        "pe_ratio":             pe_ratio,
        "pfcf_ratio":           pfcf_ratio,
        "ps_ratio":             ps_ratio,
        "peg_ratio":            peg_ratio,
        # Price history
        "current_price":        current_price,
        "week_52_high":         week_52_high,
        "week_52_low":          week_52_low,
        "pct_from_high":        pct_from_high,          # % below 52w high (≤ 0)
        "implied_pfcf_at_high": implied_pfcf_at_high,   # peak-valuation proxy
        # Profile
        "economic_profile":     economic_profile,
    }


# ─────────────────────────────────────────────
# 1. BUSINESS QUALITY
# ─────────────────────────────────────────────

def score_business_quality(metrics: dict) -> Optional[float]:
    """
    25% weight. Measures the underlying quality of the business.

    Sub-components:
      Revenue growth YoY      0–30 pts
      Gross margin level       0–20 pts + trend bonus 0–5 pts
      FCF margin (TTM)         0–25 pts
      Net cash vs market cap   0–20 pts

    Returns None only when all four sub-components are unavailable.
    Missing sub-components contribute 0 pts (not scaled up); a company
    missing one component can still score well on the others.
    """
    rev_growth   = metrics.get("rev_growth")
    gm_ann       = metrics.get("gm_ann")
    gm_trend     = metrics.get("gm_trend")
    fcf_margin   = metrics.get("fcf_margin")
    net_cash_pct = metrics.get("net_cash_pct")

    if all(v is None for v in [rev_growth, gm_ann, fcf_margin, net_cash_pct]):
        return None

    score = 0.0

    profile  = metrics.get("economic_profile", "unknown")
    mults    = get_multipliers(profile)
    disabled = get_disabled_signals(profile)

    m_rev = mults.get("revenue_growth_multiplier", 1.0) or 1.0
    m_gm  = mults.get("gross_margin_multiplier",   1.0)
    m_fcf = mults.get("fcf_margin_multiplier",     1.0)

    # Revenue growth (30 pts) — thresholds scaled by profile multiplier
    if rev_growth is not None:
        if rev_growth > 50 * m_rev:     score += 30
        elif rev_growth > 30 * m_rev:   score += 26
        elif rev_growth > 20 * m_rev:   score += 21
        elif rev_growth > 10 * m_rev:   score += 15
        elif rev_growth > 5 * m_rev:    score += 9
        elif rev_growth > 0:            score += 4
        # ≤ 0: 0 pts (shrinking or flat)

    # Gross margin level (20 pts) + trend bonus (5 pts) — skip if disabled
    if "gross_margin" not in disabled and m_gm is not None:
        if gm_ann is not None:
            if gm_ann > 65 * m_gm:     score += 20
            elif gm_ann > 50 * m_gm:   score += 16
            elif gm_ann > 35 * m_gm:   score += 12
            elif gm_ann > 20 * m_gm:   score += 7
            else:                       score += 3   # below profile-adjusted floor
        if gm_trend is not None:
            if gm_trend > 3:    score += 5
            elif gm_trend > 1:  score += 3
            elif gm_trend > -1: score += 1
            # < -1 pp: 0 pts (compressing margins)

    # FCF margin (25 pts) — skip if disabled
    if "fcf_margin" not in disabled and m_fcf is not None:
        if fcf_margin is not None:
            if fcf_margin > 30 * m_fcf:     score += 25
            elif fcf_margin > 20 * m_fcf:   score += 20
            elif fcf_margin > 10 * m_fcf:   score += 13
            elif fcf_margin > 5 * m_fcf:    score += 7
            elif fcf_margin > 0:            score += 3
            # ≤ 0: 0 pts (cash burning)

    # Net cash as % of market cap (20 pts) - skip if disabled for this profile
    # (banks/insurers carry deposits/float as operating liabilities, not leverage)
    if "net_cash" not in disabled and net_cash_pct is not None:
        if net_cash_pct > 10:       score += 20   # Fortress balance sheet
        elif net_cash_pct > 0:      score += 14   # Net cash
        elif net_cash_pct > -15:    score += 8    # Modest net debt
        elif net_cash_pct > -30:    score += 3    # Moderate leverage
        # < -30%: 0 pts (heavily levered)

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 2. VALUATION VS GROWTH
# ─────────────────────────────────────────────

def score_valuation_vs_growth(metrics: dict) -> Optional[float]:
    """
    20% weight. Lower multiples relative to growth rate = higher score.

    Sub-components:
      PEG ratio (P/E / revenue growth)   0–40 pts
      P/FCF                              0–40 pts
      P/S adjusted for growth (PSG)      0–20 pts

    A company with no earnings (P/E undefined) or negative FCF still gets
    scored on the sub-components that are computable.
    """
    peg_ratio  = metrics.get("peg_ratio")
    pfcf_ratio = metrics.get("pfcf_ratio")
    ps_ratio   = metrics.get("ps_ratio")
    rev_growth = metrics.get("rev_growth")

    if all(v is None for v in [peg_ratio, pfcf_ratio, ps_ratio]):
        return None

    score = 0.0

    # PEG ratio: cheap vs growth (40 pts)
    if peg_ratio is not None:
        if peg_ratio < 0.5:     score += 40   # Extremely cheap vs growth
        elif peg_ratio < 1.0:   score += 35
        elif peg_ratio < 1.5:   score += 27
        elif peg_ratio < 2.0:   score += 18
        elif peg_ratio < 3.0:   score += 9
        # ≥ 3: 0 pts
    else:
        log.warning("peg_ratio unavailable — valuation vs growth score contribution set to 0")

    # P/FCF (40 pts)
    if pfcf_ratio is not None:
        if pfcf_ratio < 15:     score += 40
        elif pfcf_ratio < 20:   score += 34
        elif pfcf_ratio < 30:   score += 26
        elif pfcf_ratio < 40:   score += 18
        elif pfcf_ratio < 60:   score += 9
        elif pfcf_ratio < 80:   score += 4
        # ≥ 80: 0 pts
    else:
        score += 20   # Neutral: negative FCF or no data

    # P/S adjusted for growth: PSG = P/S / (rev_growth / 10)
    # PSG < 1 = well-priced growth; PSG > 5 = expensive
    if ps_ratio is not None and rev_growth and rev_growth > 0:
        psg = ps_ratio / (rev_growth / 10)
        if psg < 0.5:    score += 20
        elif psg < 1.0:  score += 16
        elif psg < 2.0:  score += 11
        elif psg < 3.5:  score += 6
        elif psg < 5.0:  score += 2
        # ≥ 5: 0 pts
    elif ps_ratio is not None:
        # No growth data — score P/S on its own
        if ps_ratio < 3:     score += 14
        elif ps_ratio < 8:   score += 8
        elif ps_ratio < 15:  score += 4
        # > 15: 0 pts
    else:
        score += 10   # Neutral

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 2b. VALUATION VS GROWTH — COMPOUNDER MODE
# ─────────────────────────────────────────────

def score_valuation_vs_growth_compounder(metrics: dict) -> Optional[float]:
    """
    Compounder-mode VG signal. Rewards high ABSOLUTE REVENUE GROWTH even at
    premium multiples. Revenue growth gets 40 of 100 points unconditionally;
    PEG and P/FCF fill the remaining 60 points.

    Sub-components:
      Revenue growth tier (absolute)   0–40 pts  (growth is the primary signal)
      PEG ratio                        0–30 pts
      P/FCF                            0–30 pts
    """
    peg_ratio  = metrics.get("peg_ratio")
    pfcf_ratio = metrics.get("pfcf_ratio")
    rev_growth = metrics.get("rev_growth")

    if all(v is None for v in [peg_ratio, pfcf_ratio, rev_growth]):
        return None

    score = 0.0

    profile = metrics.get("economic_profile", "unknown")
    mults   = get_multipliers(profile)
    m_rev   = mults.get("revenue_growth_multiplier", 1.0) or 1.0

    # Revenue growth tier (40 pts) — dominant signal; thresholds scaled by profile
    if rev_growth is not None:
        if rev_growth > 50 * m_rev:     score += 40
        elif rev_growth > 30 * m_rev:   score += 30
        elif rev_growth > 20 * m_rev:   score += 20
        elif rev_growth > 10 * m_rev:   score += 10
        # below sector-adjusted floor: 0 pts — not a compounder growth rate
    else:
        score += 15   # Neutral

    # PEG ratio (30 pts)
    if peg_ratio is not None:
        if peg_ratio < 0.5:     score += 30
        elif peg_ratio < 1.0:   score += 26
        elif peg_ratio < 1.5:   score += 20
        elif peg_ratio < 2.0:   score += 14
        elif peg_ratio < 3.0:   score += 7
        # ≥ 3: 0 pts
    else:
        score += 15   # Neutral

    # P/FCF (30 pts)
    if pfcf_ratio is not None:
        if pfcf_ratio < 15:     score += 30
        elif pfcf_ratio < 20:   score += 26
        elif pfcf_ratio < 30:   score += 20
        elif pfcf_ratio < 40:   score += 14
        elif pfcf_ratio < 60:   score += 7
        elif pfcf_ratio < 80:   score += 3
        # ≥ 80: 0 pts
    else:
        score += 15   # Neutral

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 2c. VALUATION VS GROWTH — QUALITY COMPOUNDER MODE
# ─────────────────────────────────────────────

def score_valuation_vs_growth_quality_compounder(metrics: dict) -> Optional[float]:
    """
    Quality compounder VG signal. Rewards multiples that are reasonable for
    a mature, high-moat business. Does NOT penalize premium multiples when
    gross margin > 40%, FCF margin > 15%, and revenue growth is in the
    steady 5–15% quality compounder range.

    Sub-components:
      P/FCF quality-adjusted     0–60 pts  (relaxed thresholds vs standard VG)
      Revenue growth quality     0–25 pts  (5–15% sweet spot; penalises extremes)
      Gross margin quality gate  0–15 pts  (fingerprint of a durable moat)
    """
    pfcf_ratio = metrics.get("pfcf_ratio")
    rev_growth = metrics.get("rev_growth")
    gm_ann     = metrics.get("gm_ann")

    if all(v is None for v in [pfcf_ratio, rev_growth, gm_ann]):
        return None

    score = 0.0

    profile  = metrics.get("economic_profile", "unknown")
    mults    = get_multipliers(profile)
    disabled = get_disabled_signals(profile)
    m_gm     = mults.get("gross_margin_multiplier", 1.0)

    # P/FCF quality-adjusted (60 pts)
    # Premium multiples are acceptable for mature businesses with durable moats;
    # thresholds are deliberately more lenient than the standard VG signal.
    if pfcf_ratio is not None:
        if pfcf_ratio < 20:     score += 60   # Cheap even for quality
        elif pfcf_ratio < 30:   score += 52   # Good for a quality compounder
        elif pfcf_ratio < 40:   score += 42   # Fair
        elif pfcf_ratio < 50:   score += 30   # Stretched but acceptable
        elif pfcf_ratio < 60:   score += 18   # Expensive
        else:                   score += 8    # Too expensive — not 0, quality can sustain
    else:
        score += 30   # Neutral: negative FCF or capex cycle (not unusual for quality)

    # Revenue growth in the quality range (25 pts)
    # Rewards steady, durable growth — too fast signals long_term_compounder,
    # too slow signals stagnation.
    if rev_growth is not None:
        if 10 <= rev_growth < 15:   score += 25   # Ideal quality compounder cadence
        elif 5 <= rev_growth < 10:  score += 20   # Steady
        elif 15 <= rev_growth < 20: score += 18   # Slightly above quality range
        elif 3 <= rev_growth < 5:   score += 12   # Mature, still growing
        elif 20 <= rev_growth < 30: score += 10   # More of a long_term_compounder
        elif 0 < rev_growth < 3:    score += 5    # Flat
        elif rev_growth >= 30:      score += 5    # Fast grower — wrong archetype
        # ≤ 0: 0 pts — declining revenue disqualifies quality compounder thesis
    else:
        score += 12   # Neutral

    # Gross margin quality gate (15 pts) — skip if disabled for this profile
    if "gross_margin" not in disabled and m_gm is not None and gm_ann is not None:
        if gm_ann > 60 * m_gm:     score += 15   # Exceptional for this profile
        elif gm_ann > 40 * m_gm:   score += 10   # Strong quality business
        elif gm_ann > 25 * m_gm:   score += 5    # Acceptable
        # below profile-adjusted floor: 0 pts — commodity economics

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 3. HISTORICAL DISCOUNT
# ─────────────────────────────────────────────

def score_historical_discount(metrics: dict) -> Optional[float]:
    """
    15% weight. Is the stock cheaper now than it was at its recent high,
    adjusted for fundamental improvement?

    Sub-components:
      P/FCF compression from 52-week high     0–50 pts
      Price position within 52-week range     0–30 pts
      FCF growth acceleration vs prior year   0–20 pts
    """
    pfcf_ratio          = metrics.get("pfcf_ratio")
    implied_pfcf_high   = metrics.get("implied_pfcf_at_high")
    pct_from_high       = metrics.get("pct_from_high")
    week_52_high        = metrics.get("week_52_high")
    week_52_low         = metrics.get("week_52_low")
    current_price       = metrics.get("current_price")
    fcf_ttm             = metrics.get("fcf_ttm")
    fcf_ann0            = metrics.get("fcf_ann0")
    fcf_ann1            = metrics.get("fcf_ann1")

    if pfcf_ratio is None and pct_from_high is None and fcf_ttm is None:
        return None

    score = 0.0

    # P/FCF compression from peak (50 pts)
    # implied_pfcf_at_high = P/FCF if stock were at 52w high with today's FCF
    # A lower current P/FCF vs peak = discount
    if pfcf_ratio is not None and implied_pfcf_high is not None and implied_pfcf_high > 0:
        compression_pct = (implied_pfcf_high - pfcf_ratio) / implied_pfcf_high * 100
        if compression_pct > 50:    score += 50   # Deeply discounted
        elif compression_pct > 35:  score += 40
        elif compression_pct > 20:  score += 30
        elif compression_pct > 10:  score += 18
        elif compression_pct > 0:   score += 8    # Slight discount
        # ≤ 0: re-rated higher (price > 52w high adjusted for FCF)
    elif pfcf_ratio is not None:
        # No implied high: use absolute P/FCF as proxy for value
        if pfcf_ratio < 20:     score += 35
        elif pfcf_ratio < 30:   score += 22
        elif pfcf_ratio < 50:   score += 12
        # > 50: 0 pts

    # Price position within 52-week range (30 pts)
    if pct_from_high is not None:
        drawdown = abs(pct_from_high)
        if drawdown > 40:    score += 30   # Near 52-week low
        elif drawdown > 25:  score += 23
        elif drawdown > 15:  score += 15
        elif drawdown > 8:   score += 8
        elif drawdown > 3:   score += 3
        # < 3%: near 52-week high — no historical discount

    # FCF growth acceleration (20 pts): TTM FCF vs prior annual FCF
    if fcf_ttm is not None and fcf_ann1 is not None and fcf_ann1 > 0:
        fcf_growth = (fcf_ttm - fcf_ann1) / fcf_ann1 * 100
        if fcf_growth > 60:     score += 20   # FCF surged; price likely lagged
        elif fcf_growth > 30:   score += 15
        elif fcf_growth > 10:   score += 9
        elif fcf_growth > 0:    score += 4
        # ≤ 0: FCF not growing — no acceleration discount

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 4. EARNINGS QUALITY
# ─────────────────────────────────────────────

def score_earnings_quality(metrics: dict) -> Optional[float]:
    """
    20% weight. High-quality earnings are confirmed by cash generation,
    expanding gross margins, and consistent revenue growth.

    Sub-components:
      FCF / net income ratio      0–40 pts  (>1 = earnings are real cash)
      Gross margin trend          0–35 pts  (expanding = pricing power)
      Revenue growth consistency  0–25 pts  (all 4 quarters growing)
    """
    fcf_to_ni          = metrics.get("fcf_to_ni")
    gm_trend           = metrics.get("gm_trend")
    gm_q0              = metrics.get("gm_q0")
    rev_increasing_pairs = metrics.get("rev_increasing_pairs")
    rev_growth         = metrics.get("rev_growth")

    if all(v is None for v in [fcf_to_ni, gm_trend, rev_increasing_pairs]):
        return None

    score = 0.0

    # FCF / net income (40 pts)
    # > 1.0: FCF exceeds reported earnings (high quality, low accruals)
    # < 0.5: reported earnings well exceed FCF (potential accrual inflation)
    if fcf_to_ni is not None:
        if fcf_to_ni > 1.3:     score += 40   # Exemplary cash conversion
        elif fcf_to_ni > 1.0:   score += 33
        elif fcf_to_ni > 0.7:   score += 22
        elif fcf_to_ni > 0.5:   score += 12
        elif fcf_to_ni > 0.0:   score += 5
        # ≤ 0: negative FCF vs positive earnings — poor quality
    else:
        score += 20   # Neutral: cannot compute (missing data)

    # Gross margin trend over 4 quarters (35 pts)
    if gm_trend is not None:
        if gm_trend > 5:        score += 35   # Significant margin expansion
        elif gm_trend > 2:      score += 27
        elif gm_trend > 0.5:    score += 18
        elif gm_trend > -0.5:   score += 12   # Roughly flat (stable pricing)
        elif gm_trend > -2:     score += 5
        # < -2 pp: material margin compression
    elif gm_q0 is not None:
        # Trend not computable; score on current margin level only
        if gm_q0 > 60:      score += 20
        elif gm_q0 > 40:    score += 12
        elif gm_q0 > 25:    score += 6
    else:
        score += 12   # Neutral

    # Revenue consistency (25 pts): how many of 3 QoQ pairs were increasing?
    if rev_increasing_pairs is not None:
        score += rev_increasing_pairs / 3 * 25
    elif rev_growth is not None:
        # Fallback: use annual YoY growth as consistency proxy
        if rev_growth > 10:     score += 18
        elif rev_growth > 0:    score += 9
    else:
        score += 10   # Neutral

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 5. ENTRY POINT VS FUNDAMENTALS
# ─────────────────────────────────────────────

def score_entry_vs_fundamentals(metrics: dict) -> Optional[float]:
    """
    12% weight. Asks: has price fallen or stagnated while fundamentals
    (revenue, FCF) accelerated? High score = attractive entry relative to
    recent fundamental improvement.

    Sub-components:
      Price drawdown from 52-week high   0–55 pts
      Revenue growth rate (fundamental)  0–30 pts
      FCF acceleration vs prior year     0–15 pts
    """
    pct_from_high = metrics.get("pct_from_high")
    rev_growth    = metrics.get("rev_growth")
    fcf_ttm       = metrics.get("fcf_ttm")
    fcf_ann1      = metrics.get("fcf_ann1")

    if pct_from_high is None and rev_growth is None:
        return None

    score = 0.0

    profile = metrics.get("economic_profile", "unknown")
    mults   = get_multipliers(profile)
    m_rev   = mults.get("revenue_growth_multiplier", 1.0) or 1.0

    # Price drawdown from 52-week high (55 pts)
    # A deeper drawdown with improving fundamentals = better entry
    if pct_from_high is not None:
        drawdown = abs(pct_from_high)
        if drawdown > 45:       score += 55   # Near 52-week low — deep value
        elif drawdown > 30:     score += 45
        elif drawdown > 20:     score += 32
        elif drawdown > 12:     score += 20
        elif drawdown > 6:      score += 10
        elif drawdown > 2:      score += 4
        # < 2%: near 52-week high — no entry discount
    else:
        score += 20   # Neutral

    # Revenue growth rate (30 pts) — thresholds scaled by sector multiplier
    if rev_growth is not None:
        if rev_growth > 50 * m_rev:     score += 30
        elif rev_growth > 30 * m_rev:   score += 24
        elif rev_growth > 20 * m_rev:   score += 18
        elif rev_growth > 10 * m_rev:   score += 11
        elif rev_growth > 0:            score += 5
        # ≤ 0: 0 pts — declining fundamentals make any entry less attractive
    else:
        score += 10   # Neutral

    # FCF acceleration: TTM FCF vs prior annual FCF (15 pts)
    if fcf_ttm is not None and fcf_ann1 is not None and fcf_ann1 > 0:
        fcf_accel = (fcf_ttm - fcf_ann1) / fcf_ann1 * 100
        if fcf_accel > 50:      score += 15
        elif fcf_accel > 20:    score += 10
        elif fcf_accel > 5:     score += 6
        elif fcf_accel > 0:     score += 3
        # ≤ 0: FCF declining or flat
    else:
        score += 5   # Neutral

    return min(100.0, max(0.0, score))


# ─────────────────────────────────────────────
# 6. BINARY EVENT RISK
# ─────────────────────────────────────────────

def score_binary_event_risk(earnings_d: dict) -> Optional[float]:
    """
    8% weight. HIGH score = LOW binary event risk (no imminent gap catalyst).
    Earnings within 14 days reduces the ceiling by penalizing this component.

    The signal is intentionally inverted: a company with earnings in 3 days
    is a binary bet, not a screening candidate. The penalty here creates a
    meaningful composite drag that filters such setups toward the short list
    only when all other signals are exceptional.

    Returns None only if earnings_d is completely empty (no data at all).
    """
    if not earnings_d:
        return None

    days_to = earnings_d.get("days_to_earnings")
    if days_to is None:
        log.warning("days_to_earnings missing — binary risk score defaulting to 50.0 (unknown)")
        return 50.0

    if days_to > 90:    return 92.0   # Far away — no binary risk
    elif days_to > 45:  return 78.0   # On radar, not imminent
    elif days_to > 21:  return 62.0   # Approaching — worth noting
    elif days_to > 14:  return 45.0   # Active watch window
    elif days_to > 7:   return 28.0   # Imminent — flagged as gap risk
    elif days_to > 3:   return 15.0   # This week — binary event
    else:               return 5.0    # Imminent — maximum binary risk


# ─────────────────────────────────────────────
# MISPRICING HYPOTHESIS
# ─────────────────────────────────────────────

def build_mispricing_hypothesis(
    ticker:    str,
    scores:    SignalScores,
    metrics:   dict,
    earnings_d: dict,
    composite: Optional[float] = None,
) -> str:
    """
    Generate a plain-English mispricing hypothesis for Stage 02 research.
    The hypothesis explains the composite score in terms of specific fundamental
    data points and flags the primary research question for the deep-research agent.

    composite — regime-weighted composite from the screener (if None, an
                unweighted average is used as a fallback).
    """
    parts: list[str] = []

    # ── Composite score summary ───────────────
    if composite is None:
        all_scores = [
            scores.business_quality, scores.valuation_vs_growth,
            scores.historical_discount, scores.earnings_quality,
            scores.entry_vs_fundamentals, scores.binary_event_risk,
        ]
        valid_scores = [s for s in all_scores if s is not None]
        composite = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0

    conv = "high-conviction" if composite >= 70 else "moderate" if composite >= 50 else "low"
    parts.append(f"{ticker} screens at {composite:.1f}/100 ({conv} fundamental score).")

    # ── Business quality narrative ────────────
    rev_growth = metrics.get("rev_growth")
    gm_ann     = metrics.get("gm_ann")
    fcf_margin = metrics.get("fcf_margin")
    bq         = scores.business_quality

    if bq is not None and bq >= 60:
        details = []
        if rev_growth is not None:
            details.append(f"{rev_growth:+.0f}% revenue growth YoY")
        if gm_ann is not None:
            details.append(f"{gm_ann:.0f}% gross margin")
        if fcf_margin is not None:
            details.append(f"{fcf_margin:.0f}% FCF margin")
        if details:
            parts.append(f"Business quality is strong ({bq:.0f}/100): {', '.join(details)}.")
    elif bq is not None and bq < 40:
        issues = []
        if rev_growth is not None and rev_growth <= 0:
            issues.append(f"revenue declining {rev_growth:.0f}% YoY")
        if fcf_margin is not None and fcf_margin < 0:
            issues.append("negative FCF margin")
        if issues:
            parts.append(f"Business quality is a concern ({bq:.0f}/100): {', '.join(issues)}.")

    # ── Valuation vs growth narrative ─────────
    peg    = metrics.get("peg_ratio")
    pfcf   = metrics.get("pfcf_ratio")
    vg     = scores.valuation_vs_growth

    if vg is not None:
        val_details = []
        if peg is not None:
            val_details.append(f"PEG {peg:.1f}×")
        if pfcf is not None:
            val_details.append(f"P/FCF {pfcf:.0f}×")
        if val_details:
            if vg >= 60:
                parts.append(f"Valuation is attractive vs growth ({vg:.0f}/100): {', '.join(val_details)}.")
            elif vg < 35:
                parts.append(f"Valuation is stretched ({vg:.0f}/100): {', '.join(val_details)}.")
            else:
                parts.append(f"Valuation is fair vs growth ({vg:.0f}/100): {', '.join(val_details)}.")

    # Commodity-cyclical FCF normalization disclosure: P/FCF, fcf_margin and
    # FCF/NI above use a trailing mid-cycle FCF average, not peak-cycle TTM FCF.
    if metrics.get("fcf_normalized"):
        ttm  = metrics.get("fcf_ttm")
        mid  = metrics.get("mid_cycle_fcf")
        yrs  = metrics.get("fcf_normalization_years")
        if ttm is not None and mid is not None:
            parts.append(
                f"FCF normalized for cyclicality: TTM FCF ${ttm/1e9:.2f}B vs "
                f"{yrs}yr mid-cycle ${mid/1e9:.2f}B "
                f"({metrics.get('fcf_peak_ratio'):.2f}× peak) — valuation/quality "
                f"signals scored on the mid-cycle figure to avoid extrapolating "
                f"peak-cycle cash flow."
            )

    # ── Historical discount narrative ─────────
    pct_from_high = metrics.get("pct_from_high")
    hd = scores.historical_discount

    if hd is not None and pct_from_high is not None:
        if hd >= 65:
            parts.append(
                f"Stock trades {abs(pct_from_high):.0f}% below its 52-week high "
                f"while fundamentals have improved — historical discount confirmed ({hd:.0f}/100)."
            )
        elif hd < 35 and pct_from_high is not None and abs(pct_from_high) < 5:
            parts.append(
                f"Stock is near its 52-week high ({abs(pct_from_high):.0f}% below) "
                f"— limited historical discount ({hd:.0f}/100)."
            )

    # ── Earnings quality narrative ─────────────
    fcf_to_ni = metrics.get("fcf_to_ni")
    gm_trend  = metrics.get("gm_trend")
    eq        = scores.earnings_quality

    if eq is not None:
        eq_details = []
        if fcf_to_ni is not None:
            direction = "exceeds" if fcf_to_ni >= 1.0 else "trails"
            eq_details.append(f"FCF {direction} net income at {fcf_to_ni:.2f}×")
        if gm_trend is not None:
            trend_word = "expanding" if gm_trend > 0.5 else "flat" if gm_trend > -0.5 else "compressing"
            eq_details.append(f"gross margins are {trend_word} ({gm_trend:+.1f}pp over 4 quarters)")
        if eq_details:
            parts.append(f"Earnings quality is {'high' if eq >= 65 else 'mixed' if eq >= 45 else 'low'} "
                         f"({eq:.0f}/100): {'; '.join(eq_details)}.")

    # ── Binary event risk ─────────────────────
    days_to = earnings_d.get("days_to_earnings") if earnings_d else None
    br = scores.binary_event_risk

    if days_to is not None and days_to <= 14:
        parts.append(
            f"BINARY RISK: Earnings report in {days_to} days — "
            f"gap risk is elevated; position sizing should reflect this."
        )

    # ── Research focus ─────────────────────────
    # Identify the weakest signal to direct Stage 02 research
    signal_labels = {
        "business_quality":      ("BQ", scores.business_quality),
        "valuation_vs_growth":   ("VG", scores.valuation_vs_growth),
        "historical_discount":   ("HD", scores.historical_discount),
        "earnings_quality":      ("EQ", scores.earnings_quality),
        "entry_vs_fundamentals": ("EF", scores.entry_vs_fundamentals),
    }
    valid_labeled = {k: v for k, (_, v) in signal_labels.items() if v is not None}
    if valid_labeled:
        weakest_key = min(valid_labeled, key=lambda k: valid_labeled[k])
        research_focus_map = {
            "business_quality":      "Verify revenue growth durability and margin sustainability.",
            "valuation_vs_growth":   "Assess whether the current valuation is justified by the growth runway.",
            "historical_discount":   "Confirm whether the valuation premium is warranted by improved fundamentals.",
            "earnings_quality":      "Investigate FCF conversion quality and gross margin trajectory.",
            "entry_vs_fundamentals": "Determine whether the price has already re-rated or remains disconnected from fundamentals.",
        }
        focus = research_focus_map.get(weakest_key, "Conduct full fundamental review.")
        parts.append(f"Stage 02 research focus: {focus}")

    return " ".join(parts)
