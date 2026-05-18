"""
regime_classifier.py
Classifies the current market regime from observable indicators and returns
a RegimeProfile containing signal weights and screening thresholds.

The regime is the single biggest modifier of screening behavior:
  - In risk-on momentum: cast a wide net, lower threshold, overweight momentum/RS
  - In risk-off defensive: raise the bar significantly, shrink the shortlist
  - In liquidity contraction: only the highest-conviction setups pass
  - In earnings volatility: weight catalyst proximity heavily

Regime classification is always explicit and logged. It is never inferred
silently from signal behavior.
"""

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict


# ─────────────────────────────────────────────
# REGIME DEFINITIONS
# ─────────────────────────────────────────────

class MarketRegime(str, Enum):
    RISK_ON_MOMENTUM      = "risk_on_momentum"
    RISK_OFF_DEFENSIVE    = "risk_off_defensive"
    LIQUIDITY_EXPANSION   = "liquidity_expansion"
    LIQUIDITY_CONTRACTION = "liquidity_contraction"
    EARNINGS_VOLATILITY   = "earnings_volatility"
    MACRO_UNCERTAINTY     = "macro_uncertainty"


@dataclass
class RegimeProfile:
    regime:              MarketRegime
    confidence:          float          # 0–1, set at classification time
    weights:             Dict[str, float]
    min_score_threshold: float          # minimum composite score to enter shortlist
    max_shortlist_size:  int            # cap on shortlist length
    description:         str            # human-readable rationale


# ─────────────────────────────────────────────
# BASE REGIME PROFILES
# These are templates; confidence is assigned at runtime.
# ─────────────────────────────────────────────

_BASE_PROFILES: Dict[MarketRegime, RegimeProfile] = {

    MarketRegime.RISK_ON_MOMENTUM: RegimeProfile(
        regime=MarketRegime.RISK_ON_MOMENTUM,
        confidence=0.0,
        weights={
            "momentum":           0.25,
            "relative_strength":  0.25,
            "volume_anomaly":     0.15,
            "sector_leadership":  0.15,
            "news_velocity":      0.10,
            "earnings_proximity": 0.10,
        },
        min_score_threshold=52.0,
        max_shortlist_size=20,
        description=(
            "Growth and momentum rewarded. Liquidity is supportive. "
            "Cast a wide net — quality setups are plentiful."
        )
    ),

    MarketRegime.RISK_OFF_DEFENSIVE: RegimeProfile(
        regime=MarketRegime.RISK_OFF_DEFENSIVE,
        confidence=0.0,
        weights={
            "momentum":           0.10,
            "relative_strength":  0.20,
            "volume_anomaly":     0.20,
            "sector_leadership":  0.25,
            "news_velocity":      0.15,
            "earnings_proximity": 0.10,
        },
        min_score_threshold=65.0,   # Significantly raised bar
        max_shortlist_size=10,
        description=(
            "Defensive posture. Elevated volatility and weak breadth. "
            "Only the highest-conviction setups pass. Favor relative leaders."
        )
    ),

    MarketRegime.LIQUIDITY_EXPANSION: RegimeProfile(
        regime=MarketRegime.LIQUIDITY_EXPANSION,
        confidence=0.0,
        weights={
            "momentum":           0.22,
            "relative_strength":  0.22,
            "volume_anomaly":     0.18,
            "sector_leadership":  0.18,
            "news_velocity":      0.10,
            "earnings_proximity": 0.10,
        },
        min_score_threshold=50.0,   # Lower threshold — rising tide
        max_shortlist_size=20,
        description=(
            "Easing financial conditions. Speculative appetite rising. "
            "Volume and sector rotation are strong signals. Cast wider net."
        )
    ),

    MarketRegime.LIQUIDITY_CONTRACTION: RegimeProfile(
        regime=MarketRegime.LIQUIDITY_CONTRACTION,
        confidence=0.0,
        weights={
            "momentum":           0.15,
            "relative_strength":  0.25,
            "volume_anomaly":     0.20,
            "sector_leadership":  0.20,
            "news_velocity":      0.10,
            "earnings_proximity": 0.10,
        },
        min_score_threshold=68.0,   # Very high bar — multiple compression environment
        max_shortlist_size=8,
        description=(
            "Tightening financial conditions. Multiple compression in effect. "
            "Only clear leaders with strong fundamentals and RS pass."
        )
    ),

    MarketRegime.EARNINGS_VOLATILITY: RegimeProfile(
        regime=MarketRegime.EARNINGS_VOLATILITY,
        confidence=0.0,
        weights={
            "momentum":           0.15,
            "relative_strength":  0.15,
            "volume_anomaly":     0.20,
            "sector_leadership":  0.10,
            "news_velocity":      0.15,
            "earnings_proximity": 0.25,  # Catalyst timing dominates
        },
        min_score_threshold=55.0,
        max_shortlist_size=15,
        description=(
            "Peak earnings season with elevated single-stock volatility. "
            "Catalyst timing is the primary filter. Volume and news confirm."
        )
    ),

    MarketRegime.MACRO_UNCERTAINTY: RegimeProfile(
        regime=MarketRegime.MACRO_UNCERTAINTY,
        confidence=0.0,
        weights={
            "momentum":           0.15,
            "relative_strength":  0.20,
            "volume_anomaly":     0.20,
            "sector_leadership":  0.20,
            "news_velocity":      0.15,
            "earnings_proximity": 0.10,
        },
        min_score_threshold=65.0,
        max_shortlist_size=10,
        description=(
            "High policy sensitivity and elevated macro correlation. "
            "Only clear leaders with defensible positions and strong RS pass."
        )
    ),
}


def _clone(regime: MarketRegime) -> RegimeProfile:
    """Return a deep copy of a base profile (safe for runtime mutation)."""
    p = _BASE_PROFILES[regime]
    return RegimeProfile(
        regime=p.regime,
        confidence=p.confidence,
        weights=dict(p.weights),
        min_score_threshold=p.min_score_threshold,
        max_shortlist_size=p.max_shortlist_size,
        description=p.description,
    )


# ─────────────────────────────────────────────
# CLASSIFICATION LOGIC
# ─────────────────────────────────────────────

def classify_regime(regime_indicators: dict) -> RegimeProfile:
    """
    Classify the current market regime from observable indicators.

    Expected keys in regime_indicators:
      vix              (float)  — VIX spot level
      spy_20d_return   (float)  — SPY 20-day price return %
      spy_vs_ma200     (bool)   — True if SPY is above its 200-day MA
      hy_spread        (float)  — HY credit spread in bps (optional, default 350)
      earnings_season  (bool)   — True if >30 S&P 500 companies report this week
      fed_action_recent(bool)   — True if Fed acted or spoke in the last 14 days
      sector_dispersion(float)  — Top-minus-bottom decile sector return spread %
      breadth_adv_decline(float)— Advance/decline ratio (14-day rolling)

    Classification rules are ordered by priority. The first match wins.
    All rules are explicit — no implicit defaults based on signal behavior.

    Returns a RegimeProfile with confidence set.
    """
    def _get(key, default):
        v = regime_indicators.get(key)
        return default if v is None else v

    vix         = _get("vix", 20.0)
    spy_20d     = _get("spy_20d_return", 0.0)
    spy_ma200   = _get("spy_vs_ma200", True)
    hy_spread   = _get("hy_spread", 350)
    ear_season  = _get("earnings_season", False)
    fed_action  = _get("fed_action_recent", False)
    dispersion  = _get("sector_dispersion", 10.0)
    breadth     = _get("breadth_adv_decline", 1.0)

    # ── Rule 1: Earnings Volatility
    # Active earnings season + elevated VIX = catalyst timing dominates
    if ear_season and vix > 18:
        p = _clone(MarketRegime.EARNINGS_VOLATILITY)
        p.confidence = 0.80 if vix > 22 else 0.70
        return p

    # ── Rule 2: Macro Uncertainty
    # Very elevated VIX, OR elevated VIX + Fed action + high dispersion
    if vix > 30:
        p = _clone(MarketRegime.MACRO_UNCERTAINTY)
        p.confidence = _macro_confidence(vix, fed_action)
        return p
    if vix > 22 and fed_action and dispersion > 20:
        p = _clone(MarketRegime.MACRO_UNCERTAINTY)
        p.confidence = _macro_confidence(vix, fed_action)
        return p

    # ── Rule 3: Risk-Off Defensive
    # Elevated VIX + poor breadth + SPY below 200-day MA
    if vix > 22 and breadth < 0.90 and not spy_ma200:
        p = _clone(MarketRegime.RISK_OFF_DEFENSIVE)
        p.confidence = 0.78
        return p

    # ── Rule 4: Liquidity Contraction
    # Tightening credit conditions visible in HY spreads
    if hy_spread > 520:
        p = _clone(MarketRegime.LIQUIDITY_CONTRACTION)
        p.confidence = 0.75
        return p
    if hy_spread > 420 and spy_20d < -4:
        p = _clone(MarketRegime.LIQUIDITY_CONTRACTION)
        p.confidence = 0.68
        return p

    # ── Rule 5: Liquidity Expansion
    # Low VIX + strong breadth + SPY trending up
    if vix < 15 and breadth > 1.35 and spy_20d > 5:
        p = _clone(MarketRegime.LIQUIDITY_EXPANSION)
        p.confidence = 0.74
        return p

    # ── Rule 6: Risk-On Momentum (default)
    p = _clone(MarketRegime.RISK_ON_MOMENTUM)
    # Confidence increases with stronger confirming signals
    conf = 0.58
    if spy_20d > 5 and breadth > 1.15 and vix < 18 and spy_ma200:
        conf = 0.82
    elif spy_20d > 2 and breadth > 1.05 and vix < 20:
        conf = 0.68
    p.confidence = conf
    return p


def _macro_confidence(vix: float, fed_action: bool) -> float:
    base = 0.62
    if vix > 38:     base += 0.20
    elif vix > 30:   base += 0.12
    elif vix > 24:   base += 0.06
    if fed_action:   base += 0.08
    return min(0.95, base)


# ─────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────

def get_all_regimes() -> Dict[str, dict]:
    """Return all regime profiles as plain dicts (for documentation/logging)."""
    return {
        r.value: {
            "weights":             _BASE_PROFILES[r].weights,
            "min_score_threshold": _BASE_PROFILES[r].min_score_threshold,
            "max_shortlist_size":  _BASE_PROFILES[r].max_shortlist_size,
            "description":         _BASE_PROFILES[r].description,
        }
        for r in MarketRegime
    }
