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

### Stage 05/06 Architecture B (40c366f + b5e5d24 + a4a5792)
Division of labor: Stage 05 debate scores business
merit only. Stage 06 splits two ways:
(a) Python — `entry_price_calculator.py` (b5e5d24)
    deterministically computes the entry-price band
    from bull_scenario_price + bear_scenario_price +
    current_price + screening_archetype. Result
    persists as `synthesis.computed_entry` and is
    threaded to the journal top level by Stage 07.
    The Chief Analyst LLM never computes these
    numbers.
(b) Chief Analyst — reads `computed_entry` (including
    `price_gate_passed`), reads `merit_lean` from the
    Debate Moderator (a4a5792), runs the Step 5
    recommendation matrix on (price_gate_passed ×
    merit_lean), and contributes only the
    `recommendation` enum + `entry_price_rationale`
    prose. No four-case arithmetic in the prompt.

Recommendation matrix:
              gate_pass         gate_fail
  merit_bull  ENTER             watch
  merit_bal   watch             pass
  merit_bear  pass (default;    pass
              watch only on
              named pivot)
INVERTED / DEGENERATE case_labels are treated as
gate-fail rows regardless of business-merit lean.
ENTER splits into strong_conviction_enter (when
final_evidence_score ≥ 80 AND merit_margin ≥ 4.0
AND no bear_correct critical adjudication) and
moderate_conviction_enter otherwise. Margin threshold
4.0 replaced the prior `bull R1 ≥ +6` test in a4a5792
since R1 self-scores are now audit-only.

This replaces the 40c366f baseline's all-watch
default under inconclusive debates. Three prompt
iterations (a844d3e, d378be2 → 909b59a revert)
tried to fix the issue at the prompt level before
b5e5d24 moved the arithmetic out of the LLM.

### Debate Moderator (a4a5792)
Stage 05 ends with a neutral evidence referee — the
Debate Moderator — that reads both R1 positions,
both R2 rebuttals, and the contentions (with the
analysts' self-scores stripped out) and allocates a
fixed pool of 10 points between bull and bear based
on grounded, surviving evidence. Sum-10 forces a
relative judgment: points given to one side are
denied the other. Forced-directional: must name a
single `decisive_evidence` item for the leaning side
unless the scores are a true near-tie.

Code-side lean derivation (`derive_lean` in
`pipeline/05_debate/run.py`, kept in sync with
`run_moderator_only.py`):
  margin = normalised_bull - normalised_bear
  abs(margin) <= 0.5  → "balanced"
  margin > 0          → "bull_leans"
  margin < 0          → "bear_leans"
ε = 0.5 (tightened from 1.0 after the harness sample
showed the wider band suppressed thin but real
bear-leaning reads). LLM cannot mint its own
"balanced" label — the code recomputes from its two
scores.

Decision wiring (`debate_scorer.compute_debate_scores`):
  outcome label:
    bull_leans → BULL_PREVAILS
    bear_leans → BEAR_PREVAILS
    balanced   → BALANCED
    null/parse-fail → INCONCLUSIVE (failure state only)
  winner/loser weights (margin-scaled):
    winner_w = 0.50 + min(|margin|, 10) / 10 × 0.30
             = 0.50 .. 0.80
    loser_w  = 1 − winner_w
  net_score_adj = w_bull × bull_self_adj
                + w_bear × bear_self_adj
  Self-scores still feed the net adjustment, but the
  weight RATIO is no longer derived from them.
  INCONCLUSIVE is no longer a normal state — it
  fires only when the Moderator block is missing.

Chief Analyst anchoring (Step 5 in
`prompts/chief_analyst.md`):
  merit_lean is treated as an anchor, same status as
  screening_archetype (4ea4c75). Default mapping:
    bull_leans → merit_bull
    bear_leans → merit_bear
    balanced   → merit_balanced
  Overriding the Moderator lean requires a NAMED,
  SPECIFIC reason in `entry_price_rationale`:
    (1) a CRITICAL contention adjudicated against the
        leaning side in Step 3, OR
    (2) a LIVE Risk Officer blocking flag the
        Moderator's evidence pool did not contain, OR
    (3) `philosophy_fit = does_not_fit` (downgrade
        to merit_bear regardless of lean).
  "Debate was close" / "merits to both sides" /
  "decisive_evidence is contestable" are explicitly
  NOT valid overrides. `bull_leans + gate-pass →
  ENTER unless a named blocker is stated.`

Why this exists: the discrimination thread (Path B
4478857 → Path B.2 b1404d5 → Architecture B 40c366f
→ b5e5d24) addressed structural causes of debate
clustering, but the bull and bear were still each
scoring their own case in isolation — both saturate
their conviction and inconclusive debates produced
all-watch defaults. The Moderator does the
relative-judgment job the analysts structurally
cannot. Self-scores stay in the record for audit
but no longer drive outcome or weighting.

Journal threading (decision_capture._build_record):
  merit_lean, merit_margin, decisive_evidence are
  written to the journal record for outcome-tracking
  correlation (post-hoc: did the decisions follow
  the Moderator's call, and did those calls hold up?).

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

Stage 05 runs two rounds plus the Moderator:
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
    R2 adjustments are audit-only — they no longer
    feed outcome or weighting (a4a5792).
  Moderator (a4a5792): neutral evidence referee that
    reads both rounds + contentions (with self-scores
    stripped) and emits a sum-10 verdict. Its `lean`
    drives outcome; its `margin` drives the
    margin-scaled (0.50..0.80) winner/loser
    weighting in compute_debate_scores. See the
    "Debate Moderator" section above for details.
    The prior R1-net-adjustment classifier
    (PREVAIL_THRESHOLD = 3.5, INCONCLUSIVE_GAP = 12.0)
    is removed.

### Two-Score Distinction (Stage 05 vs Stage 06)
Stage 05 produces mechanical evidence_score and
confidence_score from the debate. As of a4a5792 the
mechanics are: base scores + Moderator-weighted
sum of self-score adjustments (winner_w 0.50..0.80
margin-scaled), clamped. Self-scores are still
inputs to the net; they are no longer drivers of
the outcome label or the weight ratio.

Stage 06's Chief Analyst produces its own
final_evidence_score and final_confidence_score —
reasoned narrative numbers reflecting the full
synthesis (debate outcome from the Moderator, risk
officer flags, contention adjudications, philosophy
fit, computed_entry from the entry-price
calculator). The Chief Analyst's scores plus entry-
price band are used in Stage 07 and the journal
record. Stage 05 scores are preserved in the debate
record for traceability. The Moderator block
(`debate_record.moderator`) is also preserved and
its `lean` / `margin` / `decisive_evidence` are
threaded to the journal.

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

~~File-handle leak~~ — FIXED (see Pending below).
Stage 01 previously leaked ~6 FDs per ticker
(~3.3 sockets + ~2.1 pipes), requiring
`ulimit -n 8192` to survive 500 tickers. Resolved
by hoisting `ThreadPoolExecutor` out of the
per-ticker loop and closing `yf.Ticker.session`
explicitly. Post-fix slope is ~0/ticker. The
`ulimit -n 8192` guidance is kept as a
belt-and-suspenders safety net but is no longer
load-bearing.

### Pending
~~Entry-price computation in Python~~ — DONE in
**b5e5d24**. `pipeline/06_synthesis/entry_price_calculator.py`
is a pure function (13/13 tests pass) consuming
bull_scenario_price + bear_scenario_price +
current_price + screening_archetype and returning
case_label (IN_BAND / ABOVE_BAND / BELOW_BEAR /
INVERTED / DEGENERATE), entry_price, entry_range
({low, high}), target_2to1_price = (bull + 2*bear)/3,
ratio_at_current, archetype_min_rr (deep_value 2.0
/ quality_compounder 1.5 / long_term_compounder 1.2),
price_gate_passed, and a rationale. Stage 06's
run.py runs the calculator pre-Chief, injects
computed_entry into the Chief brief, and persists
it as synthesis.computed_entry. Stage 07's
decision_capture._build_record reads journal entry
fields from there. The Chief Analyst prompt is
slimmed: Step 8 is now read-only (no computation);
Step 5 is a matrix on (price_gate_passed ×
business-merit lean) that maps to the existing
recommendation enum. This removes the all-watch
default that the 40c366f baseline produced under
inconclusive debates. Chief no longer emits
entry_price / entry_range / current_price_used /
target_2to1_price / ratio_at_current /
price_gate_passed / archetype_min_rr — Python
writes those to the journal directly; Chief
contributes recommendation + entry_price_rationale
prose.

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

Architecture B (40c366f + b5e5d24 + a4a5792) —
committed; validated end-to-end on 6 tickers
(VRT/BSX/CRM/NVDA/PODD/PTC). scenario_price flows
analysts → debate → Chief brief → journal. Entry-
price refactor (b5e5d24) computes the band
deterministically in Python; Chief writes
recommendation off the resolved band via the Step 5
matrix. Debate Moderator (a4a5792) drives outcome
+ weighting; self-scores demoted to audit-only;
Chief's Step 5 anchors on merit_lean. The all-watch
default and the all-balanced-debate clustering are
both gone. Three prompt iterations (a844d3e, d378be2
→ 909b59a revert) and the discrimination thread
(Path B 4478857 → Path B.2 b1404d5 → 40c366f →
b5e5d24) preceded the Moderator fix; each addressed
a structural piece, but the analysts-scoring-their-
own-case root cause needed a neutral judge to close.
b1404d5 is not separately validated; its rubric
changes carried into Architecture B.

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
40c366f  feat: Architecture B — debate scores business merit only, valuation moves to Chief Analyst entry-price adjudication
b5e5d24  feat: move entry-price computation to Python (entry_price_calculator); Chief writes recommendation off deterministic band
a4a5792  feat: Debate Moderator drives outcome + weighting (ε=0.5); self-scores demoted to audit-only; Chief lean is a named-override anchor


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
