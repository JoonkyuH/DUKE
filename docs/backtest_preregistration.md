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
- Regime classification during the backtest uses fixed
  default values for three inputs (hy_spread,
  sector_dispersion, breadth_adv_decline) because no
  free historical per-date source exists. Regime
  detection in the backtest is therefore partly
  synthetic.
- The binary-event-risk signal is inert during the
  backtest (earnings_data is empty); its weight is
  redistributed to the other signals by the screener.
- EDGAR XBRL coverage is sparse before roughly
  2016–2018, so a large share of the S&P 500 universe
  has no point-in-time fundamentals on the early test
  dates and is excluded before screening. The early
  in-sample dates therefore screen a thinned universe.
- All 10 test dates (January 2013–2022) were classified
  as risk_on_momentum. The backtest exercises only one
  of the screener's six regimes; the other five
  (risk_off_defensive, liquidity_expansion,
  liquidity_contraction, earnings_volatility,
  macro_uncertainty) are unvalidated by this run.

## Fixed parameters (committed before runner built)

- Test dates: January 1 of each year from 2013 to 2022
  inclusive (10 dates). If January 1 is not a trading
  day, use the next trading day.
- Holding period: 12 months forward total return from
  each test date.
- In-sample dates: 2013, 2014, 2015, 2016, 2017, 2018
  (6 dates). Used for any weight or threshold tuning
  only.
- Hold-out dates: 2019, 2020, 2021, 2022 (4 dates).
  Scored once, not tuned against.
- Benchmark: S&P 500 total return over the same 12-month
  holding period for each test date.
- Cost assumption: subtract a flat 0.2% per position as
  a one-time entry cost from the shortlist's return.
- Shortlist: whatever the screener's regime logic
  produces at each date (size varies 8–20 by regime);
  equal-weighted.

## Success criteria — fixed in advance

PASS: on the hold-out set, the shortlist's average
annualized total return (after the 0.2% cost) exceeds
the S&P 500 by at least 3.0 percentage points.

MARGINAL: the shortlist beats the index by more than 0
but less than 3.0 percentage points, OR trails it by
less than 1.0 point.

FAIL: the shortlist trails the S&P 500 by 1.0 percentage
point or more on the hold-out set.

## Commitment

If the result is MARGINAL or FAIL, the next work item is
reworking the archetype weights — not building Stage 06,
not refining Stage 05. The reasoning layer is only as
valuable as the candidate set it reasons over. This
commitment is fixed before the number is seen.

A backtest that is only believed when it agrees with the
builder is not a decision gate. This document exists so
that the result is acted on whichever way it lands.

## Corrections discovered after Backtest Result 01

These items were identified by reading the screener code
after the result was recorded. They are stated here as
post-run corrections, not quiet edits, so the record
remains honest.

1. Signal description error. This document describes the
   TAM share-gain proxy as "3-year CAGR." The screener
   code (signal_scorer.py) does not compute a 3-year
   CAGR. It computes a one-year year-over-year revenue
   change (rev_ann0 vs rev_ann1). Backtest Result 01
   therefore tested a one-year YoY signal, not a 3-year
   CAGR. The result remains valid as a test of the actual
   code; this note corrects the description.

2. Regime system inert in scoring. The per-regime weight
   dicts in regime_classifier.py (_BASE_PROFILES) are
   emitted into output metadata but are never read by
   run_screening() when computing composite scores. The
   field regime_adjusted_score is assigned the
   unadjusted composite directly. Scoring uses only the
   three fixed archetype weight sets (COMPOUNDER_WEIGHTS,
   QUALITY_COMPOUNDER_WEIGHTS, DEEP_VALUE_WEIGHTS) in
   every regime. Consequently, all 10 backtest dates were
   scored by an identical profile regardless of regime
   classification; the screener has no regime-adaptive
   scoring behavior in V1 as tested.
