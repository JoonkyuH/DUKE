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

# Maximum risk_factors items allowed within the filing_quotes budget.
# Non-rf items fill the first (filing_budget - _RF_CAP) slots; rf fills the rest.
# If fewer non-rf items exist, rf may expand to fill the total budget.
_RF_CAP = 3

_EVIDENCE_NATURE_MAP: dict[str, str] = {
    "guidance":                "forward_guidance",
    "demand_commentary":       "realized_result",
    "margin_commentary":       "realized_result",
    "competitive_positioning": "realized_result",
    "tone_shift":              "management_commentary",
    "risk_factors":            "disclosed_risk",
    "litigation":              "disclosed_risk",
    "regulatory":              "disclosed_risk",
}


def _evidence_nature(item: dict) -> str:
    """Classify an evidence item's nature for downstream split-scoring."""
    if item.get("item_class") in ("external_bull", "external_bear"):
        return "external_claim"
    return _EVIDENCE_NATURE_MAP.get(item.get("category", ""), "management_commentary")


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


def _top_n_filing_capped(filing: list, total_budget: int = 8) -> tuple:
    """
    Budget filing_quotes with risk_factors capped at _RF_CAP (3).

    Non-rf items fill up to (total_budget - _RF_CAP) slots first.
    If fewer non-rf items exist, risk_factors expand to fill the remaining
    budget up to total_budget. Both sub-lists are sorted by _score descending.
    """
    rf_items     = [e for e in filing if e.get("category") == "risk_factors"]
    non_rf_items = [e for e in filing if e.get("category") != "risk_factors"]

    non_rf_ranked = sorted(non_rf_items, key=lambda x: x.get("_score", 0.0), reverse=True)
    rf_ranked     = sorted(rf_items,     key=lambda x: x.get("_score", 0.0), reverse=True)

    non_rf_kept = non_rf_ranked[:total_budget - _RF_CAP]   # up to 5 slots
    rf_budget   = total_budget - len(non_rf_kept)           # 3 normally; more if non-rf scarce
    rf_kept     = rf_ranked[:rf_budget]

    kept = non_rf_kept + rf_kept
    excl = max(0, len(filing) - len(kept))
    return kept, excl


def _classify(candidate: dict) -> str:
    """Return 'bear', 'bull', or 'neither'. Bear wins on tie (contested signal)."""
    qt = set(candidate.get("query_types") or [])
    has_bear = bool(qt & _BEAR_QUERY_TYPES)
    has_bull = bool(qt & _BULL_QUERY_TYPES)
    if has_bear:
        return "bear"
    if has_bull:
        return "bull"
    return "neither"


def _severity_rank(item: dict) -> int:
    sev = str(item.get("severity") or "").lower()
    return {"high": 1, "medium": 2, "low": 3}.get(sev, 4)


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
    # Classify every item before budgeting so evidence_nature flows through
    scored_items     = [{**e, "evidence_nature": _evidence_nature(e)} for e in scored_items]
    scored_candidates = [{**c, "evidence_nature": "external_claim"} for c in scored_candidates]

    mgmt   = [e for e in scored_items if e.get("item_class") == "management_quote"]
    filing = [e for e in scored_items if e.get("item_class") == "filing_quote"]
    bull   = [c for c in scored_candidates if _classify(c) == "bull"]
    bear   = [c for c in scored_candidates if _classify(c) == "bear"]

    mgmt_kept,   mgmt_excl   = _top_n(mgmt,   _BUDGETS["management_quotes"])
    filing_kept, filing_excl = _top_n_filing_capped(filing, _BUDGETS["filing_quotes"])
    bull_kept,   bull_excl   = _top_n(bull,   _BUDGETS["external_bull_evidence"])
    bear_kept,   bear_excl   = _top_n(bear,   _BUDGETS["external_bear_evidence"])

    # Uncertainties: sort by severity (high first) before capping at 3
    sorted_contradictions = sorted(contradictions or [], key=_severity_rank)
    uncertainties_kept  = sorted_contradictions[:_BUDGETS["uncertainties"]]
    uncertainties_excl  = max(0, len(sorted_contradictions) - _BUDGETS["uncertainties"])

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
