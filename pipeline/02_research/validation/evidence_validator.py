"""
evidence_validator.py
Validates evidence items by verifying verbatim quote presence in raw source text.

Entry point:
    validate_evidence(items: list[dict], transcript: dict) -> list[dict]

Verified items are enriched with:
    context_before, context_after, source_span, extraction_confidence, possibly_truncated

Unverifiable items are excluded from output and written to:
    validation/review_queue/{ticker}_{timestamp}.json
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("evidence_validator")

_REVIEW_QUEUE  = Path(__file__).resolve().parent / "review_queue"
_CONTEXT_WORDS = 50


# ─────────────────────────────────────────────
# TEXT HELPERS
# ─────────────────────────────────────────────

def _words_before(text: str, char_pos: int, n: int) -> str:
    words = text[:char_pos].split()
    return " ".join(words[-n:])


def _words_after(text: str, char_pos: int, n: int) -> str:
    words = text[char_pos:].split()
    return " ".join(words[:n])


def _find_verbatim(quote: str, raw: str) -> tuple:
    """
    Case-insensitive verbatim search; falls back to flexible whitespace matching.
    Returns (char_start, char_end) or (None, None).
    """
    m = re.search(re.escape(quote.strip()), raw, re.I)
    if m:
        return m.start(), m.end()

    # Flexible: treat any whitespace sequence as \\s+
    flex = r"\s+".join(re.escape(w) for w in quote.split())
    m = re.search(flex, raw, re.I)
    if m:
        return m.start(), m.end()

    return None, None


# ─────────────────────────────────────────────
# REVIEW QUEUE
# ─────────────────────────────────────────────

def _write_review_queue(ticker: str, items: list) -> None:
    _REVIEW_QUEUE.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = _REVIEW_QUEUE / f"{ticker}_{ts}.json"
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Review queue written: %s (%d items)", path.name, len(items))


# ─────────────────────────────────────────────
# PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def validate_evidence(items: list, transcript: dict) -> list:
    """
    Validate each evidence item against the raw transcript text.

    Args:
        items:      Evidence dicts from extract_quotes() or extract_contradictions().
        transcript: dict from fetch_transcript() — must include raw_text and ticker.

    Returns:
        Validated items enriched with context/span fields. Unverifiable items excluded.
    """
    raw_text = transcript.get("raw_text", "")
    ticker   = transcript.get("ticker", "UNKNOWN")

    if not raw_text:
        log.warning("%s: no raw_text for validation — returning items unmodified", ticker)
        return items

    validated    = []
    review_items = []

    for item in items:
        # Determine which field holds the primary quote to verify
        quote_text = (item.get("quote_text") or item.get("current_quote") or "").strip()

        # Items without a searchable quote (e.g. contradiction items with null prior_quote)
        # pass through without enrichment
        if not quote_text:
            validated.append(item)
            continue

        char_start, char_end = _find_verbatim(quote_text, raw_text)

        if char_start is not None:
            truncated = char_end >= len(raw_text) - 50
            enriched  = dict(item)
            enriched.update({
                "context_before":        _words_before(raw_text, char_start, _CONTEXT_WORDS),
                "context_after":         _words_after(raw_text, char_end,   _CONTEXT_WORDS),
                "source_span":           [char_start, char_end],
                "extraction_confidence": "high",
                "possibly_truncated":    truncated,
            })
            validated.append(enriched)
        else:
            log.info(
                "%s: quote not found verbatim (cat=%s) — queued for review",
                ticker, item.get("category", "?"),
            )
            review_items.append({
                "ticker":   ticker,
                "category": item.get("category", ""),
                "content":  quote_text,
                "reason":   "verbatim_not_found",
                "item":     item,
            })

    if review_items:
        _write_review_queue(ticker, review_items)

    log.info(
        "%s: validation — %d passed, %d queued for review",
        ticker, len(validated), len(review_items),
    )
    return validated
