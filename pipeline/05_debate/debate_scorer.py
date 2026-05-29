"""
debate_scorer.py
Computes debate-adjusted scores and classifies the debate outcome.

After the EDIT 2 rewire (Debate Moderator), outcome and weighting are driven by
the Moderator's `lean` + `margin`, not the analysts' self-scores. The
self-scores remain in the debate record for traceability — they no longer feed
the outcome classifier or the weighting ratio.

  Outcome  comes from Moderator.lean:
    bull_leans → BULL_PREVAILS
    bear_leans → BEAR_PREVAILS
    balanced   → BALANCED
    None (Moderator parse failure) → INCONCLUSIVE
      (INCONCLUSIVE is now a failure state only, not normal operation.)

  Weighting comes from Moderator.margin (margin-scaled):
    winner_w = 0.50 + min(|margin|, MARGIN_SCALE_CAP) / MARGIN_SCALE_CAP
               * (WINNER_MAX_WEIGHT - WINNER_MIN_WEIGHT)
             = 0.50 .. 0.80
    loser_w  = 1 - winner_w
    Winner = bull if margin > 0, bear if margin < 0; on balanced 0.50 / 0.50.
"""

from typing import Optional

from debate_types import DebateOutcome


SCORE_ADJ_MAX     = 15.0   # Absolute bound for score adjustments (unchanged)
CONF_ADJ_MAX      = 10.0   # Absolute bound for confidence adjustments (unchanged)

# Margin-scaled weighting constants (tunable):
# winner gets WINNER_MIN_WEIGHT (50%) at zero margin and scales linearly to
# WINNER_MAX_WEIGHT (80%) as the Moderator margin approaches MARGIN_SCALE_CAP.
# Loser gets the complement.
WINNER_MIN_WEIGHT = 0.50
WINNER_MAX_WEIGHT = 0.80
MARGIN_SCALE_CAP  = 10.0   # Moderator scores sum to 10; max possible |margin| is 10.


def compute_debate_scores(
    base_evidence_score:   float,
    base_confidence_score: float,
    bull_score_adj:        float,
    bull_conf_adj:         float,
    bear_score_adj:        float,
    bear_conf_adj:         float,
    moderator:             Optional[dict] = None,
) -> dict:
    """
    Compute debate-adjusted evidence and confidence scores and classify outcome.

    Outcome is driven by the Debate Moderator's `lean`. Weighting is driven by
    the Moderator's `margin` (margin-scaled — bigger margin → winner gets more
    weight, up to 80/20). Self-scores still feed the net adjustment via
    weight × score_adj — but the weight RATIO is no longer derived from the
    self-scores themselves.

    Args:
        base_evidence_score:   Layer 4 evidence_score (pre-debate baseline)
        base_confidence_score: Layer 4 confidence_score (pre-debate baseline)
        bull_score_adj:        Bull analyst's recommended evidence_score adjustment
                                  (audit-only — no longer drives outcome/weighting)
        bull_conf_adj:         Bull analyst's confidence_score adjustment (audit-only)
        bear_score_adj:        Bear analyst's recommended evidence_score adjustment
                                  (audit-only)
        bear_conf_adj:         Bear analyst's confidence_score adjustment (audit-only)
        moderator:             Moderator block from debate_dict["moderator"].
                                  None or {"lean": None} → INCONCLUSIVE outcome
                                  with 50/50 weighting (failure mode).

    Returns dict with:
        debate_evidence_score   (float)
        debate_confidence_score (float)
        net_score_adjustment    (float)
        net_conf_adjustment     (float)
        outcome                 (DebateOutcome)
    """
    # Clamp each adjustment to its allowed range
    bull_score_adj = _clamp(bull_score_adj, -SCORE_ADJ_MAX, SCORE_ADJ_MAX)
    bear_score_adj = _clamp(bear_score_adj, -SCORE_ADJ_MAX, SCORE_ADJ_MAX)
    bull_conf_adj  = _clamp(bull_conf_adj,  -CONF_ADJ_MAX,  CONF_ADJ_MAX)
    bear_conf_adj  = _clamp(bear_conf_adj,  -CONF_ADJ_MAX,  CONF_ADJ_MAX)

    # Outcome + weights from the Moderator (or INCONCLUSIVE fallback)
    outcome, bull_w, bear_w = _outcome_and_weights_from_moderator(moderator)

    net_score_adj = bull_w * bull_score_adj + bear_w * bear_score_adj
    net_conf_adj  = bull_w * bull_conf_adj  + bear_w * bear_conf_adj

    debate_evidence_score   = _clamp(base_evidence_score   + net_score_adj, -100.0, 100.0)
    debate_confidence_score = _clamp(base_confidence_score + net_conf_adj,    0.0, 100.0)

    return {
        "debate_evidence_score":   round(debate_evidence_score, 1),
        "debate_confidence_score": round(debate_confidence_score, 1),
        "net_score_adjustment":    round(net_score_adj, 1),
        "net_conf_adjustment":     round(net_conf_adj, 1),
        "outcome":                 outcome,
    }


def _outcome_and_weights_from_moderator(
    moderator: Optional[dict],
) -> tuple[DebateOutcome, float, float]:
    """
    Map a Moderator block to (outcome, bull_w, bear_w).

    Moderator block shape (from pipeline/05_debate/run.py _call_moderator):
        {"lean": "bull_leans" | "bear_leans" | "balanced" | None,
         "margin": float, ...}

    INCONCLUSIVE is now a failure state — it fires only when the Moderator
    block is missing or its lean is None (parse failure).
    """
    if not moderator or moderator.get("lean") is None:
        return DebateOutcome.INCONCLUSIVE, 0.5, 0.5

    lean = moderator.get("lean")
    margin = float(moderator.get("margin") or 0.0)

    if lean == "balanced":
        return DebateOutcome.BALANCED, 0.5, 0.5

    # Margin-scaled weighting: winner_w 0.50 .. 0.80 as |margin| grows.
    abs_m   = min(abs(margin), MARGIN_SCALE_CAP)
    winner_w = (
        WINNER_MIN_WEIGHT
        + (abs_m / MARGIN_SCALE_CAP) * (WINNER_MAX_WEIGHT - WINNER_MIN_WEIGHT)
    )
    loser_w = 1.0 - winner_w

    if lean == "bull_leans":
        return DebateOutcome.BULL_PREVAILS, winner_w, loser_w
    if lean == "bear_leans":
        return DebateOutcome.BEAR_PREVAILS, loser_w, winner_w

    # Unrecognized lean string — defensive fall-through to INCONCLUSIVE.
    return DebateOutcome.INCONCLUSIVE, 0.5, 0.5


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
