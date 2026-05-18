"""
debate_scorer.py
Computes debate-adjusted scores and classifies the debate outcome.

Each analyst submits a score_adjustment [-15, +15] and a confidence_adjustment
[-10, +10] representing how much they believe the Layer 4 baseline should shift.

Net adjustment is the average of the two, so:
  - Bull pushes positive, bear pushes negative → they partially cancel
  - If both agree the evidence is strong (or weak), the net reflects that consensus
  - The further apart they are with a small net, the more inconclusive the debate

Outcome rules (evaluated in order):
  BULL_PREVAILS:  net_score_adj > +8
  BEAR_PREVAILS:  net_score_adj < -8
  INCONCLUSIVE:   |bull_adj - bear_adj| > 15 AND |net_score_adj| <= 8
                  (large disagreement, unresolved by averaging)
  BALANCED:       everything else
"""

from debate_types import DebateOutcome


SCORE_ADJ_MAX     = 15.0   # Absolute bound for score adjustments
CONF_ADJ_MAX      = 10.0   # Absolute bound for confidence adjustments
PREVAIL_THRESHOLD =  8.0   # Net movement above this = one side prevailed
INCONCLUSIVE_GAP  = 15.0   # Analyst disagreement gap above which debate is inconclusive


def compute_debate_scores(
    base_evidence_score:   float,
    base_confidence_score: float,
    bull_score_adj:        float,
    bull_conf_adj:         float,
    bear_score_adj:        float,
    bear_conf_adj:         float,
) -> dict:
    """
    Compute debate-adjusted evidence and confidence scores and classify outcome.

    Args:
        base_evidence_score:   Layer 4 evidence_score (pre-debate baseline)
        base_confidence_score: Layer 4 confidence_score (pre-debate baseline)
        bull_score_adj:        Bull analyst's recommended evidence_score adjustment
        bull_conf_adj:         Bull analyst's recommended confidence_score adjustment
        bear_score_adj:        Bear analyst's recommended evidence_score adjustment
        bear_conf_adj:         Bear analyst's recommended confidence_score adjustment

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

    net_score_adj = (bull_score_adj + bear_score_adj) / 2.0
    net_conf_adj  = (bull_conf_adj  + bear_conf_adj)  / 2.0

    debate_evidence_score   = _clamp(base_evidence_score   + net_score_adj, -100.0, 100.0)
    debate_confidence_score = _clamp(base_confidence_score + net_conf_adj,    0.0, 100.0)

    outcome = _determine_outcome(net_score_adj, bull_score_adj, bear_score_adj)

    return {
        "debate_evidence_score":   round(debate_evidence_score, 1),
        "debate_confidence_score": round(debate_confidence_score, 1),
        "net_score_adjustment":    round(net_score_adj, 1),
        "net_conf_adjustment":     round(net_conf_adj, 1),
        "outcome":                 outcome,
    }


def _determine_outcome(
    net_adj:  float,
    bull_adj: float,
    bear_adj: float,
) -> DebateOutcome:
    if net_adj > PREVAIL_THRESHOLD:
        return DebateOutcome.BULL_PREVAILS
    if net_adj < -PREVAIL_THRESHOLD:
        return DebateOutcome.BEAR_PREVAILS
    if abs(bull_adj - bear_adj) > INCONCLUSIVE_GAP:
        return DebateOutcome.INCONCLUSIVE
    return DebateOutcome.BALANCED


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
