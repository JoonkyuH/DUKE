# Backtest Result 02 — Stage 01 Weekly Backtest (2013–2024)

Recorded after the run. Verdict applied per the v2 pre-registered
criterion committed in docs/backtest_preregistration.md before the
backtest was executed.

## Verdict: NO EDGE DEMONSTRATED

The 95% block-bootstrap confidence interval on mean 12-month excess
return is [−2.18pp, +3.94pp], which includes zero. The screener's
performance cannot be statistically distinguished from the S&P 500
at the 5% level. Per the pre-registration commitment, this directs
next work to reworking the screener's signal set or weights — not
Stage 05, not Stage 06.

## Run parameters

- Dates: every Friday, 2013-01-04 → 2024-12-27 (626 test dates)
- Universe: point-in-time S&P 500 at each date (760 unique tickers
  across the full window)
- Screening signals as-of Friday close; entry price = next-trading-day
  close (Monday, or Tuesday+ if Monday is a holiday)
- Forward returns: equal-weighted shortlist vs SPY adjusted close
- Cost: 0.2% one-time entry per position, deducted per date
- EDGAR as_of filter applied at every date — no fundamental lookahead
- Statistics: Newey-West HAC (bandwidth = h − 1), circular block
  bootstrap (B = 4999, block length = max(h_weeks, ⌊T^(1/3)⌋))

## Per-horizon results

| Horizon  | N Obs | ESS |  Mean XS  |  NW SE  | 95% CI (bootstrap)      | Hit%  |  Max DD  |   IR  |
|----------|------:|----:|----------:|--------:|-------------------------|------:|---------:|------:|
| 1-month  |   626 | 259 |  +0.01 pp | 0.15 pp | [−0.30pp, +0.32pp]      | 46.3% | −21.12pp |  0.02 |
| 3-month  |   626 |  99 |  +0.43 pp | 0.37 pp | [−0.28pp, +1.16pp]      | 54.5% | −22.03pp |  0.23 |
| 6-month  |   626 |  57 |  +0.77 pp | 0.69 pp | [−0.60pp, +2.07pp]      | 56.5% | −20.42pp |  0.21 |
| 12-month |   626 |  37 |  +0.84 pp | 1.62 pp | [−2.18pp, +3.94pp]      | 48.7% | −23.35pp |  0.09 |

ESS = effective sample size = T × S₀ / V_NW.

## Per-regime breakdown (all horizons)

### 1-month
| Regime               | Weeks |  Wt%  |  Avg XS  | Hit%  | Volatility |
|----------------------|------:|------:|---------:|------:|-----------:|
| earnings_volatility  |    70 | 11.2% | +0.58 pp | 51.4% |   +3.14 pp |
| liquidity_contraction|     0 |  0.0% |      N/A |   N/A |        N/A |
| liquidity_expansion  |     0 |  0.0% |      N/A |   N/A |        N/A |
| macro_uncertainty    |    19 |  3.0% | −1.43 pp | 31.6% |   +3.64 pp |
| risk_off_defensive   |     0 |  0.0% |      N/A |   N/A |        N/A |
| risk_on_momentum     |   537 | 85.8% | −0.01 pp | 46.2% |   +2.29 pp |

### 3-month
| Regime               | Weeks |  Wt%  |  Avg XS  | Hit%  | Volatility |
|----------------------|------:|------:|---------:|------:|-----------:|
| earnings_volatility  |    70 | 11.2% | +0.50 pp | 51.4% |   +4.97 pp |
| liquidity_contraction|     0 |  0.0% |      N/A |   N/A |        N/A |
| liquidity_expansion  |     0 |  0.0% |      N/A |   N/A |        N/A |
| macro_uncertainty    |    19 |  3.0% | +1.88 pp | 47.4% |   +8.24 pp |
| risk_off_defensive   |     0 |  0.0% |      N/A |   N/A |        N/A |
| risk_on_momentum     |   537 | 85.8% | +0.37 pp | 55.1% |   +3.23 pp |

### 6-month
| Regime               | Weeks |  Wt%  |  Avg XS  | Hit%  | Volatility |
|----------------------|------:|------:|---------:|------:|-----------:|
| earnings_volatility  |    70 | 11.2% | +1.22 pp | 57.1% |   +5.50 pp |
| liquidity_contraction|     0 |  0.0% |      N/A |   N/A |        N/A |
| liquidity_expansion  |     0 |  0.0% |      N/A |   N/A |        N/A |
| macro_uncertainty    |    19 |  3.0% | +3.83 pp | 57.9% |   +9.76 pp |
| risk_off_defensive   |     0 |  0.0% |      N/A |   N/A |        N/A |
| risk_on_momentum     |   537 | 85.8% | +0.60 pp | 56.4% |   +4.91 pp |

### 12-month
| Regime               | Weeks |  Wt%  |  Avg XS   | Hit%  | Volatility |
|----------------------|------:|------:|----------:|------:|-----------:|
| earnings_volatility  |    70 | 11.2% |  +3.33 pp | 57.1% |  +11.73 pp |
| liquidity_contraction|     0 |  0.0% |       N/A |   N/A |        N/A |
| liquidity_expansion  |     0 |  0.0% |       N/A |   N/A |        N/A |
| macro_uncertainty    |    19 |  3.0% | +17.04 pp | 63.2% |  +20.08 pp |
| risk_off_defensive   |     0 |  0.0% |       N/A |   N/A |        N/A |
| risk_on_momentum     |   537 | 85.8% |  −0.05 pp | 47.1% |   +8.50 pp |

## Observations

**On the primary verdict.** The 12-month 95% CI of [−2.18pp, +3.94pp]
spans both sides of zero by a wide margin. The point estimate of
+0.84pp is positive but carries a NW standard error of 1.62pp, more
than 1.9× the estimate itself. There is no statistically distinguishable
edge at this horizon.

**On the effective sample size.** 626 raw observations collapse to an
ESS of 37 at the 12-month horizon. Weekly overlapping windows with a
52-week hold are nearly fully correlated; the 626 observations contain
roughly the same independent information as 37 non-overlapping annual
observations. The CIs are correspondingly wide. This is not a flaw in
the methodology — it is the honest accounting of how much information
is actually present.

**On the shorter horizons.** The 3-month and 6-month hit rates (54.5%
and 56.5%) are modestly above 50%, and mean excess returns are +0.43pp
and +0.77pp respectively. A faint positive lean is visible across the
middle horizons. However, no horizon's CI excludes zero, and the
pre-registered primary gate is the 12-month horizon. These figures are
supporting context, not a basis for a different verdict.

**On regime classifier coverage.** The regime classifier assigned 85.8%
of all 626 weeks to risk_on_momentum and assigned zero weeks to
liquidity_contraction, liquidity_expansion, and risk_off_defensive across
the full 12-year window. Three of the six regimes are entirely unexercised.
This is a structural problem: the classifier's secondary inputs (HY spread,
sector dispersion, breadth) are held at fixed neutral defaults throughout the
backtest because no per-date historical source was available. The classifier
is effectively operating on only three of its eight inputs and collapses
to a two-regime system (risk_on_momentum plus occasional
earnings_volatility/macro_uncertainty). The per-regime breakdown cannot be
interpreted as evidence about how the screener behaves across market regimes.

**On the macro_uncertainty figure.** The 12-month +17.04pp figure for
macro_uncertainty rests on 19 observations, all overlapping. The ESS for
this sub-series is a fraction of that count. This number should not be
read as a reliable regime effect; it reflects a small cluster of dates
(predominantly the COVID-adjacent period) where the screener happened to
hold names that recovered strongly.

## Classification accounting

Across all 626 screening dates at the 12-month horizon:
- Priced positions: 11,048
- Wipeout positions: 0
- Unresolved: 0
- Universe no-price (never reached screener): 47,309

No manual classification is required.

## Next work

Per the pre-registration commitment in docs/backtest_preregistration.md:
NO EDGE DEMONSTRATED directs next work to reworking the screener's
signal set or weights. Stage 05 and Stage 06 work is deferred until the
candidate-set quality is validated.

Two root causes are identified by this result and are the natural starting
points:

1. The regime classifier requires real per-date secondary inputs (HY
   credit spreads, sector dispersion, breadth) to exercise anything beyond
   risk_on_momentum. Until those inputs are wired in, regime-adaptive
   screening is inert for the majority of market environments.

2. The screener's signal set may not carry sufficient forward-return
   information at the 12-month horizon in the current form. The signal
   definitions and their weighting relative to the archetype profiles
   warrant review before a third backtest run.
