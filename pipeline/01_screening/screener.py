"""
screener.py
Main orchestrator for the initial screening layer.

Takes a list of raw signal records, classifies the market regime,
scores all six signals for each ticker, applies regime-adjusted weights,
and outputs a ranked ticker shortlist ready for Layer 2 deep research.

Entry point: run_screening()
"""

import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from signal_scorer import (
    SignalScores,
    score_momentum,
    score_relative_strength,
    score_volume_anomaly,
    score_sector_leadership,
    score_news_velocity,
    score_earnings_proximity,
)
from regime_classifier import RegimeProfile, MarketRegime, classify_regime
from reason_codes import assign_reason_codes, FLAG_WEAK_SECTOR


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

FALLBACK_THRESHOLD  = 45.0    # Used if fewer than MIN_SHORTLIST_SIZE tickers pass
MIN_SHORTLIST_SIZE  = 5       # If shortlist is smaller, lower the threshold


# ─────────────────────────────────────────────
# OUTPUT DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class ShortlistEntry:
    ticker:                  str
    composite_score:         float
    regime_adjusted_score:   float
    signal_scores:           dict
    signal_weights_applied:  dict
    regime_at_screening:     str
    reason_codes:            List[str]
    flags:                   List[str]
    priority:                int         # 1 = highest score


@dataclass
class ScreeningOutput:
    screening_id:          str
    timestamp:             str
    market_regime:         str
    regime_confidence:     float
    universe_size:         int
    candidates_evaluated:  int
    threshold_applied:     float
    shortlist:             List[ShortlistEntry]
    shortlist_count:       int
    metadata:              dict

    def to_dict(self) -> dict:
        d = asdict(self)
        d["shortlist"] = [asdict(e) for e in self.shortlist]
        return d


# ─────────────────────────────────────────────
# COMPOSITE SCORE
# ─────────────────────────────────────────────

def _compute_composite(scores: SignalScores, weights: dict) -> float:
    """
    Weighted composite score. Handles None signal scores by redistributing
    their weight proportionally across the remaining valid signals.

    This prevents a missing data field from unfairly suppressing the composite.
    """
    signal_map = {
        "momentum":           scores.momentum,
        "relative_strength":  scores.relative_strength,
        "volume_anomaly":     scores.volume_anomaly,
        "sector_leadership":  scores.sector_leadership,
        "news_velocity":      scores.news_velocity,
        "earnings_proximity": scores.earnings_proximity,
    }

    valid   = {k: v for k, v in signal_map.items() if v is not None}
    missing = {k for k, v in signal_map.items() if v is None}

    if not valid:
        return 0.0

    # Sum weights of valid signals, then normalize to 1.0
    valid_weight_total = sum(weights[k] for k in valid)
    if valid_weight_total == 0:
        return 0.0

    composite = sum(
        valid[k] * (weights[k] / valid_weight_total)
        for k in valid
    )
    return round(composite, 2)


# ─────────────────────────────────────────────
# SCREENING PASS
# ─────────────────────────────────────────────

def run_screening(
    raw_records:       List[dict],
    regime_indicators: dict,
    sector_data:       Optional[dict] = None,
) -> ScreeningOutput:
    """
    Full screening pass over the universe.

    Args:
        raw_records:
            List of dicts, each conforming to raw_signal_record.json schema.
            Invalid or incomplete records are scored with available data.

        regime_indicators:
            Market-level inputs for regime classification:
              vix               (float)  — VIX spot level
              spy_20d_return    (float)  — SPY 20-day return %
              spy_vs_ma200      (bool)   — SPY above 200-day MA
              hy_spread         (float)  — HY credit spread bps (optional)
              earnings_season   (bool)   — Peak earnings week
              fed_action_recent (bool)   — Recent Fed action/speech
              sector_dispersion (float)  — Top-minus-bottom sector spread %
              breadth_adv_decline(float) — Advance/decline ratio 14-day

        sector_data:
            Optional dict keyed by sector ETF ticker (e.g. "XLK") containing:
              sector_rs_vs_spy_20d (float) — sector outperformance vs SPY

    Returns:
        ScreeningOutput with ranked shortlist and regime metadata.
    """
    start_ms = time.monotonic()

    # ── Step 1: Classify regime ──────────────
    regime = classify_regime(regime_indicators)
    weights = regime.weights
    sector_data = sector_data or {}
    warnings: List[str] = []

    # ── Step 2: Score all tickers ────────────
    scored: List[Tuple[float, ShortlistEntry]] = []

    for record in raw_records:
        ticker = record.get("ticker", "UNKNOWN")

        price_d    = record.get("price_data", {})
        rs_d       = record.get("relative_strength", {})
        news_d     = record.get("news_data", {})
        earnings_d = record.get("earnings_data", {})
        sector_key = record.get("sector", "")
        sector_d   = sector_data.get(sector_key, {})

        # Score each signal
        scores = SignalScores(
            momentum=           score_momentum(price_d),
            relative_strength=  score_relative_strength(rs_d),
            volume_anomaly=     score_volume_anomaly(price_d),
            sector_leadership=  score_sector_leadership(rs_d, sector_d),
            news_velocity=      score_news_velocity(news_d),
            earnings_proximity= score_earnings_proximity(earnings_d),
        )

        composite = _compute_composite(scores, weights)

        # Annotate record with weak-sector flag for reason_codes
        sector_rs = sector_d.get("sector_rs_vs_spy_20d")
        record["_sector_rs_negative"] = (sector_rs is not None and sector_rs < 0)

        reason_codes, flags = assign_reason_codes(scores, record)

        # Clean up internal annotation
        record.pop("_sector_rs_negative", None)

        entry = ShortlistEntry(
            ticker=ticker,
            composite_score=composite,
            regime_adjusted_score=composite,   # V2: add regime bias adjustment
            signal_scores={
                "momentum":           _fmt(scores.momentum),
                "relative_strength":  _fmt(scores.relative_strength),
                "volume_anomaly":     _fmt(scores.volume_anomaly),
                "sector_leadership":  _fmt(scores.sector_leadership),
                "news_velocity":      _fmt(scores.news_velocity),
                "earnings_proximity": _fmt(scores.earnings_proximity),
            },
            signal_weights_applied=dict(weights),
            regime_at_screening=regime.regime.value,
            reason_codes=reason_codes,
            flags=flags,
            priority=0,     # assigned below after sorting
        )
        scored.append((composite, entry))

    # ── Step 3: Sort descending by composite ─
    scored.sort(key=lambda t: t[0], reverse=True)
    all_entries = [e for _, e in scored]

    # ── Step 4: Apply threshold ───────────────
    threshold = regime.min_score_threshold
    passing   = [e for e in all_entries if e.regime_adjusted_score >= threshold]

    fallback_used = False
    if len(passing) < MIN_SHORTLIST_SIZE:
        threshold     = FALLBACK_THRESHOLD
        fallback_used = True
        passing       = [e for e in all_entries if e.regime_adjusted_score >= threshold]
        warnings.append(
            f"Fewer than {MIN_SHORTLIST_SIZE} tickers passed regime threshold "
            f"({regime.min_score_threshold}). Fallback threshold "
            f"({FALLBACK_THRESHOLD}) applied."
        )

    # ── Step 5: Cap shortlist ─────────────────
    shortlist = passing[:regime.max_shortlist_size]

    # ── Step 6: Assign priorities ─────────────
    for i, entry in enumerate(shortlist):
        entry.priority = i + 1

    duration_ms = int((time.monotonic() - start_ms) * 1000)

    return ScreeningOutput(
        screening_id=_make_id(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        market_regime=regime.regime.value,
        regime_confidence=round(regime.confidence, 3),
        universe_size=len(raw_records),
        candidates_evaluated=len(raw_records),
        threshold_applied=threshold,
        shortlist=shortlist,
        shortlist_count=len(shortlist),
        metadata={
            "regime_description":      regime.description,
            "regime_weights":          weights,
            "fallback_threshold_used": fallback_used,
            "screening_duration_ms":   duration_ms,
            "warnings":                warnings,
        }
    )


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def _fmt(v: Optional[float]) -> Optional[float]:
    return round(v, 1) if v is not None else None


def _make_id() -> str:
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    rand = str(uuid.uuid4())[:4].upper()
    return f"SCR-{ts}-{rand}"
