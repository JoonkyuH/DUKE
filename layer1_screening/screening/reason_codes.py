"""
reason_codes.py
Assigns human-readable reason codes and investigation flags to each screened ticker.

Reason codes explain WHY a ticker was selected. They are the first thing a
human (or Layer 2 agent) reads when deciding where to focus deep research.

Flags mark concerns — they do NOT disqualify a ticker. A ticker with a flag
still passed screening; the flag tells Layer 2 what to scrutinize first.
"""

from typing import List, Tuple
from signal_scorer import SignalScores


# ─────────────────────────────────────────────
# REASON CODES
# ─────────────────────────────────────────────

MOMENTUM_BREAKOUT          = "MOMENTUM_BREAKOUT"           # momentum ≥ 80
MOMENTUM_STRONG            = "MOMENTUM_STRONG"             # momentum ≥ 60
RS_MARKET_LEADER           = "RS_MARKET_LEADER"            # RS vs market ≥ 80
RS_SECTOR_TOP_QUARTILE     = "RS_SECTOR_TOP_QUARTILE"      # RS vs sector ≥ 60
VOLUME_SURGE               = "VOLUME_SURGE"                # volume_ratio ≥ 2.0
VOLUME_ABOVE_AVERAGE       = "VOLUME_ABOVE_AVERAGE"        # volume_ratio ≥ 1.3
SECTOR_LEADER              = "SECTOR_LEADER"               # sector leadership ≥ 75
NEWS_ACCELERATION          = "NEWS_ACCELERATION"           # news velocity ≥ 65
EARNINGS_CATALYST_IMMINENT = "EARNINGS_CATALYST_IMMINENT"  # ≤ 7 days to earnings
EARNINGS_CATALYST_WINDOW   = "EARNINGS_CATALYST_WINDOW"    # ≤ 21 days to earnings
MULTI_SIGNAL_CONFLUENCE    = "MULTI_SIGNAL_CONFLUENCE"     # ≥ 3 signals score ≥ 65

REASON_CODE_DESCRIPTIONS = {
    MOMENTUM_BREAKOUT:          "Strong price momentum — above all key MAs with high ROC",
    MOMENTUM_STRONG:            "Solid price trend — above most MAs with positive ROC",
    RS_MARKET_LEADER:           "Significantly outperforming the broad market",
    RS_SECTOR_TOP_QUARTILE:     "Leading within its sector peer group",
    VOLUME_SURGE:               "Volume ≥2× the 20-day average — institutional activity signal",
    VOLUME_ABOVE_AVERAGE:       "Volume above recent average — participation increasing",
    SECTOR_LEADER:              "Top quartile performer in a sector outperforming the market",
    NEWS_ACCELERATION:          "News coverage accelerating with quality sources",
    EARNINGS_CATALYST_IMMINENT: "Earnings report within 7 days — near-term catalyst window",
    EARNINGS_CATALYST_WINDOW:   "Earnings within 21 days — setup window active",
    MULTI_SIGNAL_CONFLUENCE:    "Three or more signals scoring ≥65 — high multi-factor alignment",
}


# ─────────────────────────────────────────────
# INVESTIGATION FLAGS
# ─────────────────────────────────────────────

FLAG_OVERBOUGHT_RSI      = "FLAG_OVERBOUGHT_RSI"        # RSI > 78
FLAG_HIGH_VOL_DOWN_DAY   = "FLAG_HIGH_VOL_DOWN_DAY"     # High volume + down day (distribution)
FLAG_NEGATIVE_NEWS       = "FLAG_NEGATIVE_NEWS"          # Sentiment score < -0.3
FLAG_WEAK_SECTOR         = "FLAG_WEAK_SECTOR"            # Sector RS negative
FLAG_LOW_SOURCE_QUALITY  = "FLAG_LOW_SOURCE_QUALITY"     # News velocity driven by low-quality sources
FLAG_EARNINGS_GAP_RISK   = "FLAG_EARNINGS_GAP_RISK"      # Earnings within 5 days — binary event risk

FLAG_DESCRIPTIONS = {
    FLAG_OVERBOUGHT_RSI:     "RSI > 78: price may be extended short-term. Layer 2: check for parabolic structure.",
    FLAG_HIGH_VOL_DOWN_DAY:  "High volume on a down day suggests distribution. Layer 2: check for failed breakout.",
    FLAG_NEGATIVE_NEWS:      "Negative news sentiment detected. Layer 2: identify source and verify materiality.",
    FLAG_WEAK_SECTOR:        "Sector is underperforming the market. Layer 2: confirm ticker is a true relative leader.",
    FLAG_LOW_SOURCE_QUALITY: "News velocity is driven by social/low-quality sources. Apply low evidence weight.",
    FLAG_EARNINGS_GAP_RISK:  "Earnings within 5 days — binary event risk. Layer 2: assess gap risk vs setup quality.",
}


# ─────────────────────────────────────────────
# ASSIGNMENT LOGIC
# ─────────────────────────────────────────────

def assign_reason_codes(
    scores: SignalScores,
    record: dict,
) -> Tuple[List[str], List[str]]:
    """
    Assign reason codes and flags for a scored ticker.

    Args:
        scores: SignalScores dataclass with 0–100 floats (or None for missing data)
        record: Full raw signal record dict

    Returns:
        (reason_codes, flags) — both lists of string constants
    """
    codes: List[str] = []
    flags: List[str] = []

    price    = record.get("price_data", {})
    news     = record.get("news_data", {})
    earnings = record.get("earnings_data", {})
    rs_data  = record.get("relative_strength", {})

    # ── Reason Codes ──────────────────────────

    # Momentum
    mom = scores.momentum
    if mom is not None:
        if mom >= 80:   codes.append(MOMENTUM_BREAKOUT)
        elif mom >= 60: codes.append(MOMENTUM_STRONG)

    # Relative strength
    rs = scores.relative_strength
    if rs is not None:
        if rs >= 80:    codes.append(RS_MARKET_LEADER)
        elif rs >= 60:  codes.append(RS_SECTOR_TOP_QUARTILE)

    # Volume
    vol = scores.volume_anomaly
    vol_ratio = price.get("volume_ratio", 1.0)
    if vol is not None:
        if vol_ratio >= 2.0:   codes.append(VOLUME_SURGE)
        elif vol_ratio >= 1.3: codes.append(VOLUME_ABOVE_AVERAGE)

    # Sector leadership
    if scores.sector_leadership is not None and scores.sector_leadership >= 75:
        codes.append(SECTOR_LEADER)

    # News velocity
    if scores.news_velocity is not None and scores.news_velocity >= 65:
        codes.append(NEWS_ACCELERATION)

    # Earnings proximity
    days_to = earnings.get("days_to_earnings", 999)
    if days_to <= 7:        codes.append(EARNINGS_CATALYST_IMMINENT)
    elif days_to <= 21:     codes.append(EARNINGS_CATALYST_WINDOW)

    # Multi-signal confluence
    strong = sum([
        (scores.momentum           or 0) >= 65,
        (scores.relative_strength  or 0) >= 65,
        (scores.volume_anomaly     or 0) >= 65,
        (scores.sector_leadership  or 0) >= 65,
        (scores.news_velocity      or 0) >= 65,
    ])
    if strong >= 3:
        codes.append(MULTI_SIGNAL_CONFLUENCE)

    # ── Flags ─────────────────────────────────

    # Overbought RSI
    rsi = price.get("rsi_14")
    if rsi is not None and rsi > 78:
        flags.append(FLAG_OVERBOUGHT_RSI)

    # High-volume down day (distribution signal)
    change_1d = price.get("change_1d_pct", 0)
    if vol_ratio >= 1.5 and change_1d < -1.5:
        flags.append(FLAG_HIGH_VOL_DOWN_DAY)

    # Negative news sentiment
    sentiment = news.get("sentiment_score", 0)
    if sentiment < -0.3:
        flags.append(FLAG_NEGATIVE_NEWS)

    # Low source quality (news velocity may be noise)
    source_quality = news.get("source_quality_score", 0.5)
    if source_quality < 0.35 and news.get("velocity_ratio", 1.0) > 1.5:
        flags.append(FLAG_LOW_SOURCE_QUALITY)

    # Weak sector (ticker may be falsely elevated within a lagging sector)
    # Note: sector_rs is pulled from sector_data, not record directly
    # Flag logic deferred to screener.py where sector_data is available
    # Placeholder hook:
    if record.get("_sector_rs_negative", False):
        flags.append(FLAG_WEAK_SECTOR)

    # Earnings gap risk (binary event imminent)
    if days_to <= 5:
        flags.append(FLAG_EARNINGS_GAP_RISK)

    return codes, flags
