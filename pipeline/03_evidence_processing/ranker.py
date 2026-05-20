"""
ranker.py
Splits scored evidence into analyst-brief buckets and enforces per-bucket budgets.

Entry point:
    rank_and_budget(scored_items, scored_candidates, contradictions, source_lims)
        -> BudgetResult

BudgetResult fields:
    management_quotes      list[dict]  — top 8 by score
    filing_quotes          list[dict]  — top 8 by score
    external_bull_evidence list[dict]  — top 4 from bull query_types
    external_bear_evidence list[dict]  — top 4 from bear query_types
    uncertainties          list[dict]  — up to 3 contradiction items
    source_limitations     list[dict]  — always included (passed through)
    excluded_counts        dict        — per-bucket counts of items beyond budget
"""

from typing import NamedTuple

_BULL_QUERY_TYPES = {"bull_case", "competitive_advantage", "sector_opportunity"}
_BEAR_QUERY_TYPES = {"bear_case", "competitive_risk", "sector_risk"}

_BUDGETS = {
    "management_quotes":      8,
    "filing_quotes":          8,
    "external_bull_evidence": 4,
    "external_bear_evidence": 4,
    "uncertainties":          3,
}


class BudgetResult(NamedTuple):
    management_quotes:      list
    filing_quotes:          list
    external_bull_evidence: list
    external_bear_evidence: list
    uncertainties:          list
    source_limitations:     list
    excluded_counts:        dict    # bucket_name -> int


def _top_n(items: list, n: int) -> tuple:
    """Sort by '_score' descending, return (kept[:n], excluded_count)."""
    ranked = sorted(items, key=lambda x: x.get("_score", 0.0), reverse=True)
    return ranked[:n], max(0, len(ranked) - n)


def _is_bull(candidate: dict) -> bool:
    qt = set(candidate.get("query_types") or [])
    return bool(qt & _BULL_QUERY_TYPES)


def _is_bear(candidate: dict) -> bool:
    qt = set(candidate.get("query_types") or [])
    return bool(qt & _BEAR_QUERY_TYPES)


def rank_and_budget(
    scored_items: list,
    scored_candidates: list,
    contradictions: list,
    source_limitations: list,
) -> BudgetResult:
    """
    Parameters
    ----------
    scored_items : evidence_items with '_score' injected
    scored_candidates : discovery_candidates with '_score' injected
    contradictions : raw contradiction dicts from the packet
    source_limitations : pre-built limitation dicts (always included)
    """
    mgmt   = [e for e in scored_items if e.get("item_class") == "management_quote"]
    filing = [e for e in scored_items if e.get("item_class") == "filing_quote"]
    bull   = [c for c in scored_candidates if _is_bull(c)]
    bear   = [c for c in scored_candidates if _is_bear(c)]

    mgmt_kept,   mgmt_excl   = _top_n(mgmt,   _BUDGETS["management_quotes"])
    filing_kept, filing_excl = _top_n(filing, _BUDGETS["filing_quotes"])
    bull_kept,   bull_excl   = _top_n(bull,   _BUDGETS["external_bull_evidence"])
    bear_kept,   bear_excl   = _top_n(bear,   _BUDGETS["external_bear_evidence"])

    # Uncertainties come directly from the contradictions list, capped at 3
    uncertainties_kept  = (contradictions or [])[:_BUDGETS["uncertainties"]]
    uncertainties_excl  = max(0, len(contradictions or []) - _BUDGETS["uncertainties"])

    excluded_counts = {
        "management_quotes":      mgmt_excl,
        "filing_quotes":          filing_excl,
        "external_bull_evidence": bull_excl,
        "external_bear_evidence": bear_excl,
        "uncertainties":          uncertainties_excl,
    }

    return BudgetResult(
        management_quotes      = mgmt_kept,
        filing_quotes          = filing_kept,
        external_bull_evidence = bull_kept,
        external_bear_evidence = bear_kept,
        uncertainties          = uncertainties_kept,
        source_limitations     = source_limitations,
        excluded_counts        = excluded_counts,
    )
