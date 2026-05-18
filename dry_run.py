#!/usr/bin/env python3
"""
dry_run.py
DUKE full pipeline dry run — stages 04 through 07 — using the NVDA sample packet.

Usage:
    python3 dry_run.py

Stages covered:
  04 Scoring   — score_packet() from the pre-built evidence packet
  05 Debate    — record_debate() with synthetic bull/bear analyst positions
  06 Synthesis — synthesize() with a synthetic risk officer assessment
  07 Output    — format_recommendation() with a synthetic chief analyst output

No real data sources are connected. All analyst outputs are pre-written fixtures
that simulate realistic AI analyst responses for NVDA at June 2024.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent

# ── Investor profile — used to display position sizing as a percentage range ──
_profile_path = REPO / "config" / "investor_profile.json"
try:
    with open(_profile_path) as _f:
        _MAX_POS_PCT = float(json.load(_f).get("max_position_size_pct", 10.0))
except (OSError, ValueError, KeyError):
    _MAX_POS_PCT = 10.0

_SIZING_FACTORS = {
    "full":    1.00,
    "half":    0.50,
    "quarter": 0.25,
    "pilot":   0.10,
    "none":    0.00,
}


def _format_sizing(sizing_value: str) -> str:
    """Convert PositionSizing enum value to a lo–hi% range string."""
    factor = _SIZING_FACTORS.get(sizing_value.lower(), 0.0)
    if factor == 0.0:
        return "none"
    hi = round(_MAX_POS_PCT * factor, 1)
    lo = round(hi * 0.6, 1)
    return f"{lo:.1f}–{hi:.1f}% of portfolio"

# Add all stage directories to sys.path so relative imports inside each module resolve
for _stage in ["04_scoring", "05_debate", "06_synthesis", "07_output"]:
    _p = str(REPO / "pipeline" / _stage)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scorer import score_packet          # noqa: E402
from debate_recorder import record_debate  # noqa: E402
from synthesizer import synthesize       # noqa: E402
from formatter import format_recommendation  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# SYNTHETIC ANALYST FIXTURES
# These simulate what the AI analyst roles would return after reading their briefs.
# ─────────────────────────────────────────────────────────────────────────────

BULL_POSITION = {
    "summary": (
        "NVDA is the defining infrastructure company of the current AI investment cycle. "
        "The evidence is unambiguous: 262% YoY revenue growth, gross margins expanding to "
        "78.4%, and a CEO who explicitly says demand exceeds supply. The CUDA software "
        "ecosystem with 3.5M+ developers represents 2-3 years of structural switching costs "
        "for any credible alternative. Hyperscaler capex guidance of $200B+ for 2025 provides "
        "multi-quarter demand visibility. This is a generational compounder at the center of "
        "structural spending that will not slow in the next 2-3 years."
    ),
    "key_arguments": [
        "Revenue grew 262% YoY with sequential acceleration for three consecutive quarters — structural demand, not a one-quarter spike.",
        "Gross margin expansion to 78.4% from 64.6% demonstrates pricing power and operating leverage at scale.",
        "CUDA ecosystem with 3.5M+ developers creates 2-3 year switching costs even if competing silicon reaches performance parity.",
        "Hyperscaler capex of $200B+ for calendar 2025 (Microsoft, Google, Amazon) provides direct, named multi-quarter demand visibility.",
        "Supply-constrained language from both CEO and CFO is the strongest demand confirmation signal in the evidence packet.",
    ],
    "evidence_cited": ["EV-001", "EV-002", "EV-003", "EV-004", "EV-005", "EV-008", "EV-009"],
    "contested_items": ["EV-014"],
    "raised_risks": [],
    "learning_hooks": [
        "Hyperscaler GPU capex collectively exceeds $200B for calendar 2025 (verify at next earnings cycle Q3 2024).",
        "Gross margins remain above 75% through at least 2 consecutive quarters post-Blackwell transition.",
        "NVDA maintains greater than 80% data center GPU market share through Q4 calendar 2025.",
    ],
    "score_adjustment": 10.0,
    "confidence_adjustment": 4.0,
}

BEAR_POSITION = {
    "summary": (
        "NVDA has exceptional results, but the valuation at 35x forward earnings prices in "
        "perfection with no margin for error. The 46% revenue concentration in three customers "
        "is a structural risk the bull dismisses without evidence. A single hyperscaler order "
        "reduction — already reported by The Information for one unnamed customer — would cause "
        "a material quarterly miss. Export restrictions represent a permanent headwind already "
        "costing $5-7B and may expand to Blackwell. Watch at a lower entry point."
    ),
    "key_arguments": [
        "35x forward P/E vs. 22x sector average requires 40%+ revenue growth sustained for 3+ years — historically rare at this scale.",
        "46% customer concentration in three hyperscalers makes revenue structurally fragile to any single customer's capex cycle.",
        "AMD MI300X is gaining traction in inference workloads; the competitive moat is narrowing faster than the CUDA narrative implies.",
        "Export restriction expansion to Blackwell is a tail risk with binary outcome — and TIC-002 is already in monitoring status.",
    ],
    "evidence_cited": ["EV-012", "EV-013", "EV-014"],
    "contested_items": ["EV-001"],
    "raised_risks": [
        "Hyperscaler custom silicon acceleration (Google TPU, Amazon Trainium) could reduce NVDA dependency over a 3-5 year horizon beyond current TICs."
    ],
    "learning_hooks": [
        "AMD MI300X captures more than 5% of new data center AI inference deployments within 4 quarters.",
        "At least one named hyperscaler reduces NVDA GPU forward purchase commitments by more than 10% within 2 quarters.",
        "BIS announces export control extension to Blackwell architecture within 12 months.",
    ],
    "valuation_challenge": (
        "At 35x forward earnings, NVDA is priced for sustained hypergrowth. The evidence "
        "score of +38 reflects a strong but not exceptional directional balance — insufficient "
        "to justify this premium above sector norms. A 25x forward P/E (still premium) implies "
        "a 28% discount from current levels. This investment thesis offers no margin of safety."
    ),
    "score_adjustment": -3.0,
    "confidence_adjustment": -2.0,
}

RISK_ASSESSMENT = {
    "overall_risk_assessment": "needs_attention",
    "ready_for_chief_analyst": True,
    "blocking_issues": [],
    "tic_assessment": [
        {
            "condition_id": "TIC-001",
            "quality": "adequate",
            "severity": "fatal",
            "notes": "Clear trigger at 20% YoY deceleration. Currently not triggered. Revenue at 262% provides ample buffer.",
        },
        {
            "condition_id": "TIC-002",
            "quality": "adequate",
            "severity": "fatal",
            "notes": "MONITORING STATUS. BIS review is active; Blackwell restriction would trigger this immediately. Highest-priority pre-entry risk.",
        },
        {
            "condition_id": "TIC-003",
            "quality": "adequate",
            "severity": "major",
            "notes": "Margin threshold of 70% well-defined. Currently at 78.4% — 840bps of buffer.",
        },
    ],
    "tic_coverage_gaps": [],
    "risk_factor_assessment": [
        {
            "risk_id": "RSK-001",
            "probability_calibrated": True,
            "notes": "Customer concentration real but partially offset by multi-year AI capex commitments. Not a blocking issue.",
        },
        {
            "risk_id": "RSK-002",
            "probability_calibrated": True,
            "notes": "FLAGGED NEEDS_ATTENTION. BIS review outcome is material and timeline is uncertain.",
        },
        {
            "risk_id": "RSK-003",
            "probability_calibrated": True,
            "notes": "AMD threat real but long-timeline. Monitor MI300X adoption data quarterly.",
        },
    ],
    "missing_risk_factors": [],
    "binary_event_assessment": [
        {
            "catalyst_id": "CAT-001",
            "sizing_note": "Do not build full position prior to BIS resolution. Half-position maximum.",
            "resolution_path": "Monitor Federal Register for BIS rulemaking. Estimated resolution within 45 days.",
        }
    ],
    "monitoring_plan": {
        "frequency": "monthly",
        "leading_indicators": [
            "Hyperscaler quarterly earnings — GPU capacity commentary and forward order signals",
            "Federal Register BIS rulemaking notices for advanced computing chips",
            "AMD MI300X shipment volume disclosures",
        ],
        "exit_clarity": (
            "Exit triggers: TIC-002 (Blackwell export restriction confirmed) or TIC-001 "
            "(two consecutive quarters below 20% YoY revenue growth)."
        ),
    },
}

CHIEF_ANALYST_OUTPUT = {
    "analyst_role": "chief_analyst",
    "recommendation": "watch",
    "investment_archetype_confirmed": "long_term_compounder",
    "final_evidence_score": 41.7,
    "final_confidence_score": 95.2,
    "executive_summary": (
        "NVDA is a structurally dominant compounder in the AI infrastructure build-out "
        "with exceptional evidence quality and margin dynamics — but the debate was balanced, "
        "not bull-prevailing, and the most important pre-entry condition (TIC-002, Blackwell "
        "export restriction risk) remains unresolved in monitoring status. Do not enter now. "
        "Watch for BIS regulatory clarity or a valuation reset that creates meaningful margin "
        "of safety; either would move this to a moderate_conviction_enter."
    ),
    "bull_case_assessment": (
        "The 262% YoY revenue growth with gross margin expansion to 78.4% is genuinely "
        "exceptional and reflects structural AI infrastructure demand, not a cyclical event. "
        "The supply-constrained CEO framing confirmed by earnings call quotes and the CUDA "
        "ecosystem moat are the strongest evidence in the packet. Multi-quarter demand "
        "visibility from hyperscaler capex is credible and directly evidenced."
    ),
    "bear_case_assessment": (
        "The 46% customer concentration in three hyperscalers is the most credible structural "
        "risk — documented in the 10-K and insufficiently addressed by the bull's contest. "
        "The valuation challenge is analytically valid: 35x forward earnings requires sustained "
        "hypergrowth with no execution tolerance. The AMD competitive threat is real but "
        "long-timeline and does not affect the near-term thesis materially."
    ),
    "critical_contention_adjudications": [
        {
            "contention_id": "CON-D-001",
            "adjudication": "bull_correct",
            "reasoning": (
                "SEC filing revenue data (reliability 0.95) outweighs the single-source "
                "news-tier2 order reduction report (reliability 0.50); the latter is "
                "unconfirmed and inconsistent with hyperscaler public capex guidance."
            ),
        },
        {
            "contention_id": "CON-D-002",
            "adjudication": "bear_correct",
            "reasoning": (
                "46% customer concentration documented in 10-K (reliability 0.95) is a "
                "primary source fact. Bull's contest that it is manageable is asserted "
                "without counter-evidence; the structural risk is real and unmitigated."
            ),
        },
    ],
    "philosophy_fit": "adequate",
    "philosophy_fit_notes": (
        "NVDA fits the long-term compounder archetype with structural ecosystem growth and "
        "expanding margins. Valuation premium is expected for compounders. The export "
        "restriction overhang and balanced debate outcome prevent a strong fit classification."
    ),
    "risk_officer_flags": [
        "TIC-002 (export restriction expansion to Blackwell) in MONITORING — highest-priority pre-entry risk.",
        "CAT-001 (BIS export control review) is a high-impact binary event with uncertain outcome within ~45 days.",
    ],
    "monitoring_priorities": [
        {
            "priority": 1,
            "description": "BIS export restriction policy announcements affecting Blackwell and future architectures.",
            "source": "TIC-002",
            "frequency": "weekly",
        },
        {
            "priority": 2,
            "description": "Quarterly revenue growth rate — watch for deceleration below 40% YoY as leading indicator of TIC-001.",
            "source": "TIC-001",
            "frequency": "quarterly",
        },
        {
            "priority": 3,
            "description": "Hyperscaler GPU order volume disclosures in quarterly earnings calls (Microsoft, Google, Amazon).",
            "source": "learning_hook",
            "frequency": "quarterly",
        },
    ],
    "what_would_change_this": (
        "Move to moderate_conviction_enter if: (1) BIS confirms Blackwell chips are not "
        "subject to expanded export restrictions, OR (2) price declines 25%+ creating a "
        "more defensible entry valuation. Do not enter with TIC-002 unresolved and "
        "a balanced debate outcome."
    ),
    "blocking_issues": [],
    "metadata": {
        "debate_outcome_used": "balanced",
        "risk_assessment_used": "needs_attention",
        "score_basis": "debate_adjusted",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _to_dict(dc) -> dict:
    """Convert a dataclass (with possible Enum fields) to a plain JSON-safe dict."""
    return json.loads(
        json.dumps(
            dc.to_dict(),
            default=lambda x: x.value if hasattr(x, "value") else str(x),
        )
    )


DIV  = "=" * 72
DASH = "─" * 72


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{DIV}")
    print("  DUKE PIPELINE DRY RUN — NVDA (NVIDIA Corporation)")
    print("  Stages 04 → 05 → 06 → 07 formatter. No live data.")
    print(f"{DIV}\n")

    packet_path = REPO / "pipeline" / "03_processing" / "examples" / "sample_output.json"
    with open(packet_path) as f:
        packet = json.load(f)

    print(f"  Input:    {packet_path.name}")
    print(f"  Ticker:   {packet['ticker']}  |  "
          f"Items: {len(packet['evidence_items'])}  |  "
          f"Archetype: {packet.get('investment_archetype', '—')}\n")

    # ── STAGE 04: SCORING ─────────────────────────────────────────────────────
    print(DIV)
    print("  STAGE 04 — SCORING")
    print(DASH)

    scoring = score_packet(packet)
    ev  = scoring.evidence_breakdown
    cf  = scoring.confidence_breakdown
    inv = scoring.invalidation_report

    print(f"  Evidence Score   : {scoring.evidence_score:+.1f}")
    print(f"    bull={ev.bull_weight:.3f}  bear={ev.bear_weight:.3f}  "
          f"directional={ev.directional_count}  high-rel={ev.high_reliability_count}")
    print()
    print(f"  Confidence Score : {scoring.confidence_score:.1f}")
    print(f"    base={cf.base_confidence:.1f}  "
          f"penalties=−{cf.total_penalty:.1f}  "
          f"(contra=−{cf.contradiction_penalty:.1f}  "
          f"binary=−{cf.binary_catalyst_penalty:.1f}  "
          f"stale=−{cf.stale_data_penalty:.1f})  "
          f"bonuses=+{cf.bonuses:.1f}")
    print()
    print(f"  Conviction       : {scoring.conviction.value.upper()}")
    print(f"  Recommendation   : {scoring.recommendation.value.upper()}")
    print(f"  Position Sizing  : {_format_sizing(scoring.position_sizing.value)}")
    print()
    print(f"  Invalidation     : {inv.status.value.upper()}")
    if inv.monitoring_conditions:
        print(f"    Monitoring     : {', '.join(inv.monitoring_conditions)}")
    if inv.triggered_conditions:
        print(f"    Triggered      : {', '.join(inv.triggered_conditions)}")
    print()
    print("  Primary Risks:")
    for i, r in enumerate(scoring.primary_risks, 1):
        print(f"    {i}. {r}")
    print()

    scoring_dict = _to_dict(scoring)

    # ── STAGE 05: DEBATE ──────────────────────────────────────────────────────
    print(DIV)
    print("  STAGE 05 — DEBATE")
    print(DASH)

    debate = record_debate(packet, scoring_dict, BULL_POSITION, BEAR_POSITION)
    debate_dict = _to_dict(debate)

    print(f"  Bull adj  : {BULL_POSITION['score_adjustment']:+.0f} score / "
          f"{BULL_POSITION['confidence_adjustment']:+.0f} conf")
    print(f"  Bear adj  : {BEAR_POSITION['score_adjustment']:+.0f} score / "
          f"{BEAR_POSITION['confidence_adjustment']:+.0f} conf")
    print(f"  Net adj   : {debate.net_score_adjustment:+.1f} score / "
          f"{debate.metadata['net_conf_adjustment']:+.1f} conf")
    print()
    print(f"  Evidence  : {debate.base_evidence_score:+.1f} → {debate.debate_evidence_score:+.1f}")
    print(f"  Confidence: {debate.base_confidence_score:.1f} → {debate.debate_confidence_score:.1f}")
    print(f"  Outcome   : {debate.outcome.value.upper()}")
    print()
    print(f"  Contentions ({len(debate.contentions)}):")
    for c in debate.contentions:
        print(f"    [{c.severity.value.upper():<8}] {c.contention_id} | {c.category.upper()}")
        print(f"      {c.bull_claim}")
        print(f"      {c.bear_claim}")
    print()

    # ── STAGE 06: SYNTHESIS ───────────────────────────────────────────────────
    print(DIV)
    print("  STAGE 06 — SYNTHESIS")
    print(DASH)

    synthesis = synthesize(debate_dict, RISK_ASSESSMENT)
    syn_dict  = _to_dict(synthesis)

    print(f"  Synthesis ID       : {synthesis.synthesis_id}")
    print(f"  Ready for CA       : {synthesis.ready_for_chief_analyst}")
    print(f"  Risk Status        : {synthesis.overall_risk_assessment.upper()}")
    print(f"  Blocking Issues    : {synthesis.blocking_issues or '—'}")
    print()
    brief = synthesis.chief_analyst_brief
    print("  Brief assembled:")
    print(f"    Debate outcome   : {brief['debate_outcome']}")
    print(f"    Scores passed    : evidence={brief['scores']['debate_evidence_score']}  "
          f"confidence={brief['scores']['debate_confidence_score']}")
    print(f"    Contentions      : {len(brief['contentions'])} "
          f"[{', '.join(c['severity'] for c in brief['contentions'])}]")
    print(f"    TIC assessments  : {len(brief['risk_assessment']['tic_assessment'])}")
    print(f"    Binary events    : {len(brief['risk_assessment']['binary_event_assessment'])}")
    print(f"    Metadata         : {synthesis.metadata}")
    print()

    # ── STAGE 07: FORMATTED OUTPUT ────────────────────────────────────────────
    print(DIV)
    print("  STAGE 07 — FORMATTED RECOMMENDATION")
    print(DASH)
    print("  (Chief Analyst output is synthetic — simulates AI analyst response)")
    print()
    print(format_recommendation(CHIEF_ANALYST_OUTPUT, syn_dict))


if __name__ == "__main__":
    main()
