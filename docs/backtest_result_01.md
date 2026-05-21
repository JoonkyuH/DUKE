# DUKE Stage 01 Screener — Backtest Result 01

Run date: 2026-05-21
Pre-registration: docs/backtest_preregistration.md

## Verdict

MARGINAL — hold-out average −0.6pp vs S&P 500.

The screener is not destroying value on the hold-out set
but is not yet adding it. Per the pre-registration
commitment, a MARGINAL result directs the next work to
reworking archetype weights, not to Stage 06 or Stage 05.

## Per-date results

| Date       | Set       | Regime           | SL | SL Ret  | SPY Ret | Diff    |
|------------|-----------|------------------|----|---------|---------|---------|
| 2013-01-02 | IN-SAMPLE | risk_on_momentum | 13 | +54.1%  | +27.8%  | +26.3pp |
| 2014-01-02 | IN-SAMPLE | risk_on_momentum | 16 | +14.6%  | +14.5%  |  +0.1pp |
| 2015-01-02 | IN-SAMPLE | risk_on_momentum | 12 |  -5.8%  |  +1.3%  |  -7.0pp |
| 2016-01-04 | IN-SAMPLE | risk_on_momentum | 20 | +17.3%  | +15.1%  |  +2.1pp |
| 2017-01-03 | IN-SAMPLE | risk_on_momentum | 20 | +25.7%  | +22.4%  |  +3.3pp |
| 2018-01-02 | IN-SAMPLE | risk_on_momentum | 20 |  -2.1%  |  -5.1%  |  +3.1pp |
| 2019-01-02 | HOLD-OUT  | risk_on_momentum | 20 | +30.8%  | +32.3%  |  -1.5pp |
| 2020-01-02 | HOLD-OUT  | risk_on_momentum | 20 | +22.0%  | +17.2%  |  +4.8pp |
| 2021-01-04 | HOLD-OUT  | risk_on_momentum | 20 | +28.2%  | +31.2%  |  -3.0pp |
| 2022-01-03 | HOLD-OUT  | risk_on_momentum | 20 | -21.4%  | -19.0%  |  -2.4pp |

SL = shortlist size. SL Ret = equal-weighted 12-month
forward return after 0.2% entry cost. Diff = SL Ret
minus SPY Ret.

## Averages

In-sample average (2013–2018):  +4.6pp over 6 dates.
Hold-out average  (2019–2022):  −0.6pp over 4 dates.

## Observations

- The screener beat SPY on 3 of 6 in-sample dates and
  1 of 4 hold-out dates.

- The in-sample (+4.6pp) vs hold-out (−0.6pp) gap is
  consistent with weights that do not generalize beyond
  the tuning period.

- All 10 test dates were classified as
  risk_on_momentum. Only one of the screener's six
  regimes was exercised; the other five regimes
  (risk_off_defensive, liquidity_expansion,
  liquidity_contraction, earnings_volatility,
  macro_uncertainty) are unvalidated by this backtest.

- Per the pre-registration commitment, a MARGINAL
  result directs the next work to reworking archetype
  weights — not building Stage 06, not refining Stage
  05. This commitment was fixed before the result was
  seen.
