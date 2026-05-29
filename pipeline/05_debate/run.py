#!/usr/bin/env python3
"""
run.py — Stage 05 (Debate) orchestration bridge.

Usage:
    python3 run.py TICKER [--date YYYYMMDD]

If --date is omitted, the most recent file for TICKER is used.

Loads:
    data/scored/{TICKER}_score_{date}.json              Stage 04 output
    data/processed/{TICKER}_analyst_brief_{date}.json   Stage 02/03 output

Round 1: calls Bull and Bear Claude analysts independently, detects contentions,
computes debate-adjusted scores.

Round 2: Bull and Bear each read the opposing Round 1 position and respond.
Rebuttal score adjustments are clamped to [-10, +10] and are down-only
(bull cannot raise conviction above Round 1; bear cannot go more negative).
Writes: data/debate/{TICKER}_debate_{date}.json
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── path setup so stage-internal imports resolve ──────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from position_builder import build_bull_brief, build_bear_brief  # noqa: E402
from debate_recorder import record_debate, _make_debate_id        # noqa: E402
from debate_scorer import compute_debate_scores                    # noqa: E402
from common.brief_adapter import build_evidence_packet           # noqa: E402

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not installed — run: pip install anthropic")

_MODEL          = "claude-sonnet-4-6"
_MAX_TOKENS     = 16384  # Round 1: bull/bear independent positions (raised from 4096 — Path B prompt expansion pushed responses past the prior cap, causing silent truncation→parse-fail)
_MAX_TOKENS_R2  = 16384  # Round 2: rebuttals must respond to every opposing argument
_MOD_MODEL      = "claude-sonnet-4-6"
_MOD_MAX_TOKENS = 8192   # Debate Moderator: neutral evidence referee
_REPO_ROOT  = _THIS_DIR.parent.parent   # pipeline/05_debate/../../ = repo root


# ─────────────────────────────────────────────────────────────────────────────
# FILE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def _find_latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file found matching: {pattern}")
    return Path(matches[-1])


def _load_scoring(ticker: str, date_str: str | None) -> tuple[dict, Path]:
    base    = str(_REPO_ROOT / "data" / "scored")
    pattern = f"{base}/{ticker}_score_{date_str or '*'}.json"
    path    = _find_latest(pattern)
    with open(path) as f:
        return json.load(f), path


def _load_brief(ticker: str, date_str: str | None) -> tuple[dict, Path]:
    base    = str(_REPO_ROOT / "data" / "processed")
    pattern = f"{base}/{ticker}_analyst_brief_{date_str or '*'}.json"
    path    = _find_latest(pattern)
    with open(path) as f:
        return json.load(f), path


# ─────────────────────────────────────────────────────────────────────────────
# PACKET SYNTHESIS
# ─────────────────────────────────────────────────────────────────────────────

def _build_packet(brief: dict, scoring: dict) -> dict:
    """Delegate to the shared brief adapter in common/."""
    return build_evidence_packet(brief, scoring)


# ─────────────────────────────────────────────────────────────────────────────
# CLAUDE API
# ─────────────────────────────────────────────────────────────────────────────

def _load_prompt(name: str) -> str:
    with open(_THIS_DIR / "prompts" / name) as f:
        return f.read()


def _invoke_llm(
    client: anthropic.Anthropic,
    system_prompt: str,
    brief: dict,
    label: str,
    max_tokens: int,
) -> tuple[dict | None, str]:
    """Single LLM call. Returns (parsed_dict, raw_text). parsed_dict is None on parse failure."""
    user_msg = (
        "Here is your structured brief. Study it carefully before responding.\n\n"
        + json.dumps(brief, indent=2)
    )
    print(f"  calling {label}...", flush=True)
    resp = client.messages.create(
        model=_MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        start = 1
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        raw   = "\n".join(lines[start:end])

    # Locate the first '{' and use raw_decode so trailing content after a
    # complete JSON object is tolerated. This addresses a systematic bear-side
    # behavior where the LLM emits a valid JSON object followed by a closing
    # remark or a second block — json.loads (strict) rejects that as "Extra
    # data" even though the structured response itself is complete.
    #
    # CRITICAL GUARD — do not "simplify" this into something that swallows
    # truncated JSON. raw_decode raises JSONDecodeError when the leading
    # object is incomplete (e.g. a response cut off mid-generation by a token
    # cap, leaving unclosed braces/brackets). That MUST keep flagging as a
    # parse failure so the retry-then-flag and not_computable safety nets
    # fire — silently accepting a partial object would hide real data loss.
    # Tolerate trailing text after a complete object; never tolerate
    # incompleteness within the object itself.
    start_idx = raw.find("{")
    if start_idx < 0:
        print(f"  WARNING: {label} response contains no JSON object")
        print(f"  raw (first 400 chars): {raw[:400]}")
        return None, raw
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw, start_idx)
        return obj, raw
    except json.JSONDecodeError as exc:
        print(f"  WARNING: {label} response is not valid JSON — {exc}")
        print(f"  raw (first 400 chars): {raw[:400]}")
        return None, raw


def _call_analyst(
    client: anthropic.Anthropic,
    system_prompt: str,
    brief: dict,
    label: str,
    max_tokens: int = _MAX_TOKENS,
) -> dict:
    """
    Round 1 analyst call. Retries once on JSON parse failure (mirrors
    _call_rebuttal_analyst). On persistent failure, returns a sentinel dict
    with position_parse_failed=True and NO score_adjustment / confidence_adjustment
    keys — so downstream callers cannot mistake a parse error for a real "no
    change" score of 0.0. The Round 1 driver in main() detects this flag and
    writes a debate record marked debate_invalid with outcome=not_computable.
    """
    parsed, raw = _invoke_llm(client, system_prompt, brief, label, max_tokens)
    if parsed is not None:
        return parsed
    print(f"  {label} parse failed — retrying once...")
    parsed, raw = _invoke_llm(client, system_prompt, brief, f"{label} (retry)", max_tokens)
    if parsed is not None:
        return parsed
    print(f"  ERROR: {label} parse failed on both attempts — flagging position as missing")
    return {
        "analyst_role":          label.lower().split()[0],
        "position_parse_failed": True,
        "parse_failure_reason":  "JSON parse failed on initial call and retry",
        "raw_text_preview":      raw[:500],
    }


def _call_rebuttal_analyst(
    client: anthropic.Anthropic,
    system_prompt: str,
    brief: dict,
    label: str,
    max_tokens: int,
) -> dict:
    """
    Round 2 rebuttal call. Retries once on JSON parse failure. On persistent
    failure, returns a sentinel dict with rebuttal_parse_failed=True and no
    score_adjustment / confidence_adjustment keys — so downstream callers
    cannot mistake a parse error for a real "no change" score of 0.0.
    """
    parsed, raw = _invoke_llm(client, system_prompt, brief, label, max_tokens)
    if parsed is not None:
        return parsed
    print(f"  {label} parse failed — retrying once...")
    parsed, raw = _invoke_llm(client, system_prompt, brief, f"{label} (retry)", max_tokens)
    if parsed is not None:
        return parsed
    print(f"  ERROR: {label} parse failed on both attempts — flagging rebuttal as missing")
    return {
        "analyst_role":          label.lower().split()[0],
        "rebuttal_parse_failed": True,
        "parse_failure_reason":  "JSON parse failed on initial call and retry",
        "raw_text_preview":      raw[:500],
    }


# ─────────────────────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def _write_debate(record: dict, ticker: str, date_tag: str) -> Path:
    out_dir = _REPO_ROOT / "data" / "debate"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ticker}_debate_{date_tag}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    return path


def _print_summary(record: dict) -> None:
    m = record.get("metadata", {})
    print()
    print("=" * 62)
    print(f"  DEBATE COMPLETE — {record['ticker']}  ({record['debated_at'][:10]})")
    print("=" * 62)
    outcome = record["outcome"]
    outcome_str = outcome.value if hasattr(outcome, "value") else str(outcome)
    print(f"  Outcome:       {outcome_str}")
    ev_base  = record['base_evidence_score']
    ev_post  = record['debate_evidence_score']
    cf_base  = record['base_confidence_score']
    cf_post  = record['debate_confidence_score']
    net_ev   = record['net_score_adjustment']
    net_cf   = m.get('net_conf_adjustment', 0.0)
    print(f"  Evidence:      {ev_base:+.1f}  →  {ev_post:+.1f}  (net {net_ev:+.1f})")
    print(f"  Confidence:    {cf_base:.1f}  →  {cf_post:.1f}  (net {net_cf:+.1f})")
    n_con  = m.get('contention_count', 0)
    n_crit = m.get('critical_contentions', 0)
    n_mat  = m.get('material_contentions', 0)
    print(f"  Contentions:   {n_con}  (critical={n_crit}  material={n_mat})")
    print(f"  Conviction:    {record['original_conviction']}")
    print("=" * 62)


# ─────────────────────────────────────────────────────────────────────────────
# DEBATE MODERATOR — neutral evidence referee
# ─────────────────────────────────────────────────────────────────────────────
# The Moderator scores evidence asymmetry on a fixed pool of 10 points (bull +
# bear sum to 10). The code-side derive_lean below normalises the LLM's two
# scores and applies a ±0.5 epsilon band (tightened from ±1.0 in EDIT 2a) — the
# LLM cannot decide its own "balanced" label. This is the structural tax that
# kills the all-balanced default.
#
# As of EDIT 2 the Moderator drives:
#   - the debate outcome label (via debate_scorer._outcome_and_weights_from_moderator)
#   - the 70/30 (margin-scaled) winner/loser weighting on the self-scores
#   - the Chief's merit_lean anchor (threaded via synthesizer._build_brief)
# Self-scores (bull_score_adj / bear_score_adj) remain in the debate record
# for audit/traceability but no longer feed the outcome classifier or the
# weighting ratio.

def _strip_scores(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items()
            if k not in ("score_adjustment", "confidence_adjustment")}


def _build_moderator_brief(debate_dict: dict) -> dict:
    return {
        "ticker":       debate_dict.get("ticker"),
        "company_name": debate_dict.get("company_name"),
        "instructions": (
            "You are the Debate Moderator. Read both positions, both rebuttals, "
            "and the contentions. Allocate exactly 10 points between bull and "
            "bear based on grounded surviving evidence — not advocacy volume. "
            "Return the JSON structure specified in the system prompt."
        ),
        "bull_position": _strip_scores(debate_dict.get("bull_position") or {}),
        "bear_position": _strip_scores(debate_dict.get("bear_position") or {}),
        "bull_rebuttal": _strip_scores(debate_dict.get("bull_rebuttal") or {}),
        "bear_rebuttal": _strip_scores(debate_dict.get("bear_rebuttal") or {}),
        "contentions":   debate_dict.get("contentions") or [],
    }


def derive_lean(bull, bear) -> tuple[str | None, float]:
    """
    Code-side lean derivation. Normalises to sum-10 then applies the +/-1.0
    epsilon band. "balanced" only when the normalised scores are within 1.0 of
    each other; otherwise the higher score wins. Returns (lean, signed margin).
    margin = bull - bear after normalisation (positive = bull leans).
    """
    bull = float(bull or 0)
    bear = float(bear or 0)
    total = bull + bear
    if total <= 0:
        return None, 0.0
    b = 10.0 * bull / total
    r = 10.0 * bear / total
    margin = round(b - r, 2)
    # Epsilon band: balanced only when scores are within 0.5 of each other.
    # Tightened from 1.0 to 0.5 in EDIT 2a — the 1.0 band suppressed the four
    # real bear reads (DXCM/FSLR/GEN/PAYX at 5.5/4.5) and three thin bull reads
    # observed in the 21-ticker harness sample; 0.5 surfaces them.
    if abs(margin) <= 0.5:
        return "balanced", margin
    return ("bull_leans" if margin > 0 else "bear_leans"), margin


def _moderator_fallback() -> dict:
    """Surface parse failure visibly — do NOT default to balanced."""
    return {
        "analyst_role":         "debate_moderator",
        "bull_evidence_score":  None,
        "bear_evidence_score":  None,
        "lean":                 None,
        "margin":               None,
        "decisive_evidence":    "",
        "reasoning":            "Moderator parse failed — verdict unavailable. Downstream consumers should treat this as a failure mode, not as a balanced verdict.",
        "contention_calls":     [],
        "moderator_parse_failed": True,
    }


def _apply_moderator_verdict_to_debate_dict(debate_dict: dict) -> None:
    """
    Overwrite outcome + debate-adjusted scores on debate_dict using the
    Moderator block. record_debate already populated these from the self-scores
    earlier in the run; this rewrites them with Moderator-driven values.

    Self-scores remain in bull_position / bear_position for traceability — they
    no longer drive the outcome label or the weighting ratio.
    """
    moderator = debate_dict.get("moderator")
    base_ev   = float(debate_dict.get("base_evidence_score")   or 0.0)
    base_conf = float(debate_dict.get("base_confidence_score") or 0.0)
    bull = debate_dict.get("bull_position") or {}
    bear = debate_dict.get("bear_position") or {}
    scores = compute_debate_scores(
        base_evidence_score=base_ev,
        base_confidence_score=base_conf,
        bull_score_adj=float(bull.get("score_adjustment")      or 0.0),
        bull_conf_adj =float(bull.get("confidence_adjustment") or 0.0),
        bear_score_adj=float(bear.get("score_adjustment")      or 0.0),
        bear_conf_adj =float(bear.get("confidence_adjustment") or 0.0),
        moderator=moderator,
    )
    outcome = scores["outcome"]
    debate_dict["outcome"] = outcome.value if hasattr(outcome, "value") else str(outcome)
    debate_dict["debate_evidence_score"]   = scores["debate_evidence_score"]
    debate_dict["debate_confidence_score"] = scores["debate_confidence_score"]
    debate_dict["net_score_adjustment"]    = scores["net_score_adjustment"]
    meta = debate_dict.setdefault("metadata", {})
    meta["net_conf_adjustment"] = scores["net_conf_adjustment"]


def _call_moderator(client, debate_dict: dict) -> dict:
    """Run the Moderator. Single attempt. Returns a dict — the moderator block
    that gets attached to the debate record."""
    with open(_THIS_DIR / "prompts" / "debate_moderator.md") as f:
        system_prompt = f.read()
    brief  = _build_moderator_brief(debate_dict)
    print("  calling Debate Moderator...", flush=True)
    parsed, _raw = _invoke_llm(client, system_prompt, brief, "Debate Moderator", _MOD_MAX_TOKENS)
    if parsed is None:
        print("  WARNING: Moderator parse failed; using fallback (lean=None, scores=None)")
        return _moderator_fallback()
    bull = parsed.get("bull_evidence_score")
    bear = parsed.get("bear_evidence_score")
    lean, margin = derive_lean(bull, bear)
    return {
        "analyst_role":         "debate_moderator",
        "bull_evidence_score":  bull,
        "bear_evidence_score":  bear,
        "lean":                 lean,            # code-derived, not the LLM's
        "margin":               margin,
        "lean_llm_reported":    parsed.get("lean"),
        "decisive_evidence":    parsed.get("decisive_evidence") or "",
        "reasoning":            parsed.get("reasoning") or "",
        "contention_calls":     parsed.get("contention_calls") or [],
        "moderator_parse_failed": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 05 Debate orchestration")
    parser.add_argument("ticker", type=str.upper)
    parser.add_argument("--date", default=None, help="YYYYMMDD (defaults to most recent file)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set in environment")

    client = anthropic.Anthropic(api_key=api_key)

    print(f"\nStage 05 Debate — {args.ticker}")
    print("-" * 40)

    # ── Load inputs ───────────────────────────────────────────────────────────
    scoring, scoring_path = _load_scoring(args.ticker, args.date)
    brief,   brief_path   = _load_brief(args.ticker, args.date)

    print(f"  scoring:       {scoring_path.name}")
    print(f"  brief:         {brief_path.name}")

    packet = _build_packet(brief, scoring)
    n_bull = sum(1 for e in packet["evidence_items"] if e["direction"] == "bullish")
    n_bear = sum(1 for e in packet["evidence_items"] if e["direction"] == "bearish")
    print(f"  evidence:      {len(packet['evidence_items'])} items  (bull={n_bull}  bear={n_bear})")
    print(f"  scores:        evidence={scoring['evidence_score']:+.1f}  conf={scoring['confidence_score']:.1f}")
    print(f"  conviction:    {scoring['conviction']}")

    # ── Build analyst briefs ──────────────────────────────────────────────────
    bull_brief = build_bull_brief(packet, scoring)
    bear_brief = build_bear_brief(packet, scoring)

    # Inject archetype so analysts know which framework to apply
    bull_brief["investment_archetype"] = brief.get("screening_archetype", "")
    bear_brief["investment_archetype"] = brief.get("screening_archetype", "")

    # ── Round 1: Bull and Bear (independent) ──────────────────────────────────
    print("\nRound 1 — independent positions")
    bull_system = _load_prompt("bull_analyst.md")
    bear_system = _load_prompt("bear_analyst.md")

    bull_pos = _call_analyst(client, bull_system, bull_brief, "Bull Analyst")
    bear_pos = _call_analyst(client, bear_system, bear_brief, "Bear Analyst")

    # ── R1 parse-failure short-circuit ────────────────────────────────────────
    # If either Round 1 position failed to parse (after retry), the debate
    # cannot be scored. Fabricating 0.0 would let a parse error flow through as
    # a misleading "balanced" outcome (the failure mode that hit VRT in the
    # Path B validation run). Instead, write a debate record marked
    # debate_invalid with outcome=not_computable, pass Stage 04 baseline scores
    # through unchanged, and skip Round 2 (rebuttals against empty positions
    # are vacuous).
    bull_r1_failed = bool(bull_pos.get("position_parse_failed"))
    bear_r1_failed = bool(bear_pos.get("position_parse_failed"))

    if bull_r1_failed or bear_r1_failed:
        print(
            f"\n  ERROR: Round 1 parse failed — "
            f"bull={bull_r1_failed} bear={bear_r1_failed}"
        )
        print("         Debate cannot be scored; writing not_computable record and skipping Round 2.")
        base_ev = round(float(scoring.get("evidence_score", 0.0)),   1)
        base_cf = round(float(scoring.get("confidence_score", 0.0)), 1)
        debate_dict = {
            "debate_id":                 _make_debate_id(args.ticker),
            "score_reference":           scoring.get("score_id", ""),
            "packet_reference":          packet.get("packet_id", ""),
            "ticker":                    args.ticker,
            "company_name":              packet.get("company_name", ""),
            "debated_at":                datetime.now(timezone.utc).isoformat(),
            "bull_position":             bull_pos,
            "bear_position":             bear_pos,
            "contentions":               [],
            "base_evidence_score":       base_ev,
            "base_confidence_score":     base_cf,
            # Pass Stage 04 baseline through unchanged — no debate adjustment was computed.
            "debate_evidence_score":     base_ev,
            "debate_confidence_score":   base_cf,
            "net_score_adjustment":      0.0,
            "outcome":                   "not_computable",
            "original_conviction":       scoring.get("conviction", ""),
            "original_recommendation":   scoring.get("recommendation", ""),
            "debate_invalid":            True,
            "metadata": {
                "round_1_bull_parse_failed": bull_r1_failed,
                "round_1_bear_parse_failed": bear_r1_failed,
                "round_2_complete":          False,
                "reason": (
                    "Round 1 JSON parse failed after retry; debate not computable. "
                    "Stage 04 baseline scores are passed through unchanged."
                ),
            },
        }
        date_tag = scoring.get("scored_at", "")[:10].replace("-", "") or args.date or "unknown"
        out_path = _write_debate(debate_dict, args.ticker, date_tag)
        print(f"\n  written: {out_path.relative_to(_REPO_ROOT)}")
        print("  ⚠ DEBATE INVALID — outcome=not_computable, scores unchanged from Stage 04")
        return

    # ── Record debate ─────────────────────────────────────────────────────────
    debate_record = record_debate(packet, scoring, bull_pos, bear_pos)
    debate_dict   = debate_record.to_dict()

    # Preserve raw analyst outputs for Round 2 and downstream inspection
    debate_dict["bull_position_raw"] = bull_pos
    debate_dict["bear_position_raw"] = bear_pos

    # ── Round 2: Rebuttals ────────────────────────────────────────────────────
    print("\nRound 2 — rebuttals")
    bull_rebuttal_system = _load_prompt("bull_rebuttal.md")
    bear_rebuttal_system = _load_prompt("bear_rebuttal.md")

    # Cross-feed: each analyst receives the other's Round 1 position.
    bull_r2_brief = {
        "ticker":               args.ticker,
        "investment_archetype": brief.get("screening_archetype", ""),
        "scoring_baseline":     bull_brief["scoring_baseline"],
        "your_round1_position": bull_pos,
        "bear_round1_position": bear_pos,
    }
    bear_r2_brief = {
        "ticker":               args.ticker,
        "investment_archetype": brief.get("screening_archetype", ""),
        "scoring_baseline":     bear_brief["scoring_baseline"],
        "your_round1_position": bear_pos,
        "bull_round1_position": bull_pos,
    }
    bull_r2 = _call_rebuttal_analyst(client, bull_rebuttal_system, bull_r2_brief, "Bull Rebuttal", _MAX_TOKENS_R2)
    bear_r2 = _call_rebuttal_analyst(client, bear_rebuttal_system, bear_r2_brief, "Bear Rebuttal", _MAX_TOKENS_R2)

    bull_parse_failed = bool(bull_r2.get("rebuttal_parse_failed"))
    bear_parse_failed = bool(bear_r2.get("rebuttal_parse_failed"))

    # Round 1 baseline values used for the down-only clamp on Round 2.
    bull_r1_score = float(bull_pos.get("score_adjustment", 0.0))
    bull_r1_conf  = float(bull_pos.get("confidence_adjustment", 0.0))
    bear_r1_score = float(bear_pos.get("score_adjustment", 0.0))
    bear_r1_conf  = float(bear_pos.get("confidence_adjustment", 0.0))

    # Enforce down-only conviction clamp in code (prompts also require this).
    # Bull R2: cannot raise score_adjustment above Round 1 level.
    # Bear R2: cannot lower score_adjustment below Round 1 level (more negative = more bearish).
    # Both clamped to [-10, +10] — narrower than Round 1's [-15, +15].
    # Parse-failed rebuttals carry no scores; they remain flagged and unclamped.
    if not bull_parse_failed:
        bull_r2_score = max(-10.0, min(float(bull_r2.get("score_adjustment", 0.0)), 10.0))
        bull_r2_conf  = max(-10.0, min(float(bull_r2.get("confidence_adjustment", 0.0)), 10.0))
        bull_r2["score_adjustment"]      = min(bull_r2_score, bull_r1_score)
        bull_r2["confidence_adjustment"] = min(bull_r2_conf,  bull_r1_conf)
    if not bear_parse_failed:
        bear_r2_score = max(-10.0, min(float(bear_r2.get("score_adjustment", 0.0)), 10.0))
        bear_r2_conf  = max(-10.0, min(float(bear_r2.get("confidence_adjustment", 0.0)), 10.0))
        bear_r2["score_adjustment"]      = max(bear_r2_score, bear_r1_score)
        bear_r2["confidence_adjustment"] = max(bear_r2_conf,  bear_r1_conf)

    debate_dict["bull_rebuttal"] = bull_r2
    debate_dict["bear_rebuttal"] = bear_r2
    debate_dict["metadata"]["round_2_complete"]            = not (bull_parse_failed or bear_parse_failed)
    debate_dict["metadata"]["bull_rebuttal_parse_failed"]  = bull_parse_failed
    debate_dict["metadata"]["bear_rebuttal_parse_failed"]  = bear_parse_failed

    # ── Debate Moderator: neutral evidence referee (drives outcome + weighting) ──
    # EDIT 2 rewire: the Moderator's lean drives the outcome label and its
    # margin drives the margin-scaled (0.50..0.80) winner/loser weighting.
    # Self-scores stay in the record for traceability but no longer feed
    # the outcome classifier or the weight ratio. record_debate populated
    # outcome/scores from a moderator-less call above (→ INCONCLUSIVE
    # fallback); the call below overwrites those fields with
    # Moderator-driven values.
    print("\nDebate Moderator")
    debate_dict["moderator"] = _call_moderator(client, debate_dict)
    _apply_moderator_verdict_to_debate_dict(debate_dict)

    # ── Write output ──────────────────────────────────────────────────────────
    date_tag = scoring.get("scored_at", "")[:10].replace("-", "") or args.date or "unknown"
    out_path = _write_debate(debate_dict, args.ticker, date_tag)
    print(f"\n  written: {out_path.relative_to(_REPO_ROOT)}")

    _print_summary(debate_dict)


if __name__ == "__main__":
    main()
