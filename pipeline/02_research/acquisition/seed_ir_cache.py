"""
seed_ir_cache.py
Idempotent seed script for ir_cache rows that Perplexity cannot discover reliably.
Run from any directory:
    python3 pipeline/02_research/acquisition/seed_ir_cache.py
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent / "cache" / "duke_cache.db"

# ticker, company_name, ir_url, fiscal_year_end_month, calendar_quarter_offset, confidence
_SEEDS = [
    ("NVDA", "NVIDIA Corporation",
     "https://investor.nvidia.com/financial-info/quarterly-results/default.aspx",
     1, 1, 0.99),
    ("PLTR", "Palantir Technologies Inc.",
     "https://investors.palantir.com/financials/quarterly-results",
     12, 0, 0.99),
    ("AVGO", "Broadcom Inc.",
     "https://investors.broadcom.com",
     10, 0, 0.99),
]


def seed() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with sqlite3.connect(_DB_PATH) as con:
        for ticker, company_name, ir_url, fye_month, cal_offset, confidence in _SEEDS:
            con.execute(
                """INSERT OR IGNORE INTO ir_cache
                   (ticker, company_name, ir_url, fiscal_year_end_month,
                    calendar_quarter_offset, discovered_by, last_verified_at,
                    status, confidence)
                   VALUES (?, ?, ?, ?, ?, 'seed', ?, 'active', ?)""",
                (ticker, company_name, ir_url, fye_month, cal_offset, today, confidence),
            )
            print(f"  {ticker}: seeded (or already present)")
    print("Done.")


if __name__ == "__main__":
    seed()
