"""
run_moderator_only.py — Test harness for the Debate Moderator.

Loads existing debate records, strips self-scores, calls the Moderator, applies
the code-side lean derivation, and prints — WITHOUT writing anything.

The point: inspect the Moderator's verdicts on real (already-debated) tickers
before any Stage 05 re-run and before any decision path is rewired to consume
the Moderator output. If the Moderator clusters at 5/5 balanced, the prompt is
hedging and we fix it before touching debate_scorer.py / synthesizer.py /
chief_analyst.md.

Usage:
    source ~/.zprofile && cd pipeline/05_debate && \\
        python3 run_moderator_only.py VRT BSX CRM NVDA PODD PTC

Optional --date YYYYMMDD pins to a specific debate file per ticker; otherwise
the most recent file is used.
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

_THIS_DIR  = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent

try:
    import anthropic
except ImportError:
    sys.exit("anthropic SDK not installed — run: pip install anthropic")

_MOD_MODEL      = "claude-sonnet-4-6"
_MOD_MAX_TOKENS = 8192


def _load_debate(ticker: str, date_str: str | None) -> tuple[dict, str]:
    base    = str(_REPO_ROOT / "data" / "debate")
    pattern = f"{base}/{ticker}_debate_{date_str or '*'}.json"
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No debate file for {ticker} matching {pattern}")
    path = Path(matches[-1])
    return json.load(open(path)), path.name


def _build_moderator_brief(debate_dict: dict) -> dict:
    """
    Build the Moderator input from a debate record. STRIPS self-scores from both
    positions and both rebuttals — the Moderator must not see them.
    """
    bull = debate_dict.get("bull_position") or {}
    bear = debate_dict.get("bear_position") or {}
    bull_r2 = debate_dict.get("bull_rebuttal") or {}
    bear_r2 = debate_dict.get("bear_rebuttal") or {}
    contentions = debate_dict.get("contentions") or []

    def _strip_scores(d: dict) -> dict:
        """Drop self-score fields. Defensive copy."""
        out = {k: v for k, v in d.items()
               if k not in ("score_adjustment", "confidence_adjustment")}
        return out

    return {
        "ticker":       debate_dict.get("ticker"),
        "company_name": debate_dict.get("company_name"),
        "instructions": (
            "You are the Debate Moderator. Read both positions, both rebuttals, "
            "and the contentions. Allocate exactly 10 points between bull and "
            "bear based on grounded surviving evidence — not advocacy volume. "
            "Return the JSON structure specified in the system prompt."
        ),
        "bull_position": _strip_scores(bull),
        "bear_position": _strip_scores(bear),
        "bull_rebuttal": _strip_scores(bull_r2),
        "bear_rebuttal": _strip_scores(bear_r2),
        "contentions":   contentions,
    }


def _invoke_moderator(
    client: anthropic.Anthropic,
    system_prompt: str,
    brief: dict,
) -> tuple[dict | None, str]:
    """
    Single LLM call. Uses raw_decode to tolerate trailing prose (same parser
    pattern as Stage 05's _invoke_llm). Returns (parsed_dict_or_None, raw_text).
    """
    user_msg = (
        "Here is the completed debate. Judge the evidence asymmetry and return "
        "the JSON object specified in your system prompt.\n\n"
        + json.dumps(brief, indent=2, default=str)
    )
    resp = client.messages.create(
        model=_MOD_MODEL,
        max_tokens=_MOD_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        start = 1
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        raw   = "\n".join(lines[start:end])
    start_idx = raw.find("{")
    if start_idx < 0:
        return None, raw
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw, start_idx)
        return obj, raw
    except json.JSONDecodeError:
        return None, raw


def derive_lean(bull: float | None, bear: float | None) -> tuple[str | None, float]:
    """
    Code-side lean derivation. Normalises the LLM's two scores to sum-10, then
    applies the +/-1.0 epsilon band. This makes `balanced` mechanically
    expensive — the LLM cannot decide its own balanced label.

    Returns (lean, signed_margin). margin = bull - bear (after normalisation).
    """
    total = (bull or 0) + (bear or 0)
    if total <= 0:
        return None, 0.0
    b = 10.0 * (bull or 0) / total
    r = 10.0 * (bear or 0) / total
    margin = round(b - r, 2)
    # Epsilon band: balanced only when scores are within 0.5 of each other.
    # Kept in sync with the live derive_lean in run.py.
    if abs(margin) <= 0.5:
        return "balanced", margin
    return ("bull_leans" if margin > 0 else "bear_leans"), margin


def _print_result(ticker: str, debate_file: str, parsed: dict | None, raw: str):
    print(f"\n{'='*70}")
    print(f"  TICKER: {ticker}   debate file: {debate_file}")
    print('='*70)
    if parsed is None:
        print("  *** MODERATOR PARSE FAILED ***")
        print(f"  raw (first 400 chars):\n    {raw[:400]}")
        return

    bull = parsed.get("bull_evidence_score")
    bear = parsed.get("bear_evidence_score")
    llm_lean = parsed.get("lean")
    decisive = parsed.get("decisive_evidence") or ""
    reasoning = parsed.get("reasoning") or ""
    contention_calls = parsed.get("contention_calls") or []

    lean, margin = derive_lean(bull, bear)

    print(f"  bull_evidence_score : {bull}")
    print(f"  bear_evidence_score : {bear}")
    print(f"  margin              : {margin:+.2f}   (derived from normalised scores)")
    print(f"  lean (code-derived) : {lean}")
    print(f"  lean (LLM reported) : {llm_lean}")
    if llm_lean != lean:
        print(f"    ^^ LLM disagrees with code-derived lean (code wins by design)")
    print(f"  decisive_evidence   : {decisive[:200]}")
    print(f"  reasoning           : {reasoning[:300]}")
    if contention_calls:
        print(f"  contention_calls    :")
        for c in contention_calls:
            print(f"    - {c.get('contention_id')}: favored={c.get('favored')}  basis={(c.get('basis') or '')[:100]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Moderator harness — read-only")
    parser.add_argument("tickers", nargs="+", type=str.upper)
    parser.add_argument("--date", default=None, help="YYYYMMDD; defaults to most recent debate per ticker")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set in environment")
    client = anthropic.Anthropic(api_key=api_key)

    with open(_THIS_DIR / "prompts" / "debate_moderator.md") as f:
        system_prompt = f.read()

    for t in args.tickers:
        try:
            debate_dict, fname = _load_debate(t, args.date)
        except FileNotFoundError as e:
            print(f"\n{t}: {e}")
            continue

        # If the debate is invalid (parse-failed R1), the Moderator has nothing
        # to judge — skip it cleanly rather than feed garbage in.
        if debate_dict.get("debate_invalid") or debate_dict.get("outcome") == "not_computable":
            print(f"\n{t}: debate is marked debate_invalid / not_computable — skipping.")
            continue

        brief = _build_moderator_brief(debate_dict)
        print(f"  calling Moderator for {t}...", flush=True)
        parsed, raw = _invoke_moderator(client, system_prompt, brief)
        _print_result(t, fname, parsed, raw)


if __name__ == "__main__":
    main()
