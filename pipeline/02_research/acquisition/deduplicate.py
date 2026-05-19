"""
deduplicate.py
Deduplicates evidence items by quote text hash.

Entry point:
    deduplicate(items: list[dict]) -> list[dict]

Items with the same normalised quote text are collapsed:
- The version from the highest-reliability source is kept.
- Source URLs from duplicates are merged into source_also_found_in.
- Every deduplication event is logged.
"""

import hashlib
import logging

log = logging.getLogger("deduplicate")


def _quote_text(item: dict) -> str:
    """Return the primary quote field for this item, or ''."""
    return (item.get("quote_text") or item.get("current_quote") or "").strip()


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _hash(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode()).hexdigest()


def deduplicate(items: list) -> list:
    """
    Collapse items that share the same normalised quote text.

    Args:
        items: Evidence dicts from extract_quotes() or extract_contradictions().

    Returns:
        Deduplicated list. Items without a searchable quote pass through unchanged.
    """
    # Separate quotable items from pass-throughs (e.g. contradiction items with null quote)
    quotable    = []
    passthrough = []
    for item in items:
        if _quote_text(item):
            quotable.append(item)
        else:
            passthrough.append(item)

    # Group by hash
    groups: dict[str, list] = {}
    for item in quotable:
        h = _hash(_quote_text(item))
        groups.setdefault(h, []).append(item)

    kept = []
    for h, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue

        # Sort descending by reliability; keep the best
        group.sort(key=lambda x: x.get("reliability", 0.0), reverse=True)
        winner   = dict(group[0])
        others   = group[1:]

        also_found = winner.get("source_also_found_in", [])
        for dup in others:
            dup_url = dup.get("source_url", "")
            if dup_url and dup_url not in also_found:
                also_found.append(dup_url)
            log.info(
                "Deduplication: kept %s (rel=%.2f) over %s (rel=%.2f) — quote=%r",
                winner.get("source_type", "?"), winner.get("reliability", 0),
                dup.get("source_type", "?"),   dup.get("reliability", 0),
                _quote_text(winner)[:60],
            )

        if also_found:
            winner["source_also_found_in"] = also_found
        kept.append(winner)

    result = kept + passthrough
    removed = len(items) - len(result)
    if removed:
        log.info("Deduplication complete: %d removed, %d kept", removed, len(result))
    return result
