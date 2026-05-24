"""
reason_codes.py
Assigns human-readable reason codes and investigation flags to each screened ticker.

Reason codes explain WHY a ticker was selected — the specific fundamental data
points that drove it onto the shortlist. Stage 02 researchers read these first.

Flags mark concerns — they do NOT disqualify a ticker. A passing ticker with
a flag still passed screening; the flag tells Stage 02 what to scrutinize.
"""

import logging
from typing import List, Tuple
from signal_scorer import SignalScores
from economic_profile_classifier import get_disabled_signals, is_commodity_cyclical

log = logging.getLogger("reason_codes")


# ─────────────────────────────────────────────
# REASON CODES
# ─────────────────────────────────────────────

STRONG_REVENUE_GROWTH    = "STRONG_REVENUE_GROWTH"    # revenue growth > 25% YoY
MODERATE_REVENUE_GROWTH  = "MODERATE_REVENUE_GROWTH"  # revenue growth 10–25% YoY
HIGH_GROSS_MARGIN        = "HIGH_GROSS_MARGIN"         # gross margin > 55%
EXPANDING_MARGINS        = "EXPANDING_MARGINS"         # gross margin expanding > 2pp over 4Q
STRONG_FCF               = "STRONG_FCF"               # FCF margin > 20%
NET_CASH_FORTRESS        = "NET_CASH_FORTRESS"         # net cash > 5% of market cap
UNDERVALUED_PEG          = "UNDERVALUED_PEG"           # PEG < 1.0
LOW_PFCF                 = "LOW_PFCF"                  # P/FCF < 20×
HISTORICAL_DISCOUNT      = "HISTORICAL_DISCOUNT"       # > 20% below 52-week high with improving FCF
HIGH_EARNINGS_QUALITY    = "HIGH_EARNINGS_QUALITY"     # FCF > 1.0× net income
REVENUE_ACCELERATION     = "REVENUE_ACCELERATION"      # all 3 QoQ pairs increasing
MULTI_SIGNAL_CONFLUENCE  = "MULTI_SIGNAL_CONFLUENCE"   # ≥ 3 signals score ≥ 65

REASON_CODE_DESCRIPTIONS = {
    STRONG_REVENUE_GROWTH:   "Revenue growing > 25% YoY — top-line momentum is strong",
    MODERATE_REVENUE_GROWTH: "Revenue growing 10–25% YoY — steady fundamental growth",
    HIGH_GROSS_MARGIN:       "Gross margin > 55% — differentiated product with pricing power",
    EXPANDING_MARGINS:       "Gross margin expanding > 2pp over 4 quarters — pricing power strengthening",
    STRONG_FCF:              "FCF margin > 20% — high-quality cash generator",
    NET_CASH_FORTRESS:       "Net cash > 5% of market cap — balance sheet optionality",
    UNDERVALUED_PEG:         "PEG < 1.0 — priced below its revenue growth rate",
    LOW_PFCF:                "P/FCF < 20× — cheap on a cash flow basis",
    HISTORICAL_DISCOUNT:     "Trading > 20% below 52-week high with FCF improving — potential mispricing",
    HIGH_EARNINGS_QUALITY:   "FCF exceeds net income — reported earnings are real, not accrual-driven",
    REVENUE_ACCELERATION:    "All 4 quarters showing sequential revenue growth — momentum confirmed",
    MULTI_SIGNAL_CONFLUENCE: "Three or more fundamental signals scoring ≥ 65 — high multi-factor alignment",
}


# ─────────────────────────────────────────────
# INVESTIGATION FLAGS
# ─────────────────────────────────────────────

FLAG_BINARY_EVENT_RISK   = "FLAG_BINARY_EVENT_RISK"    # Earnings within 14 days
FLAG_FCF_BELOW_EARNINGS  = "FLAG_FCF_BELOW_EARNINGS"   # FCF < 0.6× net income (accrual risk)
FLAG_DECLINING_MARGINS   = "FLAG_DECLINING_MARGINS"    # Gross margin declining > 2pp
FLAG_HIGH_LEVERAGE       = "FLAG_HIGH_LEVERAGE"        # Net debt > 25% of market cap
FLAG_NEGATIVE_FCF        = "FLAG_NEGATIVE_FCF"         # TTM FCF is negative
FLAG_REVENUE_DECLINING   = "FLAG_REVENUE_DECLINING"    # Revenue growth YoY ≤ 0%
FLAG_HIGH_PFCF           = "FLAG_HIGH_PFCF"            # P/FCF > 60× (expensive on cash basis)

FLAG_CYCLICAL_PEAK_RISK  = "FLAG_CYCLICAL_PEAK_RISK"   # commodity-cyclical profile at peak-cycle FCF

FLAG_DESCRIPTIONS = {
    FLAG_CYCLICAL_PEAK_RISK: "Commodity-cyclical business (energy E&P/integrated/midstream) generating peak-cycle FCF - current cash flow reflects elevated commodity prices, not durable earnings power. Do not extrapolate.",
    FLAG_BINARY_EVENT_RISK:  "Earnings within 14 days — gap risk is elevated. Assess setup quality vs event risk.",
    FLAG_FCF_BELOW_EARNINGS: "FCF < 0.6× net income — reported earnings may be inflated by accruals. Verify cash flow statement.",
    FLAG_DECLINING_MARGINS:  "Gross margin declining > 2pp over 4 quarters — pricing power or cost pressure. Identify cause.",
    FLAG_HIGH_LEVERAGE:      "Net debt > 25% of market cap — balance sheet risk in a tightening cycle. Review debt maturity.",
    FLAG_NEGATIVE_FCF:       "TTM free cash flow is negative — company is not yet self-funding. Verify path to FCF breakeven.",
    FLAG_REVENUE_DECLINING:  "Revenue declining YoY — fundamental deterioration. Verify this is not a one-time comp issue.",
    FLAG_HIGH_PFCF:          "P/FCF > 60× — expensive on a cash flow basis. Requires exceptional growth to justify.",
}


# ─────────────────────────────────────────────
# ASSIGNMENT LOGIC
# ─────────────────────────────────────────────

_DISABLED_SIGNAL_CODES = {
    "net_cash":     {NET_CASH_FORTRESS, FLAG_HIGH_LEVERAGE},
    "gross_margin": {HIGH_GROSS_MARGIN, EXPANDING_MARGINS, FLAG_DECLINING_MARGINS},
    "fcf_margin":   {STRONG_FCF, FLAG_NEGATIVE_FCF},
}


def assign_reason_codes(
    scores:  SignalScores,
    record:  dict,
) -> Tuple[List[str], List[str]]:
    """
    Assign reason codes and flags for a scored ticker.

    Args:
        scores: SignalScores dataclass with 0–100 floats (or None for missing data)
        record: Full raw signal record dict (must include "fundamental_metrics" key
                populated by screener.py from compute_fundamental_metrics output)

    Returns:
        (reason_codes, flags) — both lists of string constants
    """
    codes:   List[str] = []
    flags:   List[str] = []

    m        = record.get("fundamental_metrics", {})
    earn_d   = record.get("earnings_data", {})

    rev_growth   = m.get("rev_growth")
    gm_ann       = m.get("gm_ann")
    gm_trend     = m.get("gm_trend")
    fcf_margin   = m.get("fcf_margin")
    fcf_to_ni    = m.get("fcf_to_ni")
    net_cash_pct = m.get("net_cash_pct")
    peg_ratio    = m.get("peg_ratio")
    pfcf_ratio   = m.get("pfcf_ratio")
    pct_from_high = m.get("pct_from_high")
    fcf_ttm      = m.get("fcf_ttm")
    fcf_ann1     = m.get("fcf_ann1")
    rev_pairs    = m.get("rev_increasing_pairs")

    # ── Reason Codes ──────────────────────────

    # Revenue growth
    if rev_growth is not None:
        if rev_growth > 25:     codes.append(STRONG_REVENUE_GROWTH)
        elif rev_growth > 10:   codes.append(MODERATE_REVENUE_GROWTH)

    # Gross margin
    if gm_ann is not None and gm_ann > 55:
        codes.append(HIGH_GROSS_MARGIN)

    # Margin trend
    if gm_trend is not None and gm_trend > 2:
        codes.append(EXPANDING_MARGINS)

    # FCF strength
    if fcf_margin is not None and fcf_margin > 20:
        codes.append(STRONG_FCF)

    # Balance sheet
    if net_cash_pct is not None and net_cash_pct > 5:
        codes.append(NET_CASH_FORTRESS)

    # Valuation
    if peg_ratio is not None and peg_ratio < 1.0:
        codes.append(UNDERVALUED_PEG)
    if pfcf_ratio is not None and pfcf_ratio < 20:
        codes.append(LOW_PFCF)

    # Historical discount
    if (pct_from_high is not None and abs(pct_from_high) > 20
            and fcf_ttm is not None and fcf_ann1 is not None
            and fcf_ttm > fcf_ann1):
        codes.append(HISTORICAL_DISCOUNT)

    # Earnings quality
    if fcf_to_ni is not None and fcf_to_ni >= 1.0:
        codes.append(HIGH_EARNINGS_QUALITY)

    # Revenue acceleration
    if rev_pairs is not None and rev_pairs >= 3:
        codes.append(REVENUE_ACCELERATION)

    # Multi-signal confluence
    strong = sum([
        (scores.business_quality      or 0) >= 65,
        (scores.valuation_vs_growth   or 0) >= 65,
        (scores.historical_discount   or 0) >= 65,
        (scores.earnings_quality      or 0) >= 65,
        (scores.entry_vs_fundamentals or 0) >= 65,
    ])
    if strong >= 3:
        codes.append(MULTI_SIGNAL_CONFLUENCE)

    # ── Flags ─────────────────────────────────

    # Binary event risk
    days_to = earn_d.get("days_to_earnings")
    if days_to is None:
        ticker = record.get("ticker", "UNKNOWN")
        log.warning("%s: days_to_earnings missing — FLAG_BINARY_EVENT_RISK cannot be evaluated", ticker)
    elif days_to <= 14:
        flags.append(FLAG_BINARY_EVENT_RISK)

    # FCF quality concern
    if fcf_to_ni is not None and fcf_to_ni < 0.6:
        flags.append(FLAG_FCF_BELOW_EARNINGS)

    # Negative FCF
    if fcf_ttm is not None and fcf_ttm < 0:
        flags.append(FLAG_NEGATIVE_FCF)

    # Margin compression
    if gm_trend is not None and gm_trend < -2:
        flags.append(FLAG_DECLINING_MARGINS)

    # Leverage
    if net_cash_pct is not None and net_cash_pct < -25:
        flags.append(FLAG_HIGH_LEVERAGE)

    # Revenue decline
    if rev_growth is not None and rev_growth <= 0:
        flags.append(FLAG_REVENUE_DECLINING)

    # Expensive on FCF basis
    if pfcf_ratio is not None and pfcf_ratio > 60:
        flags.append(FLAG_HIGH_PFCF)

    # ── Profile-aware adjustments ─────────────
    economic_profile = record.get("classification", {}).get("economic_profile", "unknown")

    # Commodity-cyclical peak-cycle warning: a price-taker generating a high
    # FCF margin is almost certainly riding elevated commodity prices.
    if is_commodity_cyclical(economic_profile) and fcf_margin is not None and fcf_margin > 15:
        flags.append(FLAG_CYCLICAL_PEAK_RISK)

    # Suppress codes/flags tied to signals structurally disabled for this profile.
    disabled = get_disabled_signals(economic_profile)
    if disabled:
        suppressed = set()
        for sig in disabled:
            suppressed |= _DISABLED_SIGNAL_CODES.get(sig, set())
        codes = [c for c in codes if c not in suppressed]
        flags = [f for f in flags if f not in suppressed]

    return codes, flags
