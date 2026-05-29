# DUKE — Dynamic Unified Knowledge Entity

A 7-stage multi-agent investment research pipeline for a concentrated equity
portfolio.

DUKE screens the S&P 500, runs shortlisted tickers through evidence
acquisition, refinery, scoring, a multi-agent debate, and synthesis, and
produces structured recommendation packets for human review. It is not a
trading bot and does not execute orders.

---

## The Seven Stages

| Stage | Directory | Role | Output |
|---|---|---|---|
| 01 — Screening | `pipeline/01_screening/` | Scores fundamental quality signals across the S&P 500; applies regime weights; emits a shortlist with investment archetypes (`long_term_compounder`, `quality_compounder`, or `deep_value`) | `data/screening/shortlist_{date}.json` |
| 02 — Research | `pipeline/02_research/` | Acquires earnings transcripts, SEC filings, and external evidence for a single ticker; extracts and validates structured quotes | `data/raw/{TICKER}_evidence_{date}.json` |
| 03 — Refinery | `pipeline/03_evidence_processing/` | Compresses raw evidence into a ranked analyst brief; generates catalyst map, thesis-invalidation conditions, and uncertainties | `data/processed/{TICKER}_analyst_brief_{date}.json` |
| 04 — Scoring | `pipeline/04_scoring/` | Computes Directional Thesis Score (DTS), Risk Burden Score (RBS), and confidence score from the analyst brief | `data/scored/{TICKER}_score_{date}.json` |
| 05 — Debate | `pipeline/05_debate/` | Bull and Bear analysts build independent business-merit positions (Round 1) and respond to each other (Round 2). Each emits a grounded `scenario_price` (per-share price if their case plays out) — currently derived from fundamental mechanics (EPS × multiple) and not yet reconciled against the live price, so a beaten-down name's bear floor can land above the current quote. A neutral Debate Moderator then allocates a fixed pool of 10 points between bull and bear based on grounded, surviving evidence — its `lean` + `margin` drive the debate outcome and the winner/loser weighting; the analysts' self-scores are kept for audit only | `data/debate/{TICKER}_debate_{date}.json` |
| 06 — Synthesis | `pipeline/06_synthesis/` | Risk Officer reviews for blocking issues; an entry-price calculator (Python) computes a 2:1 risk/reward entry band from `current_price` plus both analysts' scenario prices; Chief Analyst synthesizes the business-merit verdict and selects the final recommendation off a matrix on (`price_gate_passed` × Moderator's `merit_lean`) | `data/synthesis/{TICKER}_synthesis_{date}.json` |
| 07 — Output | `pipeline/07_output/` | Displays the formatted recommendation and sizing guidance; prompts for investor decision inputs; writes the decision record | `data/journal/DEC-{TICKER}-{YYYYMMDD}.json` |

---

## How to Run

There is no master orchestrator yet — stages run manually in sequence. Each
stage reads the most recent output file for the given ticker; an optional
`--date YYYYMMDD` flag (Stages 03–07) pins to a specific file.

API keys must be in the environment. In any shell session that has not sourced
`~/.zprofile`, prefix every command with `source ~/.zprofile &&` or the API
calls will fail silently. See [API Keys](#api-keys-required) below.

**Stage 01 — Screening**
```
cd pipeline/01_screening
source ~/.zprofile && python3 run_screening.py --universe sp500
```
`--universe sp500` fetches the live S&P 500 ticker list via the EarningsCall
SDK. Individual tickers can be passed as positional arguments instead:
`python3 run_screening.py NVDA AAPL MSFT`. Stage 01 uses `sys.path.insert(0,
".")` for imports, so the `cd` is required.
*`--universe` flag and positional-ticker form verified against argparse
definitions in `run_screening.py`.*

**Stage 02 — Research**
```
cd pipeline/02_research
source ~/.zprofile && python3 run.py TICKER ARCHETYPE
```
`ARCHETYPE` must be one of: `long_term_compounder`, `quality_compounder`,
`deep_value`. Use the archetype from the Stage 01 shortlist output.
*Argument form verified against `run.py` docstring and `_VALID_ARCHETYPES`
constant.*

**Stage 03 — Refinery**
```
cd pipeline/03_evidence_processing
source ~/.zprofile && python3 run.py TICKER
```
*Argument form verified against `run.py` docstring.*

**Stage 04 — Scoring**
```
cd pipeline/04_scoring
source ~/.zprofile && python3 run.py TICKER
```
*Argument form verified against `run.py` docstring.*

**Stage 05 — Debate**
```
cd pipeline/05_debate
source ~/.zprofile && python3 run.py TICKER
```
*Argument form verified against `run.py` docstring.*

**Stage 06 — Synthesis**
```
cd pipeline/06_synthesis
source ~/.zprofile && python3 run.py TICKER
```
*Argument form verified against `run.py` docstring.*

**Stage 07 — Output**
```
cd pipeline/07_output
source ~/.zprofile && python3 run.py TICKER
```
Stage 07 is interactive: it displays the recommendation, then prompts for
action (`enter` / `watch` / `pass` / `override`), conviction (1–10), and
notes. Answer the prompts directly.

For non-interactive or automated runs, pipe responses after sourcing the
environment. Example for a `watch` decision with conviction 5 and no notes:
```
cd pipeline/07_output
source ~/.zprofile && printf "watch\n5\n\n" | python3 run.py TICKER
```
Prompt order: action → conviction → notes (position size is inserted between
action and conviction only for `enter` or `override`).

*Run command verified against `run.py` docstring. Prompt order verified
against `decision_capture.py`.*

The `cd pipeline/XX` convention for Stages 03–07 follows `CLAUDE.md`. Those
run.py files resolve paths relative to `__file__` and may work from other
directories, but the `cd` form is the tested invocation.

---

## API Keys Required

All keys live in `~/.zprofile` and `~/.zshrc`. Claude Code bash sessions do
not source these automatically.

| Service | Environment Variable | Purpose |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | All LLM calls (Stages 02–07) |
| Perplexity | `PERPLEXITY_API_KEY` | Evidence discovery (Stage 02) |
| NewsAPI | `NEWSAPI_KEY` | News discovery (Stage 02) |
| FRED | `FRED_API_KEY` | HY spread and regime classification (Stage 01) |
| EarningsCall | `EARNINGSCALL_API_KEY` | Earnings transcripts; S&P 500 universe fetch (Stages 01–02) |

---

## Documentation

**[CLAUDE.md](CLAUDE.md)** — Developer and operational reference. Architecture
decisions, scoring design, known issues, commit history, and run commands.
Read this before touching any code.

**[docs/HISTORY.md](docs/HISTORY.md)** — Append-only project history. Records
what each significant commit fixed, what was broken before it, and why it
mattered. Includes the current open-issues list.
