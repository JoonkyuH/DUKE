# Layer 1 — Initial Screening

## What This Layer Does
Takes a universe of securities, scores each one across six signals,
applies regime-adjusted weights, and outputs a ranked shortlist of
5–20 tickers for Layer 2 deep research.

## Files

```
layer1_screening/
├── schemas/
│   ├── raw_signal_record.json    — Input schema (one record per ticker)
│   └── screening_output.json     — Output schema (full shortlist)
│
├── screening/
│   ├── signal_scorer.py          — Six signal scoring functions (0–100 each)
│   ├── regime_classifier.py      — Market regime detection + weight profiles
│   ├── reason_codes.py           — Reason codes and investigation flags
│   └── screener.py               — Main orchestrator (entry point: run_screening)
│
└── prompts/
    └── market_researcher.md      — System prompt for the Market Researcher role
```

## The Six Signals

| Signal             | What It Measures                            | Key Inputs                              |
|--------------------|---------------------------------------------|-----------------------------------------|
| Momentum           | Trend strength vs MAs and ROC               | Price vs 20/50/200d MA, 5d/20d ROC, RSI|
| Relative Strength  | Outperformance vs market and sector         | RS vs SPY 10/20d, RS vs sector 10d     |
| Volume Anomaly     | Institutional participation signal          | Today's vol / 20d avg vol, direction   |
| Sector Leadership  | Leading within a strong sector              | Sector rank percentile, sector RS      |
| News Velocity      | Acceleration in quality news coverage       | Article count acceleration, quality    |
| Earnings Proximity | Catalyst window (pre/post earnings)         | Days to/since earnings, EPS surprise   |

## Regime Profiles

| Regime               | Threshold | Max Size | What Changes                                |
|----------------------|-----------|----------|---------------------------------------------|
| risk_on_momentum     | 52        | 20       | Momentum + RS overweighted                  |
| risk_off_defensive   | 65        | 10       | Sector leadership dominant; high bar        |
| liquidity_expansion  | 50        | 20       | Volume + sector rotation emphasized         |
| liquidity_contraction| 68        | 8        | Very high bar; only RS leaders pass         |
| earnings_volatility  | 55        | 15       | Earnings proximity weighted at 25%          |
| macro_uncertainty    | 65        | 10       | Balanced; high bar; low shortlist size      |

## Usage (once Claude Code environment is ready)

```python
from screening.screener import run_screening

result = run_screening(
    raw_records=my_ticker_records,       # List of raw_signal_record dicts
    regime_indicators=market_inputs,     # VIX, breadth, SPY trend, etc.
    sector_data=sector_rs_data,          # Optional: sector-level RS data
)

print(result.market_regime)             # e.g. "risk_on_momentum"
print(result.shortlist_count)           # e.g. 14
for ticker in result.shortlist:
    print(ticker.ticker, ticker.composite_score, ticker.reason_codes)
```

## Output Contract for Layer 2
Each `ShortlistEntry` in the output contains:
- `ticker` — the symbol
- `composite_score` — 0–100 weighted score
- `signal_scores` — all six individual scores (null if data unavailable)
- `reason_codes` — why this ticker was selected
- `flags` — what Layer 2 should specifically scrutinize
- `priority` — rank (1 = highest score)

Layer 2 receives the full `ScreeningOutput` as its input packet.

## Design Notes
- Missing signal data returns `null` (not zero). The composite is rebalanced across available signals.
- Regime classification is always explicit and logged. It is never inferred silently.
- A fallback threshold (45) activates if fewer than 5 tickers pass the regime threshold.
- Flags do not disqualify tickers. They direct Layer 2's investigation focus.
- The researcher system prompt is additive — Claude Code will call the Python scoring
  logic directly in production. The prompt is used when the researcher role is
  powered by a language model (Perplexity + Grok gathering raw data for the schema).
