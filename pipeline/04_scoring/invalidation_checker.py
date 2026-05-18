"""
invalidation_checker.py
Evaluates thesis invalidation conditions (TICs) from an EvidencePacket.

TIC statuses:
  not_triggered — condition not met; no concern
  monitoring    — approaching the trigger threshold; watch closely
  triggered     — the observable condition has been met

TIC severities (evaluated when triggered):
  fatal — thesis abandoned; do not enter or exit immediately
  major — urgent reassessment required within 24 hours
  minor — stress signal; does not invalidate but requires monitoring

The highest triggered severity determines the overall InvalidationStatus.
A MONITORING state (not yet triggered) also produces MONITORING status
so it surfaces for human review even before a condition breaks.

Precedence: FATAL > MAJOR > MONITORING > CLEAR
"""

from typing import List
from score_types import InvalidationStatus, InvalidationReport


def check_invalidation(
    thesis_invalidation_conditions: List[dict],
) -> InvalidationReport:
    """
    Evaluate all TICs and return an InvalidationReport.

    Args:
        thesis_invalidation_conditions: List of TIC dicts from EvidencePacket.
            Each dict has: condition_id, description, monitoring_trigger,
            severity ("fatal" | "major" | "minor"), current_status
            ("not_triggered" | "monitoring" | "triggered").

    Returns:
        InvalidationReport with overall status, triggered/monitoring condition
        ID lists, and a human-readable notes string.
    """
    triggered:  List[str] = []
    monitoring: List[str] = []
    fatal_hit   = False
    major_hit   = False

    for tic in thesis_invalidation_conditions:
        cid      = tic.get("condition_id", "")
        status   = tic.get("current_status", "not_triggered")
        severity = tic.get("severity", "minor")

        if status == "triggered":
            triggered.append(cid)
            if severity == "fatal":
                fatal_hit = True
            elif severity == "major":
                major_hit = True
        elif status == "monitoring":
            monitoring.append(cid)

    if fatal_hit:
        overall = InvalidationStatus.FATAL
    elif major_hit:
        overall = InvalidationStatus.MAJOR
    elif triggered or monitoring:
        overall = InvalidationStatus.MONITORING
    else:
        overall = InvalidationStatus.CLEAR

    return InvalidationReport(
        status=overall,
        triggered_conditions=triggered,
        monitoring_conditions=monitoring,
        fatal_triggered=fatal_hit,
        major_triggered=major_hit,
        notes=_build_notes(overall, triggered, monitoring, thesis_invalidation_conditions),
    )


def _build_notes(
    status:    InvalidationStatus,
    triggered: List[str],
    monitoring: List[str],
    tics:      List[dict],
) -> str:
    if status == InvalidationStatus.CLEAR:
        return "All thesis invalidation conditions are clear."

    tic_map = {t.get("condition_id"): t for t in tics}
    parts   = []

    if triggered:
        descs = [
            f"{cid} [{tic_map.get(cid, {}).get('severity', '?').upper()}]: "
            f"{tic_map.get(cid, {}).get('description', '')}"
            for cid in triggered
        ]
        parts.append("TRIGGERED — " + " | ".join(descs))

    if monitoring:
        descs = [
            f"{cid}: {tic_map.get(cid, {}).get('description', '')}"
            for cid in monitoring
        ]
        parts.append("MONITORING — " + " | ".join(descs))

    return "  ".join(parts)
