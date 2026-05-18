"""
journal.py
Read and write DUKE decision journal records.

The journal is the persistent memory of every investment decision and its
outcome. Learning hooks written at entry are checked against outcome records
at 90, 180, and 365 days. That feedback loop is how DUKE improves over time.

Storage: data/journal/ relative to the repo root.

Naming conventions:
  Decision:   DEC-{TICKER}-{YYYYMMDD}.json
  Outcome:    OUT-{TICKER}-{YYYYMMDD}-{DAYS}d.json
  Postmortem: POST-{TICKER}-{YYYYMMDD}.json

Entry points:
  write_decision_record(record)   → path (str)
  write_outcome_record(record)    → path (str)
  write_postmortem_record(record) → path (str)
  read_journal()                  → List[dict]
"""

import json
from pathlib import Path
from typing import List


JOURNAL_DIR = Path(__file__).parent.parent.parent / "data" / "journal"


# ─────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────

def write_decision_record(record: dict) -> str:
    """
    Write a decision record to the journal.

    Required fields: ticker (str), date (str, YYYY-MM-DD)

    Returns the absolute path of the written file.
    Overwrites if a record for this ticker and date already exists.
    """
    ticker = _require(record, "ticker")
    date   = _require(record, "date").replace("-", "")
    return _write(f"DEC-{ticker}-{date}.json", record)


def write_outcome_record(record: dict) -> str:
    """
    Write an outcome record to the journal.

    Required fields: ticker (str), check_date (str, YYYY-MM-DD),
                     interval_days (int)

    Returns the absolute path of the written file.
    """
    ticker        = _require(record, "ticker")
    check_date    = _require(record, "check_date").replace("-", "")
    interval_days = int(_require(record, "interval_days"))
    return _write(f"OUT-{ticker}-{check_date}-{interval_days}d.json", record)


def write_postmortem_record(record: dict) -> str:
    """
    Write a postmortem record to the journal.

    Required fields: ticker (str), exit_date (str, YYYY-MM-DD)

    Returns the absolute path of the written file.
    """
    ticker    = _require(record, "ticker")
    exit_date = _require(record, "exit_date").replace("-", "")
    return _write(f"POST-{ticker}-{exit_date}.json", record)


# ─────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────

def read_journal() -> List[dict]:
    """
    Load all journal records from data/journal/.

    Returns a list of dicts sorted by filename (DEC before OUT before POST,
    then by ticker, then by date within each type). Each record includes a
    '_filename' key with its source filename for traceability.

    Malformed files are included as error entries rather than silently
    dropped — a corrupt record is a signal worth surfacing.
    """
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    for path in sorted(JOURNAL_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            record["_filename"] = path.name
        except (json.JSONDecodeError, OSError) as exc:
            record = {"_filename": path.name, "_error": str(exc)}
        records.append(record)

    return records


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _write(filename: str, record: dict) -> str:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    path = JOURNAL_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    return str(path)


def _require(record: dict, key: str):
    value = record.get(key)
    if value is None:
        raise ValueError(f"Journal record missing required field: '{key}'")
    return value
