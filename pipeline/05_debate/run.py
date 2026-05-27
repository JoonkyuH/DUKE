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
from pathlib import Path

# ── path setup so stage-internal imports resolve ──────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_REPO_ROOT))

from position_builder import build_bull_brief, build_bear_brief  # noqa: E402
from debate_recorder import record_debate                         # noqa: E402
from common.brief_adapter import build_evidence_packet           # noqa: E402

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not installed — run: pip install anthropic")

_MODEL          = "claude-sonnet-4-6"
_MAX_TOKENS     = 4096   # Round 1: bull/bear independent positions
_MAX_TOKENS_R2  = 16384  # Round 2: rebuttals must respond to every opposing argument
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

    try:
        return json.loads(raw), raw
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
    parsed, raw = _invoke_llm(client, system_prompt, brief, label, max_tokens)
    if parsed is not None:
        return parsed
    return {
        "analyst_role":          label.lower().split()[0],
        "summary":               raw[:500],
        "key_arguments":         [],
        "evidence_cited":        [],
        "contested_items":       [],
        "raised_risks":          [],
        "learning_hooks":        [],
        "score_adjustment":      0.0,
        "confidence_adjustment": 0.0,
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

    # ── Write output ──────────────────────────────────────────────────────────
    date_tag = scoring.get("scored_at", "")[:10].replace("-", "") or args.date or "unknown"
    out_path = _write_debate(debate_dict, args.ticker, date_tag)
    print(f"\n  written: {out_path.relative_to(_REPO_ROOT)}")

    _print_summary(debate_dict)


if __name__ == "__main__":
    main()
