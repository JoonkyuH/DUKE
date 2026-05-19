"""
screener.py
Main orchestrator for the fundamental screening layer (Stage 01).

Takes a list of raw signal records, classifies the market regime,
computes fundamental quality-and-value scores for each ticker, applies
regime-adjusted weights, and outputs a ranked shortlist ready for Stage 02.

Entry point: run_screening()

Each record must include:
  fundamental_data  — common.edgar_client.fetch_financials() output
  price_data        — from data_fetcher (for current_price)
  extended_data     — from data_fetcher (for market_cap, 52w high/low)
  earnings_data     — from data_fetcher (for binary event risk)
"""

import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

from signal_scorer import (
    SignalScores,
    compute_fundamental_metrics,
    score_business_quality,
    score_valuation_vs_growth,
    score_valuation_vs_growth_compounder,
    score_valuation_vs_growth_quality_compounder,
    score_historical_discount,
    score_earnings_quality,
    score_entry_vs_fundamentals,
    score_binary_event_risk,
    build_mispricing_hypothesis,
)
from regime_classifier import RegimeProfile, MarketRegime, classify_regime
from reason_codes import assign_reason_codes


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

FALLBACK_THRESHOLD  = 45.0    # Used if fewer than MIN_SHORTLIST_SIZE tickers pass
MIN_SHORTLIST_SIZE  = 5       # If shortlist is smaller, lower the threshold

# Archetype weight sets. Each ticker is scored under both; the higher wins.
COMPOUNDER_WEIGHTS: dict = {
    "business_quality":      0.30,
    "valuation_vs_growth":   0.25,
    "earnings_quality":      0.25,
    "entry_vs_fundamentals": 0.12,
    "historical_discount":   0.00,   # irrelevant for long-term compounders
    "binary_event_risk":     0.08,
}

DEEP_VALUE_WEIGHTS: dict = {
    "business_quality":      0.25,
    "historical_discount":   0.25,
    "earnings_quality":      0.20,
    "valuation_vs_growth":   0.15,
    "entry_vs_fundamentals": 0.12,
    "binary_event_risk":     0.03,
}

QUALITY_COMPOUNDER_WEIGHTS: dict = {
    "business_quality":      0.35,   # quality is the whole thesis
    "earnings_quality":      0.25,   # is the moat showing up in earnings?
    "valuation_vs_growth":   0.20,   # is the multiple reasonable for a mature compounder?
    "entry_vs_fundamentals": 0.12,
    "historical_discount":   0.05,   # light — quality compounders rarely get deep discounts
    "binary_event_risk":     0.03,
}

_ARCHETYPE_TIE_BAND = 1.0    # top two scores within this band → "either"


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
    screening_archetype:     str         # "long_term_compounder" | "deep_value" | "either"
    reason_codes:            List[str]
    flags:                   List[str]
    mispricing_hypothesis:   str
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
    """
    signal_map = {
        "business_quality":      scores.business_quality,
        "valuation_vs_growth":   scores.valuation_vs_growth,
        "historical_discount":   scores.historical_discount,
        "earnings_quality":      scores.earnings_quality,
        "entry_vs_fundamentals": scores.entry_vs_fundamentals,
        "binary_event_risk":     scores.binary_event_risk,
    }

    valid = {k: v for k, v in signal_map.items() if v is not None}
    if not valid:
        return 0.0

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
            List of dicts conforming to the Stage 01 raw record schema.
            Each must include:
              fundamental_data  — common.edgar_client output
              price_data        — yfinance price metrics
              extended_data     — yfinance extended metrics (market_cap, 52w range)
              earnings_data     — earnings date data

        regime_indicators:
            Market-level inputs for classify_regime():
              vix, spy_20d_return, spy_vs_ma200, hy_spread,
              earnings_season, fed_action_recent,
              sector_dispersion, breadth_adv_decline

        sector_data:
            Not used by the fundamental screener (retained for API compatibility
            with run_screening.py which passes it through).

    Returns:
        ScreeningOutput with ranked shortlist and regime metadata.
    """
    start_ms = time.monotonic()

    # ── Step 1: Classify regime ──────────────
    regime   = classify_regime(regime_indicators)
    warnings: List[str] = []

    # ── Step 2: Score all tickers ────────────
    scored: List[Tuple[float, ShortlistEntry]] = []

    for record in raw_records:
        ticker     = record.get("ticker", "UNKNOWN")
        fund_d     = record.get("fundamental_data", {})
        price_d    = record.get("price_data", {})
        ext_d      = record.get("extended_data", {})
        earnings_d = record.get("earnings_data", {})

        market_d = {
            "market_cap":    ext_d.get("market_cap"),
            "current_price": price_d.get("current_price"),
            "week_52_high":  ext_d.get("week_52_high"),
            "week_52_low":   ext_d.get("week_52_low"),
        }

        metrics = compute_fundamental_metrics(fund_d, market_d) if fund_d else {}

        # ── Signals shared across all three archetypes ─────────────
        bq = score_business_quality(metrics)
        hd = score_historical_discount(metrics)
        eq = score_earnings_quality(metrics)
        ef = score_entry_vs_fundamentals(metrics)
        br = score_binary_event_risk(earnings_d)

        # ── Archetype-specific VG signals ──────────────────────────
        vg_dv    = score_valuation_vs_growth(metrics)
        vg_comp  = score_valuation_vs_growth_compounder(metrics)
        vg_qcomp = score_valuation_vs_growth_quality_compounder(metrics)

        scores_dv = SignalScores(
            business_quality=bq, valuation_vs_growth=vg_dv,
            historical_discount=hd, earnings_quality=eq,
            entry_vs_fundamentals=ef, binary_event_risk=br,
        )
        scores_comp = SignalScores(
            business_quality=bq, valuation_vs_growth=vg_comp,
            historical_discount=hd, earnings_quality=eq,
            entry_vs_fundamentals=ef, binary_event_risk=br,
        )
        scores_qcomp = SignalScores(
            business_quality=bq, valuation_vs_growth=vg_qcomp,
            historical_discount=hd, earnings_quality=eq,
            entry_vs_fundamentals=ef, binary_event_risk=br,
        )

        comp_dv    = _compute_composite(scores_dv,    DEEP_VALUE_WEIGHTS)
        comp_comp  = _compute_composite(scores_comp,  COMPOUNDER_WEIGHTS)
        comp_qcomp = _compute_composite(scores_qcomp, QUALITY_COMPOUNDER_WEIGHTS)

        # ── Select winning archetype ───────────────────────────────
        # Sort all three descending; if top two are within the tie band → "either".
        _candidates = sorted([
            (comp_comp,  "long_term_compounder", scores_comp,  COMPOUNDER_WEIGHTS),
            (comp_qcomp, "quality_compounder",   scores_qcomp, QUALITY_COMPOUNDER_WEIGHTS),
            (comp_dv,    "deep_value",           scores_dv,    DEEP_VALUE_WEIGHTS),
        ], key=lambda x: x[0], reverse=True)

        top_score, top_arch, top_scores, top_weights = _candidates[0]
        second_score = _candidates[1][0]

        archetype       = "either" if (top_score - second_score) <= _ARCHETYPE_TIE_BAND else top_arch
        scores          = top_scores
        composite       = top_score
        winning_weights = top_weights

        # Stash metrics on record for reason_codes.py access
        record["fundamental_metrics"] = metrics

        reason_codes, flags = assign_reason_codes(scores, record)
        hypothesis = build_mispricing_hypothesis(
            ticker, scores, metrics, earnings_d, composite=composite
        )

        # Clean up internal stash
        record.pop("fundamental_metrics", None)

        entry = ShortlistEntry(
            ticker=ticker,
            composite_score=composite,
            regime_adjusted_score=composite,
            signal_scores={
                "business_quality":      _fmt(scores.business_quality),
                "valuation_vs_growth":   _fmt(scores.valuation_vs_growth),
                "historical_discount":   _fmt(scores.historical_discount),
                "earnings_quality":      _fmt(scores.earnings_quality),
                "entry_vs_fundamentals": _fmt(scores.entry_vs_fundamentals),
                "binary_event_risk":     _fmt(scores.binary_event_risk),
            },
            signal_weights_applied=dict(winning_weights),
            regime_at_screening=regime.regime.value,
            screening_archetype=archetype,
            reason_codes=reason_codes,
            flags=flags,
            mispricing_hypothesis=hypothesis,
            priority=0,
        )
        scored.append((composite, entry))

    # ── Step 3: Sort descending by composite ─
    scored.sort(key=lambda t: t[0], reverse=True)
    all_entries = [e for _, e in scored]

    # ── Step 4: Apply threshold ───────────────
    threshold    = regime.min_score_threshold
    passing      = [e for e in all_entries if e.regime_adjusted_score >= threshold]
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
            "regime_description":          regime.description,
            "compounder_weights":          COMPOUNDER_WEIGHTS,
            "quality_compounder_weights":  QUALITY_COMPOUNDER_WEIGHTS,
            "deep_value_weights":          DEEP_VALUE_WEIGHTS,
            "fallback_threshold_used":     fallback_used,
            "screening_duration_ms":       duration_ms,
            "warnings":                    warnings,
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
