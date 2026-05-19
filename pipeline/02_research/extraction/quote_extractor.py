"""
quote_extractor.py
Extracts attributed executive quotes from earnings documents.

Entry point:
    extract_quotes(transcript: dict) -> list[dict]

Each evidence item includes:
    quote_text, quote_type, speaker, speaker_confidence,
    category, direction, significance,
    source_type, source_url, document_subtype,
    fiscal_year, fiscal_quarter, reliability,
    prompt_name, prompt_version, ticker
"""

import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("quote_extractor")

_REPO_ROOT   = Path(__file__).resolve().parent.parent.parent.parent
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

sys.path.insert(0, str(_REPO_ROOT))


def _load_prompt(name: str) -> dict:
    """Parse a YAML prompt file without external dependencies."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    content = path.read_text(encoding="utf-8")

    name_m    = re.search(r"^name:\s*(.+)$",              content, re.M)
    version_m = re.search(r'^version:\s*"?([^"\n]+)"?',   content, re.M)

    prompt_start = re.search(r"^prompt:\s*\|", content, re.M)
    if not prompt_start:
        raise ValueError(f"No 'prompt: |' block found in {path}")

    after = content[prompt_start.end():]
    if after.startswith("\n"):
        after = after[1:]

    # Stop at next top-level YAML key
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


def extract_quotes(transcript: dict) -> list:
    """
    Extract structured quotes from a transcript or press release dict.

    Args:
        transcript: dict from fetch_transcript(). Must include raw_text.

    Returns:
        List of evidence item dicts, one per extracted quote.
    """
    from common.llm import get_client

    raw_text         = transcript.get("raw_text", "")
    ticker           = transcript.get("ticker", "UNKNOWN")
    fiscal_year      = transcript.get("fiscal_year", "")
    fiscal_quarter   = transcript.get("fiscal_quarter", "")
    source_type      = transcript.get("source_type", "")
    source_url       = transcript.get("source_url", "")
    reliability      = transcript.get("reliability", 0.75)
    document_subtype = transcript.get("document_subtype", "") or source_type

    if not raw_text:
        log.warning("%s: empty raw_text — nothing to extract", ticker)
        return []

    prompt_def = _load_prompt("quote_extractor")
    period     = f"{fiscal_quarter} {fiscal_year}".strip()

    filled = prompt_def["prompt"].format(
        document_subtype=document_subtype,
        company=ticker,
        period=period,
        text=raw_text[:100_000],
    )

    try:
        client       = get_client("extraction")
        raw_response = client.structured_generate(
            prompt=filled,
            system=(
                "You are a financial analyst extracting verbatim executive quotes. "
                "Return a JSON array and nothing else."
            ),
        )
    except Exception as exc:
        log.error("%s: LLM call failed: %s", ticker, exc)
        return []

    raw_quotes = _unwrap(raw_response, ticker, ("quotes", "items", "results", "data"))
    if raw_quotes is None:
        return []

    items = []
    for q in raw_quotes:
        if not isinstance(q, dict):
            continue
        quote_text = (q.get("quote_text") or "").strip()
        if not quote_text:
            continue
        items.append({
            "quote_text":          quote_text,
            "quote_type":          "direct",
            "speaker":             q.get("speaker") or "Management",
            "speaker_confidence":  float(q.get("speaker_confidence", 0.50)),
            "category":            q.get("category", ""),
            "direction":           q.get("direction", "NEUTRAL"),
            "significance":        q.get("significance", "MEDIUM"),
            "source_type":         source_type,
            "source_url":          source_url,
            "fiscal_year":         fiscal_year,
            "fiscal_quarter":      fiscal_quarter,
            "reliability":         reliability,
            "prompt_name":         prompt_def["name"],
            "prompt_version":      prompt_def["version"],
            "document_subtype":    document_subtype,
            "ticker":              ticker,
        })

    log.info("%s: extracted %d quotes", ticker, len(items))
    return items


def _unwrap(response, ticker: str, envelope_keys: tuple):
    """Return a list from a raw LLM response (list or dict envelope)."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in envelope_keys:
            if isinstance(response.get(key), list):
                return response[key]
        log.warning("%s: unexpected LLM response keys: %s", ticker, list(response.keys()))
        return None
    log.warning("%s: non-list/dict LLM response", ticker)
    return None
