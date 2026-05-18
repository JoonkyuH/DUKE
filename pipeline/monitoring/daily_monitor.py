#!/usr/bin/env python3
"""
daily_monitor.py
Morning digest for open investment positions.

Run from the repo root or the monitoring directory:
  python3 pipeline/monitoring/daily_monitor.py

Flow:
  1. Load all DEC-*.json journal records where action = "enter"
     and no matching POST-*.json postmortem exists (open positions).
  2. For each open position, query Perplexity with a structured prompt
     covering the position's what_would_change_this and monitoring_priorities.
  3. Parse the JSON response and print a terminal digest with HIGH PRIORITY
     flags for thesis_status=flag or what_would_change_progress=met.
  4. Write the full digest to data/journal/monitoring/{YYYYMMDD}.json.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# Journal module lives in pipeline/07_output/
sys.path.insert(0, str(REPO / "pipeline" / "07_output"))
# LLM client lives in common/
sys.path.insert(0, str(REPO / "common"))

from journal import read_journal, JOURNAL_DIR  # noqa: E402
import llm_client                              # noqa: E402

MONITOR_DIR = JOURNAL_DIR / "monitoring"


# ─────────────────────────────────────────────
# POSITION LOADING
# ─────────────────────────────────────────────

def load_open_positions() -> list:
    """
    Return decision records where action='enter' and no postmortem exists.

    If multiple DEC records exist for the same ticker (re-entry after exit),
    the most recent one (last alphabetically by filename) is used, provided
    the position is still open.
    """
    records = read_journal()

    # Tickers with any postmortem are considered closed
    closed_tickers = {
        r["ticker"]
        for r in records
        if r.get("_filename", "").startswith("POST-") and "ticker" in r
    }

    # Keep the most-recent DEC per ticker where action = "enter"
    # read_journal() returns records sorted by filename (DEC sorts before OUT/POST,
    # then alphabetically by ticker, then by date), so iterating and overwriting
    # yields the latest entry per ticker.
    open_positions: dict = {}
    for r in records:
        fname = r.get("_filename", "")
        if not fname.startswith("DEC-"):
            continue
        if r.get("action") != "enter":
            continue
        ticker = r.get("ticker")
        if not ticker or ticker in closed_tickers:
            continue
        if "_error" in r:
            continue
        open_positions[ticker] = r

    return list(open_positions.values())


# ─────────────────────────────────────────────
# PROMPT ASSEMBLY
# ─────────────────────────────────────────────

def _build_prompt(position: dict) -> str:
    ticker  = position["ticker"]
    company = position.get("company_name") or ticker
    wwct    = position.get("what_would_change_this") or "Not specified."
    prios   = position.get("monitoring_priorities") or []

    if prios:
        prios_text = "\n".join(
            f"  {p.get('priority', '?')}. {p.get('description', '')} "
            f"(source: {p.get('source', '?')}, frequency: {p.get('frequency', '?')})"
            for p in prios
        )
    else:
        prios_text = "  None specified."

    return f"""You are monitoring an active investment position for a disciplined long-term investor.

Ticker: {ticker} ({company})

What would change this thesis (conditions that would trigger a recommendation change):
{wwct}

Monitoring priorities:
{prios_text}

Question: Has any news or market development in the last 24 hours materially affected the investment thesis for {ticker}?

Specifically evaluate:
(a) Has anything moved any monitoring priority closer to triggering?
(b) Has anything addressed the what_would_change_this conditions — making entry or exit more likely?
(c) Are there any new material risks not already covered by the monitoring priorities?

Return ONLY a valid JSON object with this exact structure — no prose, no markdown fencing, no explanation outside the JSON:
{{
  "thesis_status": "intact",
  "relevant_news": [],
  "tic_impacts": [],
  "what_would_change_progress": "none",
  "new_risks": []
}}

Field rules:
- thesis_status: "flag" if any news materially threatens the thesis or meets an exit condition; "developing" if noteworthy but not immediately actionable; "intact" if nothing material occurred in the last 24 hours
- relevant_news: list of plain-English strings, one per relevant news item; empty list if none
- tic_impacts: list of plain-English strings describing how news affects specific monitoring priorities; empty list if none
- what_would_change_progress: "met" if a stated what_would_change condition is now fully satisfied; "partial" if it is developing toward being met; "none" if no progress
- new_risks: list of new material risks not already in the monitoring priorities; empty list if none"""


# ─────────────────────────────────────────────
# RESPONSE PARSING
# ─────────────────────────────────────────────

def _parse_response(content: str) -> dict:
    """Strip markdown fencing and parse JSON from a Perplexity response."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence (```json or ```) and closing fence (```)
        start = 1
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text  = "\n".join(lines[start:end])
    return json.loads(text)


# ─────────────────────────────────────────────
# PER-POSITION CHECK
# ─────────────────────────────────────────────

def _check_position(position: dict) -> dict:
    """Query Perplexity for one open position. Returns a normalized result dict."""
    ticker = position["ticker"]
    base = {
        "ticker":                     ticker,
        "company_name":               position.get("company_name", ""),
        "entry_date":                 position.get("date", ""),
        "conviction_at_entry":        position.get("conviction_1_to_10"),
        "position_size_pct":          position.get("position_size_pct"),
        "thesis_status":              "unknown",
        "relevant_news":              [],
        "tic_impacts":                [],
        "what_would_change_progress": "none",
        "new_risks":                  [],
        "error":                      None,
    }
    try:
        prompt  = _build_prompt(position)
        content = llm_client.call_perplexity(prompt, max_tokens=1024)
        parsed  = _parse_response(content)
        base.update({
            "thesis_status":              parsed.get("thesis_status", "intact"),
            "relevant_news":              parsed.get("relevant_news", []),
            "tic_impacts":                parsed.get("tic_impacts", []),
            "what_would_change_progress": parsed.get("what_would_change_progress", "none"),
            "new_risks":                  parsed.get("new_risks", []),
        })
    except Exception as exc:
        base["error"] = str(exc)
    return base


# ─────────────────────────────────────────────
# TERMINAL OUTPUT
# ─────────────────────────────────────────────

_BOLD  = "\033[1m"
_DIM   = "\033[2m"
_RED   = "\033[31m"
_RESET = "\033[0m"
_SEP   = "─" * 72
_DIV   = "=" * 72


def _print_digest(now: datetime, results: list) -> None:
    timestamp = now.strftime("%Y-%m-%d  %H:%M UTC")
    n_flag = sum(1 for r in results
                 if r.get("thesis_status") == "flag"
                 or r.get("what_would_change_progress") == "met")

    print(f"\n{_DIV}")
    print(f"  {_BOLD}DUKE MORNING MONITOR{_RESET}  —  {timestamp}")
    print(f"  {len(results)} open position(s)  |  {n_flag} HIGH PRIORITY")
    print(_DIV)

    for r in results:
        ticker   = r["ticker"]
        company  = r.get("company_name", "")
        status   = r.get("thesis_status", "unknown")
        progress = r.get("what_would_change_progress", "none")
        error    = r.get("error")
        high_pri = status == "flag" or progress == "met"

        print(f"\n  {_SEP}")

        if high_pri:
            print(f"  {_BOLD}{_RED}!! HIGH PRIORITY{_RESET}  "
                  f"{_BOLD}{ticker}{_RESET}  {company}")
        else:
            label = f"{ticker}  {company}".strip()
            entry = r.get("entry_date", "—")
            print(f"  {_BOLD}{label}{_RESET}  |  entered {entry}")

        if error:
            print(f"  {_RED}ERROR:{_RESET} {error}")
            continue

        status_display = {
            "flag":      f"{_RED}FLAG — REVIEW REQUIRED{_RESET}",
            "developing": "DEVELOPING",
            "intact":    "INTACT",
        }.get(status, status.upper())
        print(f"  Thesis status: {_BOLD}{status_display}{_RESET}")

        news = r.get("relevant_news", [])
        if news:
            print("  Relevant news:")
            for item in news:
                print(f"    • {item}")

        tic_impacts = r.get("tic_impacts", [])
        if tic_impacts:
            print("  Monitoring priority impacts:")
            for item in tic_impacts:
                print(f"    ⚠ {item}")

        if progress != "none":
            prog_label = f"{_BOLD}{progress.upper()}{_RESET}"
            print(f"  What-would-change progress: {prog_label}")

        new_risks = r.get("new_risks", [])
        if new_risks:
            print("  New risks:")
            for item in new_risks:
                print(f"    → {item}")

        if not news and not tic_impacts and not new_risks:
            print(f"  {_DIM}No material developments in the last 24 hours.{_RESET}")

    print(f"\n  {_SEP}\n")


# ─────────────────────────────────────────────
# DIGEST PERSISTENCE
# ─────────────────────────────────────────────

def _write_digest(now: datetime, results: list) -> str:
    MONITOR_DIR.mkdir(parents=True, exist_ok=True)
    filename = now.strftime("%Y%m%d") + ".json"
    path = MONITOR_DIR / filename
    digest = {
        "date":             now.strftime("%Y-%m-%d"),
        "run_at":           now.isoformat(),
        "position_count":   len(results),
        "high_priority_count": sum(
            1 for r in results
            if r.get("thesis_status") == "flag"
            or r.get("what_would_change_progress") == "met"
        ),
        "positions": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)
    return str(path)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)

    positions = load_open_positions()

    if not positions:
        print(f"\n  DUKE MORNING MONITOR  —  {now.strftime('%Y-%m-%d')}")
        print("  No open positions to monitor.\n")
        return

    print(f"  Checking {len(positions)} open position(s) via Perplexity…\n")
    results = [_check_position(p) for p in positions]

    _print_digest(now, results)

    path = _write_digest(now, results)
    print(f"  Digest written → {path}\n")


if __name__ == "__main__":
    main()
