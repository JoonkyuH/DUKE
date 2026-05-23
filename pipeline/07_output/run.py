#!/usr/bin/env python3
"""
run.py — Stage 07 (Output) orchestration bridge.

Usage:
    python3 run.py TICKER [--date YYYYMMDD]

If --date is omitted, the most recent synthesis file for TICKER is used.

Loads:
    data/synthesis/{TICKER}_synthesis_{date}.json   Stage 06 output

Flow:
    1. Load synthesis file — extract chief_analyst_output and synthesis metadata
    2. call capture_decision() — formats and prints the recommendation, shows
       sizing guidance and portfolio context, prompts for investor inputs,
       writes the initial decision record to data/journal/
    3. Forward learning_hooks from the Stage 06 synthesis top-level into the
       record (labelled {"source": "bull"/"bear", "hook": "..."} format),
       overwriting the raw-string extraction done internally by capture_decision
    4. Write the updated record to data/journal/ (overwrites)
    5. Print confirmation: path, ticker, date, action

Writes:
    data/journal/DEC-{TICKER}-{YYYYMMDD}.json
"""

import argparse
import glob
import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
# Must be in sys.path before importing siblings so that decision_capture.py's
# own top-level "import formatter" and "import journal" resolve correctly.
sys.path.insert(0, str(_THIS_DIR))

import decision_capture  # noqa: E402
import journal            # noqa: E402

_REPO_ROOT = _THIS_DIR.parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# FILE LOADING
# ─────────────────────────────────────────────────────────────────────────────

def _find_latest(pattern: str) -> Path:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file found: {pattern}")
    return Path(matches[-1])


def _load_synthesis(ticker: str, date_str: str | None) -> tuple[dict, str]:
    base    = str(_REPO_ROOT / "data" / "synthesis")
    pattern = f"{base}/{ticker}_synthesis_{date_str or '*'}.json"
    path    = _find_latest(pattern)
    with open(path) as f:
        data = json.load(f)
    # Extract date tag from filename: {TICKER}_synthesis_{date}.json
    date_tag = path.stem.split("_synthesis_")[-1]
    return data, date_tag


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 07 Output — decision capture")
    parser.add_argument("ticker", type=str.upper)
    parser.add_argument(
        "--date", default=None,
        help="YYYYMMDD — defaults to most recent synthesis file for TICKER",
    )
    args = parser.parse_args()

    # ── Load synthesis file ───────────────────────────────────────────────────
    synthesis, date_tag = _load_synthesis(args.ticker, args.date)

    chief_analyst_output = synthesis.get("chief_analyst_output", {})
    if not chief_analyst_output:
        sys.exit(
            f"  ERROR: no chief_analyst_output in synthesis file for {args.ticker}.\n"
            "  Run Stage 06 (pipeline/06_synthesis/run.py) first."
        )

    # Pass the full synthesis dict as synthesis_output — formatter.py and
    # decision_capture.py read ticker, company_name, debate_outcome,
    # overall_risk_assessment, scores, metadata, chief_analyst_brief from it.
    synthesis_output = synthesis

    # ── Interactive decision capture ──────────────────────────────────────────
    # capture_decision:
    #   1. Formats and prints the DUKE recommendation report
    #   2. Shows sizing guidance (with risk/fit downgrades)
    #   3. Shows portfolio context if data/raw/portfolio/latest.csv exists
    #   4. Prompts for: action, position_size_pct, conviction_1_to_10,
    #      override_recommendation, override_reason, notes
    #   5. Writes the initial decision record to data/journal/
    #   6. Returns the record dict
    record = decision_capture.capture_decision(chief_analyst_output, synthesis_output)

    # ── Forward Stage 06 learning_hooks ──────────────────────────────────────
    # capture_decision._extract_learning_hooks() pulls raw hook strings from
    # the chief_analyst_brief. Stage 06 stores labelled hooks at the top level
    # of the synthesis file: [{"source": "bull"/"bear", "hook": "..."}].
    # Overwrite with the labelled format so the journal entry used by the
    # 90/180/365-day outcome tracker has source provenance.
    stage06_hooks = synthesis.get("learning_hooks", [])
    if stage06_hooks:
        record["learning_hooks"] = stage06_hooks
        journal.write_decision_record(record)

    # ── Confirmation ──────────────────────────────────────────────────────────
    ticker   = record.get("ticker", args.ticker)
    dec_date = record.get("date", "—")
    action   = record.get("action", "—")
    n_hooks  = len(record.get("learning_hooks", []))

    journal_path = journal.JOURNAL_DIR / f"DEC-{ticker}-{dec_date.replace('-', '')}.json"
    print(f"  Journal: {journal_path.relative_to(_REPO_ROOT)}")
    print(f"  ticker={ticker}  date={dec_date}  action={action}  "
          f"learning_hooks={n_hooks}")
    print()


if __name__ == "__main__":
    main()
