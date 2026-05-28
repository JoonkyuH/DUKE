"""
entry_price_calculator.py — Stage 06 deterministic entry-price computation.

Pure function. No I/O, no LLM, no repo dependencies. Consumes three scenario
numbers plus an archetype and returns the entry-price case, band, and a price
gate the Chief Analyst uses to set its recommendation.

Replaces the four-case arithmetic that previously lived in the Chief Analyst
prompt (a844d3e / d378be2, both rolled back in 909b59a — the LLM could not
execute conditional four-case arithmetic with field-name discipline).

Reward/risk model: a fixed 2:1 favorable threshold. The 2:1 entry price is
    X = (bull + 2*bear) / 3
which is the solve-for-X of  (bull - X) / (X - bear) = 2.  Weighting the bear
scenario twice pulls the entry toward the downside floor so that at price X the
modeled upside is twice the modeled downside.

Four cases tile the number line by where current (C) sits on {bear, X, bull}:
    C <= bear        -> BELOW_BEAR   (trades below the downside case)
    bear < C <= X    -> IN_BAND      (already >= 2:1)
    X < C < bull     -> ABOVE_BAND   (too rich for a clean 2:1; wait for X)
    C >= bull        -> INVERTED     (no modeled upside; no entry number)
Degenerate inputs (missing, non-positive, bull <= bear) -> DEGENERATE.

The band (case / entry / range / X) is archetype-INDEPENDENT. Only
`price_gate_passed` depends on archetype: it is whether the reward/risk at the
current price clears that archetype's minimum. If the Chief reclassifies the
archetype downstream it re-checks the gate with a single comparison of
`ratio_at_current` against ARCHETYPE_MIN_RR — it never re-derives the band.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

TARGET_RR = 2.0  # fixed 2:1 reward/risk that locates the entry band

# Minimum acceptable reward/risk AT THE CURRENT PRICE, per archetype.
# This is the price-discipline lever: how far past the 2:1 band the Chief may
# enter. deep_value pays nothing up; compounders may pay up on conviction.
ARCHETYPE_MIN_RR = {
    "deep_value": 2.0,            # price IS the thesis; no concession
    "quality_compounder": 1.5,    # a modest premium to the band is acceptable
    "long_term_compounder": 1.2,  # may pay up on an exceptional name
}

WATCH_TOLERANCE = 0.03  # +/-3% band around the target entry in ABOVE_BAND


@dataclass
class EntryPriceResult:
    case_label: str                      # IN_BAND | ABOVE_BAND | BELOW_BEAR | INVERTED | DEGENERATE
    entry_price: Optional[float]         # None for INVERTED / DEGENERATE
    entry_range: Optional[dict]          # {"low": float, "high": float} or None
    target_2to1_price: Optional[float]   # X = (bull + 2*bear)/3, for transparency
    ratio_at_current: Optional[float]    # (bull-current)/(current-bear); None if undefined
    archetype: str
    archetype_min_rr: Optional[float]    # None if archetype unrecognized
    price_gate_passed: Optional[bool]    # ratio_at_current >= archetype_min_rr
    rationale: str

    def to_dict(self) -> dict:
        return asdict(self)


def compute_entry_price(
    bull_scenario_price: float,
    bear_scenario_price: float,
    current_price: float,
    archetype: str,
) -> EntryPriceResult:
    B = bull_scenario_price
    b = bear_scenario_price
    C = current_price

    min_rr = ARCHETYPE_MIN_RR.get(archetype)

    # --- input guards -----------------------------------------------------
    if any(v is None for v in (B, b, C)):
        return EntryPriceResult(
            "DEGENERATE", None, None, None, None, archetype, min_rr, None,
            "Missing one or more inputs (bull/bear/current); cannot compute entry.",
        )
    if B <= 0 or b <= 0 or C <= 0:
        return EntryPriceResult(
            "DEGENERATE", None, None, None, None, archetype, min_rr, None,
            "Non-positive price input; cannot compute entry.",
        )
    if B <= b:
        return EntryPriceResult(
            "DEGENERATE", None, None, None, None, archetype, min_rr, None,
            f"Scenarios crossed/degenerate: bull {B:.2f} <= bear {b:.2f}.",
        )

    X = (B + 2.0 * b) / 3.0  # 2:1 entry price

    # ratio at current is only defined for bear < current < bull
    ratio = (B - C) / (C - b) if b < C < B else None

    # --- four-case partition by where C sits on {b, X, B} -----------------
    if C >= B:
        # INVERTED: current at/above the bull scenario; no modeled upside.
        return EntryPriceResult(
            "INVERTED", None, None, round(X, 2), ratio, archetype, min_rr, False,
            f"Current {C:.2f} is at/above bull scenario {B:.2f}: no modeled "
            f"upside. No entry number produced under inversion. Watch.",
        )

    if C <= b:
        # BELOW_BEAR: current at/below the bear floor — exceptionally cheap OR
        # the scenario inputs are stale/wrong. entry now; band high = 2:1 price.
        return EntryPriceResult(
            "BELOW_BEAR", round(C, 2),
            {"low": round(C, 2), "high": round(X, 2)},
            round(X, 2), ratio, archetype, min_rr, True,
            f"Current {C:.2f} is at/below bear scenario {b:.2f}: trades below the "
            f"downside case. Entry at current; band runs to the 2:1 price {X:.2f}. "
            f"Scrutinize scenario inputs — a price below the bear floor can mean a "
            f"screaming buy or stale/incorrect scenario prices.",
        )

    # here bear < C < bull, so ratio is defined
    gate = (ratio >= min_rr) if min_rr is not None else None

    if C <= X:
        # IN_BAND: ratio >= 2:1 already; buy now up to the 2:1 price.
        return EntryPriceResult(
            "IN_BAND", round(C, 2),
            {"low": round(C, 2), "high": round(X, 2)},
            round(X, 2), ratio, archetype, min_rr, gate,
            f"Current {C:.2f} sits inside the 2:1 band (entry up to {X:.2f}); "
            f"reward/risk {ratio:.2f}:1 at current.",
        )

    # ABOVE_BAND: X < C < bull; ratio < 2:1; too rich for a clean 2:1.
    # entry_price is the disciplined 2:1 target. Whether the Chief may still
    # enter at current is governed by price_gate_passed (archetype-dependent).
    return EntryPriceResult(
        "ABOVE_BAND", round(X, 2),
        {"low":  round(X * (1 - WATCH_TOLERANCE), 2),
         "high": round(X * (1 + WATCH_TOLERANCE), 2)},
        round(X, 2), ratio, archetype, min_rr, gate,
        f"Current {C:.2f} is above the 2:1 entry price {X:.2f} "
        f"(reward/risk only {ratio:.2f}:1). Disciplined target entry {X:.2f} "
        f"(+/-{int(WATCH_TOLERANCE * 100)}%).",
    )
