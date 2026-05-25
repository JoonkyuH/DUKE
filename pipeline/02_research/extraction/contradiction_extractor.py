"""
contradiction_extractor.py
Identifies tone shifts and contradictions between current and prior quarter.

Entry point:
    extract_contradictions(ticker: str, current: dict) -> list[dict]

Skips gracefully if no prior quarter transcript is in transcript_cache.
Each evidence item includes:
    change_type, current_quote, prior_quote, category,
    direction, significance, explanation,
    current_period, prior_period,
    source_type, source_url, fiscal_year, fiscal_quarter,
    reliability, prompt_name, prompt_version, ticker
"""

import logging
import re
import sqlite3
import sys
from pathlib import Path

log = logging.getLogger("contradiction_extractor")

_REPO_ROOT   = Path(__file__).resolve().parent.parent.parent.parent
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_DB_PATH     = Path(__file__).resolve().parent.parent / "acquisition" / "cache" / "duke_cache.db"

sys.path.insert(0, str(_REPO_ROOT))


def _load_prompt(name: str) -> dict:
    """Parse a YAML prompt file without external dependencies."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8")

    name_m    = re.search(r"^name:\s*(.+)$",             content, re.M)
    version_m = re.search(r'^version:\s*"?([^"\n]+)"?',  content, re.M)

    prompt_start = re.search(r"^prompt:\s*\|", content, re.M)
    if not prompt_start:
        raise ValueError(f"No 'prompt: |' block found in {path}")

    after = content[prompt_start.end():]
    if after.startswith("\n"):
        after = after[1:]

    end_m = re.search(r"\n(?=[a-zA-Z])", after)
    if end_m:
        after = after[: end_m.start()]

    lines   = after.split("\n")
    indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    indent  = min(indents) if indents else 0
    prompt_text = "\n".join(l[indent:] if len(l) > indent else l for l in lines).strip()

    return {
        "name":    name_m.group(1).strip()    if name_m    else name,
        "version": version_m.group(1).strip() if version_m else "1.0.0",
        "prompt":  prompt_text,
    }


def _get_prior_transcript(ticker: str, current_fy: str, current_fq: str):
    """Return the most recent cached transcript that is not the current period."""
    try:
        con = sqlite3.connect(str(_DB_PATH))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM transcript_cache WHERE ticker = ? "
            "ORDER BY fiscal_year DESC, fiscal_quarter DESC",
            (ticker.upper(),),
        ).fetchall()
        con.close()
    except Exception as exc:
        log.debug("DB lookup failed for %s: %s", ticker, exc)
        return None

    current_key = f"{current_fy}_{current_fq}"
    for row in rows:
        if f"{row['fiscal_year']}_{row['fiscal_quarter']}" != current_key:
            return row
    return None


def _unwrap(response, ticker: str, envelope_keys: tuple):
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in envelope_keys:
            if isinstance(response.get(key), list):
                return response[key]
        log.warning("%s: unexpected contradiction response keys: %s", ticker, list(response.keys()))
        return None
    log.warning("%s: non-list/dict LLM response", ticker)
    return None


def extract_contradictions(ticker: str, current: dict) -> list:
    """
    Compare current quarter transcript against the prior quarter.

    Args:
        ticker:  Stock ticker symbol.
        current: dict from fetch_transcript() for the current period.

    Returns:
        List of contradiction evidence item dicts, or [] if no prior data.
    """
    from common.llm import get_client

    fiscal_year    = current.get("fiscal_year", "")
    fiscal_quarter = current.get("fiscal_quarter", "")
    current_text   = current.get("raw_text", "")
    source_type    = current.get("source_type", "")
    source_url     = current.get("source_url", "")
    reliability    = current.get("reliability", 0.75)

    if not current_text:
        log.warning("%s: no current text — skipping contradiction extraction", ticker)
        return []

    prior_row = _get_prior_transcript(ticker, fiscal_year, fiscal_quarter)
    if not prior_row:
        log.info("%s: no prior quarter in cache — skipping", ticker)
        return []

    prior_fy   = prior_row["fiscal_year"]
    prior_fq   = prior_row["fiscal_quarter"]
    prior_text = prior_row["raw_text"] or ""

    if not prior_text:
        log.info("%s: prior quarter text empty — skipping", ticker)
        return []

    log.info("%s: comparing %s %s vs %s %s",
             ticker, fiscal_quarter, fiscal_year, prior_fq, prior_fy)

    prompt_def = _load_prompt("contradiction_detector")
    filled = prompt_def["prompt"].format(
        company=ticker,
        current_period=f"{fiscal_quarter} {fiscal_year}",
        prior_period=f"{prior_fq} {prior_fy}",
        current_text=current_text[:60_000],
        prior_text=prior_text[:60_000],
    )

    try:
        client       = get_client("extraction")
        raw_response = client.structured_generate(
            prompt=filled,
            system=(
                "You are a financial analyst identifying material changes between earnings periods. "
                "Return a JSON array and nothing else."
            ),
        )
    except Exception as exc:
        log.error("%s: LLM call failed: %s", ticker, exc)
        return []

    raw_items = _unwrap(raw_response, ticker,
                        ("contradictions", "items", "results", "data"))
    if raw_items is None:
        return []

    from quote_extractor import _evidence_id

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        change_type = item.get("change_type", "").strip()
        if not change_type:
            continue
        current_quote = item.get("current_quote", "")
        significance = item.get("significance", "MEDIUM")
        items.append({
            "evidence_id":    _evidence_id(ticker, source_url, current_quote),
            "change_type":    change_type,
            "current_quote":  current_quote,
            "prior_quote":    item.get("prior_quote"),
            "category":       item.get("category", ""),
            "direction":      item.get("direction", "NEUTRAL"),
            "significance":   significance,
            "severity":       significance.lower(),
            "resolution":     "unresolved",
            "explanation":    item.get("explanation", ""),
            "current_period": f"{fiscal_quarter} {fiscal_year}",
            "prior_period":   f"{prior_fq} {prior_fy}",
            "source_type":    source_type,
            "source_url":     source_url,
            "fiscal_year":    fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            "reliability":    reliability,
            "prompt_name":    prompt_def["name"],
            "prompt_version": prompt_def["version"],
            "ticker":         ticker.upper(),
        })

    log.info("%s: found %d contradictions/shifts", ticker, len(items))
    return items
