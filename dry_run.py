#!/usr/bin/env python3
"""
dry_run.py
DUKE full pipeline dry run — stages 04 through 07.

Usage:
    python3 dry_run.py [--ticker NVDA|BULL|BEAR]

Stages covered:
  04 Scoring   — score_packet() from the pre-built evidence packet
  05 Debate    — record_debate() with synthetic bull/bear analyst positions
  06 Synthesis — synthesize() with a synthetic risk officer assessment
  07 Output    — format_recommendation() with a synthetic chief analyst output

No real data sources are connected. All analyst outputs are pre-written fixtures
that simulate realistic AI analyst responses.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent

# Add all stage directories to sys.path so relative imports inside each module resolve
for _stage in ["04_scoring", "05_debate", "06_synthesis", "07_output"]:
    _p = str(REPO / "pipeline" / _stage)
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scorer import score_packet            # noqa: E402
from debate_recorder import record_debate  # noqa: E402
from synthesizer import synthesize         # noqa: E402
from formatter import format_recommendation  # noqa: E402

# ── Investor profile — position sizing display ────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# NVDA — NVIDIA Corporation (WATCH — balanced debate, monitoring TIC)
# ─────────────────────────────────────────────────────────────────────────────

NVDA_BULL_POS = {
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

NVDA_BEAR_POS = {
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

NVDA_RISK = {
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

NVDA_CA_OUTPUT = {
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
# BULL — Bullhorn Analytics Inc. (STRONG_CONVICTION_ENTER — clean, dominant bull case)
# Expected Stage 04: ev≈+78, conf≈100 → HIGH conviction → STRONG_BUY
# ─────────────────────────────────────────────────────────────────────────────

BULL_BULL_POS = {
    "summary": (
        "Bullhorn Analytics is a structurally superior compounder with every metric moving "
        "in the right direction simultaneously: 42% revenue growth, 82% gross margins, "
        "125% NRR, positive FCF, and insider buying. The bear case is entirely a valuation "
        "argument with no primary-source evidence. The Microsoft competitive threat is "
        "early-stage and not yet visible in any retention or pricing metric. Enter at "
        "full conviction — this is a rare case where the evidence is both clear and "
        "dominated by high-reliability primary sources."
    ),
    "key_arguments": [
        "NRR of 125% means the installed base is growing revenue on its own — this is the single most important SaaS metric and it is accelerating.",
        "82% gross margin expanding from 75% YoY demonstrates pricing power that is durable, not promotional.",
        "CFO Sandra Keller purchased $2.1M in open-market shares — the clearest possible insider confidence signal.",
        "Product cycle (Bullhorn Apex, Q2 upsell launch) adds a near-term revenue accelerant on top of already strong base growth.",
        "No binary events, no monitoring TICs, no contradictions — the evidence base is unusually clean.",
    ],
    "evidence_cited": ["EV-001", "EV-002", "EV-003", "EV-004", "EV-005", "EV-007", "EV-008", "EV-009", "EV-010"],
    "contested_items": ["EV-014"],
    "raised_risks": [],
    "learning_hooks": [
        "NRR remains above 115% for the next four consecutive quarterly disclosures.",
        "Bullhorn Apex upsell attach rate exceeds 20% of eligible base within 2 quarters of general availability.",
        "Microsoft Azure Synapse mid-market launch fails to gain meaningful share in BULL's customer base within 6 quarters.",
    ],
    "score_adjustment": 10.0,
    "confidence_adjustment": 5.0,
}

BULL_BEAR_POS = {
    "summary": (
        "Bullhorn's fundamentals are strong, but the market has already priced in perfection "
        "at 18x NTM revenue. This is 64% above SaaS peer median. A single quarter of NRR "
        "softening or revenue miss would compress the multiple aggressively. The Microsoft "
        "threat is underpriced: Azure Synapse at 35% below BULL's pricing targets exactly "
        "the new logo motion that drives the growth rate. I am not disputing the quality "
        "of the business — I am disputing whether the current price leaves any room for error."
    ),
    "key_arguments": [
        "18x NTM revenue vs. 11x peer median requires sustained 35%+ growth — asymmetric downside if growth decelerates even slightly.",
        "Microsoft Azure Synapse direct overlap in mid-market segment with 35% price undercut targets BULL's highest-volume new logo segment.",
        "Top 3 customers represent 14% of revenue — not catastrophic but still a concentration to monitor.",
    ],
    "evidence_cited": ["EV-013", "EV-014"],
    "contested_items": ["EV-011"],
    "raised_risks": [],
    "learning_hooks": [
        "BULL's NRR compresses below 115% within 4 quarters of Microsoft Synapse mid-market launch.",
        "Net new logo growth decelerates below 10% YoY within 2 quarters of Microsoft pricing announcement.",
    ],
    "valuation_challenge": (
        "At 18x NTM revenue, the market is pricing approximately 35%+ revenue growth for "
        "3+ years. This is achievable but leaves zero margin of safety. If NRR softens "
        "from 125% to 112% — a 13-point move — the growth multiple collapses to peer "
        "median 11x, implying a 39% price decline from current levels. The evidence "
        "score is strong but the risk/reward is asymmetric at this entry price."
    ),
    "score_adjustment": -3.0,
    "confidence_adjustment": -2.0,
}

BULL_RISK = {
    "overall_risk_assessment": "adequate",
    "ready_for_chief_analyst": True,
    "blocking_issues": [],
    "tic_assessment": [
        {
            "condition_id": "TIC-001",
            "quality": "adequate",
            "severity": "fatal",
            "notes": "Revenue at 42% YoY provides 27pp buffer above 15% trigger. Not triggered, no monitoring required.",
        },
        {
            "condition_id": "TIC-002",
            "quality": "adequate",
            "severity": "major",
            "notes": "Gross margin at 82% provides 12pp buffer above 70% trigger. Expansion trend makes this very low risk near-term.",
        },
        {
            "condition_id": "TIC-003",
            "quality": "adequate",
            "severity": "major",
            "notes": "NRR at 125% provides 20pp buffer above 105% trigger. Improving trend — not at risk near-term.",
        },
    ],
    "tic_coverage_gaps": [],
    "risk_factor_assessment": [
        {
            "risk_id": "RSK-001",
            "probability_calibrated": True,
            "notes": "Valuation premium is real but not unusual for a SaaS compounder at this growth rate and quality level. Not a blocking issue.",
        },
        {
            "risk_id": "RSK-002",
            "probability_calibrated": True,
            "notes": "Microsoft competitive threat is early-stage. NRR of 125% shows no current impact on retention. Long-timeline risk, not near-term.",
        },
    ],
    "missing_risk_factors": [],
    "binary_event_assessment": [],
    "monitoring_plan": {
        "frequency": "quarterly",
        "leading_indicators": [
            "Net revenue retention — leading indicator of whether moat is holding against Microsoft competition",
            "Gross margin trend — watch for ASP compression as new logo cohorts mature at lower price points",
            "Net new logo growth rate — leading indicator of whether Microsoft pricing is affecting new sales",
        ],
        "exit_clarity": (
            "Exit if TIC-001 triggered (revenue growth below 15% YoY for two quarters) "
            "or TIC-003 triggered (NRR below 105% for two quarters)."
        ),
    },
}

BULL_CA_OUTPUT = {
    "analyst_role": "chief_analyst",
    "recommendation": "strong_conviction_enter",
    "investment_archetype_confirmed": "long_term_compounder",
    "final_evidence_score": 81.7,
    "final_confidence_score": 100.0,
    "executive_summary": (
        "Bullhorn Analytics is a textbook long-term compounder with evidence quality rarely "
        "seen in a single packet: 42% revenue growth with NRR 125%, 82% gross margins "
        "expanding, positive FCF, and open-market CFO buying — all confirmed by primary "
        "sources. No TICs are in monitoring; no binary events exist. The bear case is "
        "entirely a valuation argument with no primary-source support. The debate was "
        "balanced, but the base evidence score of 78+ leaves no ambiguity about direction. "
        "Enter at full position size."
    ),
    "bull_case_assessment": (
        "The NRR of 125% is the single strongest signal in the packet. It means Bullhorn's "
        "installed base is compounding revenue independently — new sales are purely additive. "
        "The 82% gross margin expanding 690bps YoY confirms pricing power is real and not "
        "promotional. CFO open-market buying of $2.1M is a direct insider confidence signal "
        "that is unambiguous in its interpretation. Product cycle catalyst adds near-term "
        "acceleration on an already-strong base."
    ),
    "bear_case_assessment": (
        "The valuation premium (18x NTM revenue vs. 11x peer median) is real but consistent "
        "with compounders of this quality. The Microsoft competitive threat is early-stage "
        "and not yet visible in NRR data — the most sensitive leading indicator. Both bear "
        "evidence items are analyst reports (reliability 0.65); neither contradicts any "
        "primary-source data. The bear contested EV-011 (TAM growth via Bloomberg) — "
        "reasonable, but Bloomberg tier-1 sourcing outweighs a speculative contest."
    ),
    "critical_contention_adjudications": [],
    "philosophy_fit": "strong",
    "philosophy_fit_notes": (
        "Near-perfect alignment with the long_term_compounder archetype: wide moat from "
        "data network effects and switching costs, margin expansion at scale, multi-year "
        "growth visibility from NRR, no binary catalyst dependency, positive FCF. "
        "Valuation premium is expected and appropriate for this quality tier."
    ),
    "risk_officer_flags": [],
    "monitoring_priorities": [
        {
            "priority": 1,
            "description": "Net revenue retention — must stay above 115% to confirm moat is holding against Microsoft entry.",
            "source": "TIC-003",
            "frequency": "quarterly",
        },
        {
            "priority": 2,
            "description": "Microsoft Azure Synapse mid-market launch adoption data — first signal of competitive pressure.",
            "source": "learning_hook",
            "frequency": "quarterly",
        },
        {
            "priority": 3,
            "description": "Gross margin trajectory through Bullhorn Apex ramp — watch for ASP compression on new cohorts.",
            "source": "TIC-002",
            "frequency": "quarterly",
        },
    ],
    "what_would_change_this": (
        "Reduce to watch if NRR softens below 115% for one quarter (early warning) or "
        "below 110% for two consecutive quarters (TIC-003 approaching). Exit if gross "
        "margin compresses below 75% (approaching TIC-002) or revenue growth decelerates "
        "below 20% (approaching TIC-001). None of these are close to triggering."
    ),
    "blocking_issues": [],
    "metadata": {
        "debate_outcome_used": "balanced",
        "risk_assessment_used": "adequate",
        "score_basis": "debate_adjusted",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# BEAR — Bearmill Retail Corp. (PASS — fatal TIC triggered, broken thesis)
# Expected Stage 04: ev≈−81, FATAL TIC triggered → INVALIDATED → pass
# ─────────────────────────────────────────────────────────────────────────────

BEAR_BULL_POS = {
    "summary": (
        "The bear case on Bearmill overstates the near-term bankruptcy risk. Project Rebuild "
        "is a credible cost restructuring: $320M in savings against a $3.2B revenue base is "
        "achievable through store closures and headcount reduction alone. The 0.3x EV/Sales "
        "valuation is a historical floor for specialty retail recoveries. I concede the "
        "evidence is largely negative, but the market may be pricing in a worst-case scenario "
        "that does not occur. The bull case is speculative but not zero."
    ),
    "key_arguments": [
        "Project Rebuild targets $320M in annualized cost savings — store closure-driven cost reduction is largely within management control.",
        "Historical specialty retail comps show 0.3x EV/Sales is a mean-reversion floor in 6 of the last 8 comparable distress cycles.",
        "Surviving store fleet after 185 closures will have significantly lower occupancy costs and potentially improved per-store economics.",
    ],
    "evidence_cited": ["EV-011", "EV-012"],
    "contested_items": ["EV-001"],
    "raised_risks": [],
    "learning_hooks": [
        "Project Rebuild achieves at least $200M of the $320M targeted savings by Q4 FY2025.",
        "Same-store sales stabilize at -5% YoY or better within 3 quarters as the store fleet rationalizes.",
    ],
    "score_adjustment": -2.0,
    "confidence_adjustment": -3.0,
}

BEAR_BEAR_POS = {
    "summary": (
        "This is not a distress opportunity. This is a broken thesis. TIC-001 has triggered: "
        "revenue has declined more than 20% YoY for two consecutive quarters — the pre-defined "
        "fatal exit condition. Every primary source confirms the same story: negative FCF for "
        "three quarters, 1,110bps gross margin compression, debt at 4.2x equity approaching "
        "covenant breach, and CEO and CFO selling their own shares ahead of further "
        "deterioration. The bull concedes a negative score adjustment. There is nothing here."
    ),
    "key_arguments": [
        "TIC-001 triggered — two consecutive quarters of >20% revenue decline. The pre-defined fatal condition has been met.",
        "Gross margin at 27% is already near the structural floor for physical retail; further compression cannot be cost-managed.",
        "CEO sold 40% of shares open-market — this is not a 10b5-1 plan; it is informed selling ahead of further deterioration.",
        "Moody's B3 credit rating implies approximately 20-25% default probability over 5 years — covenant breach is probable within 2-3 quarters.",
        "E-commerce market share in home goods grew from 31% to 47% in 24 months — BEAR has no credible digital response.",
    ],
    "evidence_cited": ["EV-001", "EV-002", "EV-003", "EV-004", "EV-007", "EV-010"],
    "contested_items": ["EV-011", "EV-012"],
    "raised_risks": [
        "Chapter 11 reorganization is a non-trivial probability within 12-18 months at current FCF burn rate."
    ],
    "learning_hooks": [
        "Bearmill files for Chapter 11 within 18 months of today.",
        "Debt covenant breach disclosed within 2 quarters without a waiver announcement.",
        "Q2 FY2025 gross margin falls below 25%, triggering TIC-002 monitoring.",
    ],
    "valuation_challenge": (
        "The Piper Sandler '0.3x EV/Sales floor' argument assumes a recovery trajectory "
        "that does not exist here. Historical specialty retail recoveries occurred when "
        "the channel shift was temporary (2008 recession) or when the company had a "
        "defensible omnichannel position. BEAR has neither. The 'floor' argument requires "
        "a going-concern assumption that is not supported by the FCF and debt evidence."
    ),
    "score_adjustment": -15.0,
    "confidence_adjustment": -8.0,
}

BEAR_RISK = {
    "overall_risk_assessment": "needs_attention",
    "ready_for_chief_analyst": True,
    "blocking_issues": [
        "TIC-001 triggered — revenue declined >20% YoY for two consecutive quarters. Fatal threshold confirmed in Q4 FY2024 and Q1 FY2025 10-Q primary source filings."
    ],
    "tic_assessment": [
        {
            "condition_id": "TIC-001",
            "quality": "adequate",
            "severity": "fatal",
            "notes": "TRIGGERED. Revenue -21% YoY in Q4 FY2024 and -24% YoY in Q1 FY2025 — two consecutive quarters confirmed. Fatal trigger met per pre-defined exit criteria.",
        },
        {
            "condition_id": "TIC-002",
            "quality": "adequate",
            "severity": "major",
            "notes": "Not yet triggered at 27% gross margin vs. 22% threshold, but trajectory is toward trigger within 2-3 quarters at current rate of compression.",
        },
    ],
    "tic_coverage_gaps": [],
    "risk_factor_assessment": [
        {
            "risk_id": "RSK-001",
            "probability_calibrated": True,
            "notes": "Market share erosion to e-commerce is structural and permanent. Store closure program does not address the root cause.",
        },
        {
            "risk_id": "RSK-002",
            "probability_calibrated": True,
            "notes": "Covenant breach probable within 2-3 quarters. Lender negotiation may result in waiver but at significant cost to equity holders.",
        },
    ],
    "missing_risk_factors": [],
    "binary_event_assessment": [],
    "monitoring_plan": {
        "frequency": "monthly",
        "leading_indicators": [
            "Same-store sales weekly velocity — any sign of stabilization vs. continued acceleration of decline",
            "Debt covenant compliance — any waiver disclosure in 8-K filings",
            "FCF burn rate — trajectory toward cash depletion or covenant breach",
        ],
        "exit_clarity": "Thesis is invalidated. This monitoring plan is for existing position holders or short sellers only.",
    },
}

BEAR_CA_OUTPUT = {
    "analyst_role": "chief_analyst",
    "recommendation": "pass",
    "investment_archetype_confirmed": "does_not_fit",
    "final_evidence_score": -92.2,
    "final_confidence_score": 73.3,
    "executive_summary": (
        "The thesis on Bearmill Retail is broken. TIC-001 — revenue declining more than "
        "20% YoY for two consecutive quarters — has triggered, meeting the pre-defined "
        "fatal exit condition. The evidence base is overwhelmingly bearish from primary "
        "sources: negative FCF for three quarters, 1,110bps gross margin compression, "
        "massive insider selling documented in SEC Form 4s, and a Moody's downgrade to "
        "B3. The bull case consists of a company press release (reliability 0.40) and a "
        "single analyst opinion (reliability 0.50). The debate outcome is bear_prevails. "
        "Pass with no further deliberation required."
    ),
    "bull_case_assessment": (
        "The bull case — Project Rebuild cost savings and historical 0.3x EV/Sales floor — "
        "is unsubstantiated by primary-source evidence. The restructuring plan comes from a "
        "company press release with no third-party verification, interim milestones, or "
        "contractual commitment. Historical specialty retail valuation floors apply to "
        "companies with credible recovery paths; BEAR has no omnichannel capability and "
        "faces structural channel shift. The bull analyst's -2 score adjustment concedes "
        "that even the optimistic view sees the evidence as net negative."
    ),
    "bear_case_assessment": (
        "The bear case is decisive and dominated by primary-source data. Two consecutive "
        "quarters of >20% revenue decline confirmed in SEC filings. Gross margin at 27%, "
        "compressed 1,110bps YoY. FCF negative for three consecutive quarters. "
        "Debt covenant at risk within 2-3 quarters per interest coverage ratio trajectory. "
        "CEO sold 40% of direct holdings open-market — not a 10b5-1 plan. Moody's B3 "
        "credit rating reflects approximately 20-25% five-year default probability."
    ),
    "critical_contention_adjudications": [
        {
            "contention_id": "CON-D-002",
            "adjudication": "bear_correct",
            "reasoning": (
                "The revenue decline is documented in two consecutive SEC filings (reliability 0.95) "
                "with specific quarterly figures. Bull's contest that the decline 'may reverse' "
                "is speculative and unsupported by any primary-source evidence. The TIC-001 "
                "trigger is definitional — two quarters of >20% decline — and it has been met."
            ),
        }
    ],
    "philosophy_fit": "does_not_fit",
    "philosophy_fit_notes": (
        "Bearmill does not fit either investment archetype. It is not a compounder — "
        "revenue is declining structurally and there is no moat. It is not a deep value "
        "opportunity — the thesis is invalidated, debt prevents a value floor from "
        "forming, and the restructuring plan lacks the primary-source credibility required "
        "to establish a margin of safety. This is a distressed situation, not an investment."
    ),
    "risk_officer_flags": [
        "TIC-001 triggered — fatal threshold met. Investment thesis invalidated per pre-defined exit criteria.",
        "Debt covenant breach probable within 2-3 quarters at current FCF burn rate of -$182M TTM.",
    ],
    "monitoring_priorities": [
        {
            "priority": 1,
            "description": "Debt covenant compliance — watch for 8-K disclosures of waiver requests or breach events.",
            "source": "risk_factor",
            "frequency": "monthly",
        },
        {
            "priority": 2,
            "description": "Same-store sales velocity — any stabilization signal would be the first data point for thesis re-evaluation.",
            "source": "learning_hook",
            "frequency": "monthly",
        },
    ],
    "what_would_change_this": (
        "Re-evaluate only if: TIC-001 un-triggers (two consecutive quarters of revenue "
        "decline less than 20% YoY) AND gross margins stabilize above 30% AND FCF returns "
        "to positive. All three conditions simultaneously. At current trajectory, none are "
        "achievable within a 12-month horizon. Pass."
    ),
    "blocking_issues": [
        "TIC-001 triggered — revenue declined >20% YoY for two consecutive quarters. Fatal exit condition met."
    ],
    "metadata": {
        "debate_outcome_used": "bear_prevails",
        "risk_assessment_used": "needs_attention",
        "score_basis": "debate_adjusted",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

_CONFIGS = {
    "NVDA": {
        "packet": REPO / "pipeline" / "03_processing" / "examples" / "sample_output.json",
        "bull_pos":  NVDA_BULL_POS,
        "bear_pos":  NVDA_BEAR_POS,
        "risk":      NVDA_RISK,
        "ca_output": NVDA_CA_OUTPUT,
    },
    "BULL": {
        "packet": REPO / "pipeline" / "03_processing" / "examples" / "strong_bull_sample.json",
        "bull_pos":  BULL_BULL_POS,
        "bear_pos":  BULL_BEAR_POS,
        "risk":      BULL_RISK,
        "ca_output": BULL_CA_OUTPUT,
    },
    "BEAR": {
        "packet": REPO / "pipeline" / "03_processing" / "examples" / "bear_sample.json",
        "bull_pos":  BEAR_BULL_POS,
        "bear_pos":  BEAR_BEAR_POS,
        "risk":      BEAR_RISK,
        "ca_output": BEAR_CA_OUTPUT,
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
    parser = argparse.ArgumentParser(description="DUKE pipeline dry run")
    parser.add_argument(
        "--ticker",
        default="NVDA",
        choices=list(_CONFIGS.keys()),
        help="Which sample packet to run (default: NVDA)",
    )
    args = parser.parse_args()

    cfg = _CONFIGS[args.ticker]

    with open(cfg["packet"]) as f:
        packet = json.load(f)

    print(f"\n{DIV}")
    print(f"  DUKE PIPELINE DRY RUN — {packet['ticker']} ({packet['company_name']})")
    print("  Stages 04 → 05 → 06 → 07 formatter. No live data.")
    print(f"{DIV}\n")

    print(f"  Input:    {cfg['packet'].name}")
    print(f"  Ticker:   {packet['ticker']}  |  "
          f"Items: {len(packet['evidence_items'])}  |  "
          f"Archetype: {packet.get('investment_archetype', '—')}\n")

    # ── STAGE 04: SCORING ─────────────────────────────────────────────────────
    print(DIV)
    print("  STAGE 04 — SCORING")
    print(DASH)

    scoring = score_packet(packet)
    inv = scoring.invalidation_report

    print(f"  Evidence Score   : {scoring.evidence_score:+.1f}")
    if scoring.evidence_score_note:
        print(f"    ↳ {scoring.evidence_score_note}")
    print()
    print(f"  Confidence Score : {scoring.confidence_score:.1f}")
    if scoring.confidence_score_note:
        print(f"    ↳ {scoring.confidence_score_note}")
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

    debate = record_debate(packet, scoring_dict, cfg["bull_pos"], cfg["bear_pos"])
    debate_dict = _to_dict(debate)

    print(f"  Bull adj  : {cfg['bull_pos']['score_adjustment']:+.0f} score / "
          f"{cfg['bull_pos']['confidence_adjustment']:+.0f} conf")
    print(f"  Bear adj  : {cfg['bear_pos']['score_adjustment']:+.0f} score / "
          f"{cfg['bear_pos']['confidence_adjustment']:+.0f} conf")
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

    synthesis = synthesize(debate_dict, cfg["risk"])
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
          f"[{', '.join(c['severity'] for c in brief['contentions'])}]"
          if brief['contentions'] else "    Contentions      : 0")
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
    print(format_recommendation(
        cfg["ca_output"],
        syn_dict,
        technical_state=packet.get("technical_state", {}),
    ))


if __name__ == "__main__":
    main()
