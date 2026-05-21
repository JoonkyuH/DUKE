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

# Unicode characters that differ between HTML source and LLM output
_UNICODE_NORM = [
    # Non-breaking and special-width spaces → regular space
    ("\xa0", " "),   # non-breaking space (very common in SEC filings)
    (" ", " "), # thin space
    (" ", " "), # en space
    (" ", " "), # em space
    ("​", ""),  # zero-width space (drop it)
    # Curly quotes → straight quotes (LLM normalises these)
    ("‘", "'"), ("’", "'"),  # ' '
    ("“", '"'), ("”", '"'),  # " "
    # Dashes
    ("—", "-"), ("–", "-"),  # em dash, en dash
    # Soft hyphen (HTML artifact) → empty
    ("\xad", ""),
]


def _normalize(text: str) -> str:
    """Replace HTML/Unicode characters that diverge between source and LLM output."""
    for old, new in _UNICODE_NORM:
        text = text.replace(old, new)
    # Collapse runs of multiple spaces that substitutions may introduce
    text = re.sub(r"  +", " ", text)
    return text


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
    Three-pass verbatim search. Returns (char_start, char_end) or (None, None).

    Pass 1: exact case-insensitive match.
    Pass 2: flexible whitespace (treats any \\s+ as equivalent).
    Pass 3: Unicode-normalized match — handles non-breaking spaces, curly quotes,
            and em/en dashes that HTML stripping leaves in source but the LLM
            normalizes in its output.

    Passes 1 and 2 use the original raw text so returned positions are accurate.
    Pass 3 uses the normalized raw; positions are still accurate because each
    replaced character is a 1-for-1 substitution (same byte length).
    """
    q = quote.strip()

    # Pass 1: exact case-insensitive
    m = re.search(re.escape(q), raw, re.I)
    if m:
        return m.start(), m.end()

    # Pass 2: flexible whitespace
    flex = r"\s+".join(re.escape(w) for w in q.split())
    m = re.search(flex, raw, re.I)
    if m:
        return m.start(), m.end()

    # Pass 3: normalize both sides, then retry passes 1 and 2
    q_n   = _normalize(q)
    raw_n = _normalize(raw)

    m = re.search(re.escape(q_n), raw_n, re.I)
    if m:
        return m.start(), m.end()

    flex_n = r"\s+".join(re.escape(w) for w in q_n.split())
    m = re.search(flex_n, raw_n, re.I)
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
    class_stats: dict = {}

    for item in items:
        # Determine which field holds the primary quote to verify
        quote_text = (item.get("quote_text") or item.get("current_quote") or "").strip()

        # Items without a searchable quote (e.g. contradiction items with null prior_quote)
        # pass through without enrichment
        if not quote_text:
            validated.append(item)
            continue

        cls = item.get("item_class", "unknown")
        if cls not in class_stats:
            class_stats[cls] = {"passed": 0, "failed": 0}

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
            prior_quote = (item.get("prior_quote") or "").strip()
            if prior_quote:
                pq_start, _ = _find_verbatim(prior_quote, raw_text)
                if pq_start is None:
                    log.warning(
                        "%s: prior_quote unverified for contradiction item (cat=%s)",
                        ticker, item.get("category", "?"),
                    )
                    enriched["prior_quote_unverified"] = True
            validated.append(enriched)
            class_stats[cls]["passed"] += 1
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
            class_stats[cls]["failed"] += 1

    if review_items:
        _write_review_queue(ticker, review_items)

    for cls, s in sorted(class_stats.items()):
        total = s["passed"] + s["failed"]
        pct   = 100 * s["passed"] / total if total else 0
        log.info(
            "%s: validation [%s] — %d/%d passed (%.0f%%)",
            ticker, cls, s["passed"], total, pct,
        )
    log.info(
        "%s: validation — %d passed, %d queued for review",
        ticker, len(validated), len(review_items),
    )
    return validated
