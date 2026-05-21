# DUKE Stage 01 Screener — Backtest Pre-Registration

Written before the backtest is run. This document fixes
the success criteria in advance so the result is a
decision gate, not a search for confirmation.

## What is being tested

Stage 01 — the fundamental screener — in isolation. Not
the full pipeline. No LLM stages. The question: does the
screener's candidate set, selected at past points in
time, outperform the S&P 500 index over the holding
period that follows.

## Method

- Universe: S&P 500 constituents as of each test date.
- Run the Stage 01 screener at multiple historical dates
  using only data that was available on that date — no
  lookahead. Point-in-time fundamentals; no use of
  restated figures published after the test date.
- For each test date, take the shortlist the screener
  produces.
- Measure the equal-weighted forward total return of
  that shortlist against the S&P 500 total return over a
  fixed holding period.
- In-sample / hold-out split: any tuning of screener
  weights or thresholds happens only against in-sample
  dates. The hold-out dates are scored once, untouched.
  If weights are changed after seeing in-sample results,
  the hold-out set is re-run without further adjustment.

## Known limitations of this test

- Survivorship: the universe must be S&P 500
  constituents as of each test date, not today's
  membership, or the result is inflated by hindsight.
- Sample size: a small number of test dates produces a
  noisy result. The success margin must be large enough
  not to be explained by that noise.
- The screener is V1 and uses proxy signals (3-year
  CAGR and gross margin trend for TAM share-gain;
  FCF-to-net-income for incremental ROIC). The backtest
  scores the proxies, not the intended V1.5 signals.

## Success criteria — fixed in advance

PASS: the screener's candidate set beats the S&P 500
total return, after reasonable cost assumptions, over
the holding period, on the hold-out set — by a margin
large enough not to be noise.

MARGINAL: the candidate set roughly matches the index.
The screener is not destroying value but is not yet
adding it. The archetype weights need work before the
reasoning layer can be trusted to add edge.

FAIL: the candidate set underperforms the index on the
hold-out set. The screener is selecting bad candidates.
The reasoning layer cannot fix this.

## Commitment

If the result is MARGINAL or FAIL, the next work item is
reworking the archetype weights — not building Stage 06,
not refining Stage 05. The reasoning layer is only as
valuable as the candidate set it reasons over. This
commitment is fixed before the number is seen.

A backtest that is only believed when it agrees with the
builder is not a decision gate. This document exists so
that the result is acted on whichever way it lands.
