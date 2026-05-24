# DUKE — Developer Reference

## What is DUKE?

DUKE ("Doesn't Usually Know Either") is a 7-stage
multi-agent investment research pipeline built for
the Li Family Office. It produces structured
recommendation packets for human review — it is
NOT a trading bot. Andrew Han is Director of
Investments and the sole operator.

## Pipeline Architecture

Stage 01: Screening
  cd pipeline/01_screening
  python3 run_screening.py --universe sp500
  → data/screening/shortlist_{date}.json

Stage 02: Research
  cd pipeline/02_research
  python3 run.py TICKER ARCHETYPE
  → data/raw/{TICKER}_evidence_{date}.json

Stage 03: Refinery
  cd pipeline/03_evidence_processing
  python3 run.py TICKER
  → data/processed/{TICKER}_analyst_brief_{date}.json

Stage 04: Scoring
  cd pipeline/04_scoring
  python3 run.py TICKER
  → data/scored/{TICKER}_score_{date}.json

Stage 05: Debate
  cd pipeline/05_debate
  python3 run.py TICKER
  → data/debate/{TICKER}_debate_{date}.json

Stage 06: Synthesis
  cd pipeline/06_synthesis
  python3 run.py TICKER
  → data/synthesis/{TICKER}_synthesis_{date}.json

Stage 07: Output
  cd pipeline/07_output
  python3 run.py TICKER
  → data/journal/DEC-{TICKER}-{YYYYMMDD}.json


## CRITICAL: Environment Variables

ALL API keys live in ~/.zprofile and ~/.zshrc.
Claude Code bash sessions do NOT source these
automatically. ALWAYS prefix commands with:

  source ~/.zprofile &&

Keys required:
  ANTHROPIC_API_KEY
  PERPLEXITY_API_KEY
  NEWSAPI_KEY
  FRED_API_KEY
  EARNINGSCALL_API_KEY


## Architecture Decisions

### Economic Profile Classifier
Tickers are classified into economic profiles
(not GICS sectors) for threshold normalization.

Files:
  pipeline/01_screening/economic_profiles.json
  pipeline/01_screening/scoring_adjustments.json
  pipeline/01_screening/economic_profile_classifier.py

Classification order:
  1. ticker_override        (confidence 1.0)
  2. gics_industry pattern  (confidence 0.85)
  3. financial_signature    (confidence 0.60)
     added to classification_review_queue
  4. unknown                (confidence 0.0)
     neutral multipliers applied

Special handling:
  banking/insurance: gross_margin + fcf_margin
    disabled entirely
  reit: fcf_margin disabled

### Transcript Waterfall
Priority 0: EarningsCall API
  earningscall_fetcher.py
  speaker-segmented, Q&A separated
  dynamic ticker resolution (GOOGL -> GOOG)
  staleness: conference_date < today -> re-fetch
Priority 1A: Perplexity discovery
Priority 1B: Static IR page PDF
Priority 2:  IR press release
Priority 3:  SEC 8-K exhibit
Priority 4:  FMP API
Priority 5:  YouTube

### Scoring Architecture
DTS (Directional Thesis Score):
  excludes disclosed_risk items
  management quote multipliers applied
  external evidence asymmetry applied
  screening adjustment = (screening_score-50)*0.30

RBS (Risk Burden Score):
  disclosed_risk items only
  specificity weighted (specific=1.0, generic=0.35)

Confidence:
  coverage penalty for missing management quotes
  0 quotes: -20, 1-2: -10, 3-4: -5

NEUTRAL management quotes:
  zero weight everywhere EXCEPT:
  item_class=management_quote AND
  significance=HIGH AND category=guidance
  -> mild bear signal: eff_weight * 0.08

### Stage 03 Synthesis
After evidence compression, one LLM synthesis call
generates three structured fields:
  catalyst_map (2-5 items)
  thesis_invalidation_conditions (2-4 items)
  uncertainties (1-3 items)
Prompt: pipeline/03_evidence_processing/prompts/synthesis.md

### Stage 05/06 Evidence Slices
Risk Officer receives filtered evidence:
  management quotes: risk/guidance/tone, HIGH/MEDIUM
  filing quotes: risk_factors + MD&A sections
  all external bear evidence
  all external bull evidence
  output: evidence_verification field

Chief Analyst receives full compressed set:
  all 8 management quotes
  all 8 filing quotes
  all 4 external bull
  all 4 external bear
  output: evidence_challenge field

Note: bull_rebuttal.md and bear_rebuttal.md exist
but are NOT activated. Decision: single-round
debate only. Chief Analyst performs evidence
challenge instead.

### EDGAR Data Integrity (3 layers)
Layer 1 - Concept selection (_entries() in edgar_client.py):
  Selects concept with most recent data (max end
  date), not first concept passing loose threshold.
  Prevents stale XBRL concepts blocking current ones.
  Falls back with warning log if no recent data.

Layer 2 - Period alignment (signal_scorer.py):
  Validates revenue and gross_profit are from same
  fiscal year before computing gross margin.
  Validates revenue and FCF before FCF margin.
  Mismatches set derived metric to None and log
  PERIOD MISMATCH warning.

Layer 3 - Disk cache (edgar_client.py):
  edgar_snapshot_cache table in duke_cache.db
  7-day TTL, stores full companyfacts JSON atomically
  per ticker. Eliminates redundant SEC API fetches.
  Path: pipeline/02_research/acquisition/cache/duke_cache.db


## Known Issues

### Must fix before relying on shortlist
EQT scores #1 on S&P 500 but is a natural gas E&P.
Peak-cycle FCF makes it look like a compounder.
EDGAR gross profit for E&P excludes DD&A/depletion.
No energy cyclical economic profile handles this.

COF scores #12 but NET_CASH_FORTRESS fires wrong.
Banking companies carry deposits as liabilities but
the net cash signal only checks long-term debt.
Fix: add net_cash_pct to disabled signals for
banking and insurance in economic_profiles.json.

872 tickers in classification_review_queue after
S&P 500 run. GICS pattern coverage needs expansion.
Audit unknown/financial_signature classifications
and add missing patterns to economic_profiles.json.

### Pending
DUKE-16: Multi-period trend analysis
DUKE-19: TAM share-gain and ROIC signals

### Do last
DUKE-17: Master orchestrator duke.py
Sector z-score upgrade (needs 500-ticker data)


## Commit History

82fd587  fix: days_to_earnings from yfinance (DUKE-01)
841f681  fix: 91-day earnings estimation fallback
64fb0f7  feat: Damodaran sector multipliers (DUKE-02 v1)
92b22f5  feat: economic profile classifier (DUKE-02 v2)
49f6781  feat: EarningsCall API transcripts (DUKE-03)
3af1833  feat: NEUTRAL signal + catalyst_map wired (DUKE-09, DUKE-12)
ef09cdb  feat: Risk Officer + Chief Analyst evidence slices (DUKE-13, DUKE-15)
c920a69  fix: MD&A filter + external bull filter
4edd9e4  fix: per-ticker 30s timeout Stage 01
2ec2f2b  fix: EDGAR concept selection + alignment + disk cache


## S&P 500 Screening Results (2026-05-24)
497 tickers screened, 20 passed, regime: risk_on_momentum

Rank  Ticker  Score  Archetype             Notes
1     EQT     83.1   long_term_compounder  NEEDS REVIEW: energy E&P peak cycle
2     PODD    80.6   deep_value
3     ADBE    79.0   quality_compounder
4     NVDA    78.2   long_term_compounder
5     PAYX    78.1   quality_compounder
6     PTC     76.2   quality_compounder
7     PLTR    76.0   long_term_compounder
8     DXCM    75.7   quality_compounder
9     INTU    75.4   deep_value
10    BSX     75.4   quality_compounder
11    VRT     74.9   long_term_compounder
12    COF     74.7   either                NEEDS REVIEW: bank, NET_CASH_FORTRESS wrong
13    ADSK    73.4   quality_compounder
14    FDS     73.3   quality_compounder
15    SNPS    72.8   quality_compounder
16    SPGI    72.7   quality_compounder
17    RMD     72.5   quality_compounder    gross margin bug fixed (was 103%, now 59.4%)
18    TYL     72.1   quality_compounder
19    TTD     72.0   deep_value
20    NOW     71.8   either

Note: Re-run Stage 01 with all fixes before
running Stages 02-07 on shortlist.


## API Services

Service       Env Var                Purpose
Anthropic     ANTHROPIC_API_KEY      All LLM calls
Perplexity    PERPLEXITY_API_KEY     Evidence discovery
NewsAPI       NEWSAPI_KEY            News discovery
FRED          FRED_API_KEY           HY spread, regime
EarningsCall  EARNINGSCALL_API_KEY   Transcripts $69/mo
