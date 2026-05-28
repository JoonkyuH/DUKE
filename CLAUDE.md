# DUKE — Developer Reference

## What is DUKE?

DUKE ("Dynamic Unified Knowledge Entity") is a 7-stage
multi-agent investment research pipeline for a concentrated
equity portfolio. It produces structured recommendation
packets for human review — it is not a trading bot.

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
     gics_industry_patterns covers the full live
     S&P 500 GICS industry vocabulary (~52 patterns).
     ~12 strings deliberately left unmapped → unknown:
       Gold, Copper, Steel, Agricultural Inputs,
       Advertising Agencies, Grocery Stores,
       Food Distribution, Medical Care Facilities,
       Conglomerates, Information Technology Services,
       Specialty Business Services. (76405ff)
  3. financial_signature    (advisory only)
     Does not assign a scoring-relevant profile.
     Unmatched tickers → unknown with neutral
     multipliers; result added to review queue.
  4. unknown                (confidence 0.0)
     neutral multipliers applied

  Review queue deduplicates per ticker.

Special handling:
  banking/insurance: gross_margin + fcf_margin
    disabled entirely
  reit: fcf_margin disabled

### Investment Archetypes
Stage 01 emits one of three archetypes:
  long_term_compounder
  quality_compounder
  deep_value

"either" has been removed. Ties resolve
deterministically to the more conservative archetype
(8dd74c1). Stage 05 bull, bear, and chief-analyst
prompts define branches for all three archetypes
(d0f0eb2).

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

### Stage 05/06 Architecture B (40c366f — UNVALIDATED)
Division of labor: Stage 05 debate scores business
merit only. Stage 06 Chief Analyst adjudicates
valuation separately.

Stage 05 = business merit
  Bull: upside / quality case (ecosystem, moat,
        margins, FCF, growth durability).
        NO valuation discussion.
  Bear: fundamental-risk case (execution misses,
        moat erosion, concentration, growth
        durability). NO valuation_challenge.
  Both: emit a grounded scenario_price
        {price, mechanism, grounding} — price if
        their case plays out. Mechanism must cite
        disclosed inputs (guided EPS × multiple,
        intrinsic-value math, deceleration ×
        compression). R1-only; rebuttals do not
        emit or revise scenario_price.

Stage 06 = valuation adjudicator
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

  Chief Analyst additionally adjudicates entry price:
    Reads bull_scenario_price + bear_scenario_price
    + current_price (from market_technical_context).
    Computes up/down = (bull_scenario − current) /
    (current − bear_scenario).
    Threshold: fixed 2:1. Entry acceptable when
    up/down ≥ 2.0.
    Three output cases:
      (1) Normal ordering, ratio ≥ 2.0:
            entry_price = current_price
            entry_range = [current, (bull+2×bear)/3]
      (2) Normal ordering, ratio < 2.0:
            entry_price = (bull + 2×bear) / 3
            entry_range = [entry×0.97, entry×1.03]
            recommend watch
      (3) Inverted (bull_scenario ≤ current):
            entry_price = null
            entry_range = null
            state inversion in rationale
            NEVER produce a fake entry number
            under inversion.
    Emits: entry_price, entry_range,
           entry_price_rationale, current_price_used.
    Surfaced to journal top-level.

Stage 05 runs two rounds:
  Round 1: Bull and Bear independent business-merit
    positions (max_tokens=16384 each — raised from
    4096 in 7b33f34 for Path B prompt expansion).
  Round 2: Cross-feed rebuttals (activated 6d215ee).
    Bull gets bear R1; Bear gets bull R1.
    max_tokens=16384 — rebuttals must respond
    to every opposing argument.
    Down-only clamp enforced in code:
      bull R2 score ≤ bull R1 score
      bear R2 score ≥ bear R1 score (less negative)
    Both clamped to [-10, +10].
    R2 adjustments are informational only; debate
    scores computed from R1 only.
  Outcome classifier on R1 net adjustment:
    PREVAIL_THRESHOLD = 3.5, INCONCLUSIVE_GAP = 12.0.
    Outcomes now mean "does the BUSINESS-MERIT
    picture lean bull or bear" — valuation no longer
    enters the classifier.

### Two-Score Distinction (Stage 05 vs Stage 06)
Stage 05 produces mechanical evidence_score and
confidence_score from the debate (signal weights,
contention adjustments, clamp logic). Stage 06's
Chief Analyst produces its own final_evidence_score
and final_confidence_score — these are reasoned
narrative numbers that reflect the full synthesis
(debate outcome, risk officer flags, contention
adjudications, philosophy fit). Stage 06 also emits
entry_price / entry_range / entry_price_rationale /
current_price_used (Architecture B). The Chief
Analyst's scores plus entry-price band are used in
Stage 07 and the journal record. Stage 05 scores
are preserved in the debate record for traceability.

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

File-handle leak: Stage 01 does not release
file/DB handles between tickers. Worked around
with `ulimit -n 8192` per-terminal. Must be fixed
before any unattended/scheduled run.

### Pending
SYF misclassification: GICS "Credit Services"
maps to payments_network, but SYF is a consumer-
credit lender. Needs a banking ticker_override
(same pattern as COF).

Electronic Components profile gap: APH, TEL, GLW
route to unknown/neutral. The bucket warrants a
dedicated economic profile.

Contradiction channel: wired end-to-end (Stage 02 →
03 → 04 → 05) but never validated with live data.
Requires two consecutive Stage 02 runs on the same
ticker — first run populates transcript_cache; second
run diffs against it and produces contradictions.

Architecture B (40c366f) — UNVALIDATED end-to-end.
Debate now scores business merit only; Chief Analyst
adjudicates entry price via 2:1 risk/reward band on
scenario prices. The discrimination thread (Path B
4478857 → Path B.2 b1404d5 → Architecture B 40c366f)
absorbed the earlier "test-run debates all resolved
balanced" concern; b1404d5 is not separately
validated. Re-run pending.

Stage 04 fundamentals wiring deferred to V2: signal
thresholds and economic profiles are live, but forward
guidance-vs-consensus comparison needs a dedicated
data source before Stage 04 can score it.

V1.5 — native financial-company signals: banking/
insurer/REIT profiles currently work by disabling
misleading signals rather than scoring native
metrics (NIM, ROE, FFO, combined ratio). Candidate
new profiles: health_insurer, it_services,
commodity_cyclical.

DUKE-16: Multi-period trend analysis
DUKE-19: TAM share-gain and ROIC signals

DCF valuation anchor (V2, data-blocked): intrinsic-
value entry price via discounted cash flow. Requires
multi-year cash-flow projections DUKE does not
generate plus a paid fundamentals feed (previously
declined). Future option pending data.

Reverse-DCF / expectations anchor (V2, data-blocked):
compute the growth/margin trajectory implied by
current price and judge achievability. Best-fit for
priced-for-perfection names. Same data dependency
as DCF anchor.

yfinance plumbing + multiple-check panel: Architecture
B currently anchors entry price on the screening
raw file's current_price (potentially days old).
Follow-up adds yfinance daily refresh plus a
trailing/forward P/E + peer-multiple panel for the
Chief Analyst to sanity-check the analysts' scenario
multiples. Required before V2 valuation anchors
become useful.

Thread debate_invalid to journal top-level: when
Round 1 parse-failure produces outcome="not_computable"
(7b33f34), the flag lives in the source debate file
and chief_analyst_output.metadata.debate_outcome_used
but not at journal top level. A casual reader sees a
plausible watch recommendation without the
failure-mode signal. Minimal one-line fix in
decision_capture._build_record, parallel to the
philosophy_fit_notes / entry_price patterns.
Cosmetic; safety net itself works.

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
76405ff  fix: expand GICS pattern coverage, fail-safe classification fallback, dedupe review queue
d0f0eb2  fix: add quality_compounder archetype branch to Stage 05 debate prompts
8dd74c1  fix: resolve archetype ties to conservative archetype, remove "either"
75e225d  docs: update CLAUDE.md — GICS, archetype, and tie-resolution fixes; refresh pending work
da27c16  fix: route real Stage 02 contradictions through to scoring and debate
546bdf4  fix: thread quality_compounder archetype through Stage 06 synthesis
6d215ee  feat: activate Stage 05 Round 2 rebuttals — bull and bear now respond to each other
4ea4c75  fix: anchor Chief Analyst to screened archetype; record archetype provenance in journal; document two-score distinction


## S&P 500 Screening Results (2026-05-24)
[STALE — pre-fix snapshot; re-run pending]
497 tickers screened, 20 passed, regime: risk_on_momentum
Predates 76405ff (GICS expansion), 8dd74c1 (tie-
resolution), and COF/SYF banking ticker_overrides.
Archetypes marked * were "either" in this run;
"either" no longer exists — will differ on re-run.

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
12    COF     74.7   *                     banking ticker_override added post-run
13    ADSK    73.4   quality_compounder
14    FDS     73.3   quality_compounder
15    SNPS    72.8   quality_compounder
16    SPGI    72.7   quality_compounder
17    RMD     72.5   quality_compounder    gross margin bug fixed (was 103%, now 59.4%)
18    TYL     72.1   quality_compounder
19    TTD     72.0   deep_value
20    NOW     71.8   *

Re-run Stage 01 before running Stages 02-07.


## API Services

Service       Env Var                Purpose
Anthropic     ANTHROPIC_API_KEY      All LLM calls
Perplexity    PERPLEXITY_API_KEY     Evidence discovery
NewsAPI       NEWSAPI_KEY            News discovery
FRED          FRED_API_KEY           HY spread, regime
EarningsCall  EARNINGSCALL_API_KEY   Transcripts $69/mo
