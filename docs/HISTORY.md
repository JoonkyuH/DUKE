# DUKE — Project History

DUKE ("Dynamic Unified Knowledge Entity") is a 7-stage multi-agent investment
research pipeline for a concentrated equity portfolio. It runs a candidate
ticker through screening (Stage 01), evidence acquisition (Stage 02), refinery
(Stage 03), scoring (Stage 04), debate (Stage 05), synthesis (Stage 06), and
decision capture (Stage 07). The output is a structured recommendation packet
— a `watch / enter / pass` judgment with an evidence trail — for human review.
DUKE is not a trading bot and does not execute orders.

This file is append-only reference history. Each significant change is
recorded with its commit hash, what was broken before the fix, what the fix
did, and why it mattered for investment quality.

---

## Chronological Change Log

### Early Build (pre-2026-05-24)

**82fd587** — `fix: populate days_to_earnings from yfinance`
Binary risk scoring requires a days-to-earnings estimate. Before this fix the
field was always zero, meaning the system could never identify an imminent
binary event.

**841f681** — `fix: 91-day earnings estimation fallback`
When yfinance returns no future earnings date, the system now defaults to
91 days rather than failing. Prevents null days_to_earnings on recently
reported tickers.

**64fb0f7 / 92b22f5** — `feat: Damodaran sector multipliers + economic profile classifier`
Initial signal thresholds were flat across all industries, which over-penalised
asset-light software and under-penalised cyclicals. The economic profile
classifier maps each ticker to a profile (software_saas, payments_network,
banking, etc.) and applies Damodaran-anchored scoring adjustments. This is the
foundation for all subsequent threshold work.

**49f6781** — `feat: EarningsCall API as primary transcript source`
Transcript quality directly controls management quote extraction quality.
Before this fix, transcripts were discovered ad-hoc via Perplexity and IR
pages, producing inconsistent speaker segmentation and Q&A separation.
EarningsCall API (Priority 0 in the waterfall) delivers structured,
speaker-segmented transcripts with staleness-aware prefetch.

**3af1833** — `feat: NEUTRAL signal scoring + catalyst_map wiring`
Neutral management quotes were previously discarded. High-significance
guidance-category neutrals now carry a mild bear signal (eff_weight × 0.08)
to flag when management stops guiding up. The catalyst_map and TIC fields from
Stage 03 synthesis are also wired into Stage 04 for scoring context.

**ef09cdb** — `feat: Risk Officer and Chief Analyst evidence slices`
Both agents were receiving the raw full evidence set, meaning the Chief
Analyst spent tokens on low-signal noise and the Risk Officer couldn't
distinguish analyst claims from source material. This commit introduces
filtered slices: Risk Officer gets management risk/guidance/tone quotes,
filing risk_factors, and all external evidence; Chief Analyst gets the full
compressed set (8+8+4+4) for the evidence challenge pass.

**c920a69** — `fix: MD&A section label filter + external bull filter`
Stage 03 was incorrectly routing MD&A-labelled filing sections into the
Risk Officer's risk_factors slice, and bear-classified external evidence
was leaking into the bull slice. Both filters corrected.

**4edd9e4** — `fix: per-ticker 30s timeout in Stage 01`
Stage 01 would hang indefinitely on slow data fetches (EDGAR, yfinance). A
30-second per-ticker timeout prevents one slow ticker from blocking the full
universe run.

**2ec2f2b** — `fix: EDGAR concept selection, cross-metric period alignment, disk cache`
Three separate EDGAR data integrity bugs:
1. Concept selection picked the first passing concept regardless of recency,
   causing stale XBRL concepts to block current ones.
2. Gross margin was computed from revenue and gross_profit belonging to
   different fiscal years after a company changed fiscal year end.
3. No disk cache meant every Stage 01 run re-fetched full companyfacts JSON
   from the SEC API (~80KB per ticker × 500 tickers). The edgar_snapshot_cache
   table in duke_cache.db now caches at a 7-day TTL.

**04260c0** — `fix: commodity-cyclical archetype override (EQT) + profile-aware reason codes (COF)`
EQT (a natural-gas E&P) scored #1 on the S&P 500 because peak-cycle free cash
flow made it appear compounder-like, and EDGAR gross profit for E&P names
excludes depletion and DD&A — inflating both the gross margin signal and the
FCF signal artificially. There was no economic profile that handled energy
cyclicals correctly, so EQT passed every quality filter it encountered. This
commit adds a commodity-cyclical archetype override so EQT-class names are
classified and scored correctly. It also adds profile-aware reason codes and a
net_cash signal correction for COF in Stage 01. EQT is no longer an open issue.

---

### 2026-05-24 Session

**76405ff** — `fix: expand GICS pattern coverage, fail-safe classification, dedupe review queue`
The economic profile classifier mapped GICS industry strings via regex
patterns but the initial pattern set covered only ~40 of the ~52 distinct
GICS industry strings in the live S&P 500. Unmatched tickers fell through to
unknown (neutral multipliers), silently suppressing DTS scores for legitimate
quality names. This commit expands gics_industry_patterns to cover the full
live vocabulary, adds a fail-safe classification fallback so unknown tickers
are correctly tagged rather than silently mis-scored, and deduplicates the
review queue so each unclassified ticker appears at most once per run.

~12 strings are deliberately left unmapped (Gold, Copper, Steel, Agricultural
Inputs, Advertising Agencies, Grocery Stores, Food Distribution, Medical Care
Facilities, Conglomerates, Information Technology Services, Specialty Business
Services) because none of these buckets has a well-defined economic profile
that maps cleanly to the existing scoring adjustments.

**d0f0eb2** — `fix: add quality_compounder archetype branch to Stage 05 debate prompts`
Stage 05 bull and bear prompts had explicit branches for long_term_compounder
and deep_value but no quality_compounder branch. Any ticker screened as
quality_compounder fell through to a default that was not calibrated for the
archetype's criteria (moat durability, pricing power, FCF consistency, premium
justified by capital returns rather than growth). Bull and bear analysts now
receive archetype-specific framing for all three archetypes.

**8dd74c1** — `fix: resolve archetype ties deterministically, remove "either"`
Stage 01 could emit archetype="either" when a ticker's signals matched two
archetypes equally. "either" propagated through all seven stages with no
archetype-specific handling at any stage, producing analytically incoherent
output. This fix resolves ties deterministically to the more conservative
archetype (quality_compounder > long_term_compounder; deep_value is not
involved in ties). "either" is removed from the system entirely.

---

### 2026-05-25/26 Session — Test Run + Fixes

**75e225d** — `docs: update CLAUDE.md — GICS, archetype, and tie-resolution fixes; refresh pending work`
Documentation refresh after the 2026-05-24 session. Recorded the GICS
expansion, tie-resolution, and quality_compounder Stage 05 support. Refreshed
the pending-work list.

**da27c16** — `fix: route real Stage 02 contradictions through to scoring and debate`
The contradiction extractor in Stage 02 writes inter-quarter contradictions to
transcript_cache in duke_cache.db. However, Stage 03 was reading evidence from
the flat JSON files in data/raw/, not from the SQLite cache. This meant
contradictions extracted by Stage 02 were never passed downstream to Stage 04
scoring or Stage 05 debate — the contradiction channel existed in code but
carried no live data. This fix routes the real contradictions from the cache
through to the evidence brief so Stage 05 analysts can engage with them.

Note: the fix is now correctly wired but requires two consecutive Stage 02 runs
on the same ticker before live contradictions appear — the first run populates
transcript_cache, the second run diffs against it.

**546bdf4** — `fix: thread quality_compounder archetype through Stage 06 synthesis`
The Stage 06 synthesizer.py _build_brief() function assembled the Chief Analyst
brief from debate_record, risk_assessment, and price_data — but not from the
analyst_brief, which is where the screening_archetype lives. As a result,
quality_compounder tickers arrived at the Chief Analyst without an archetype
field, causing the Chief Analyst to default to the wrong branch of its
investment philosophy filter. This fix passes the archetype through the
synthesizer pipeline so the Chief Analyst receives it in the brief.

**6d215ee** — `feat: activate Stage 05 Round 2 rebuttals — bull and bear now respond to each other`
Stage 05 Round 2 (cross-feed rebuttals) was scaffolded in code but deactivated
— the rebuttal prompts existed but bull and bear analysts never received each
other's Round 1 positions. This commit activates the cross-feed: Bull R2
receives Bear R1; Bear R2 receives Bull R1. Rebuttals must respond to every
opposing argument. A down-only clamp is enforced in code (Bull R2 score ≤ Bull
R1; Bear R2 score ≥ Bear R1, i.e. less negative) so rebuttals cannot inflate
the Round 1 conviction basis. R2 scores are informational only; debate scores
are computed from R1.

This activation reverses an earlier deliberate decision (backlog item DUKE-13,
2026-05-24) not to implement rebuttals — the original concern being that
adaptive debaters optimizing across rounds shift the debate from independent
evidence toward rhetoric. The reversal is provisional: rebuttal quality —
whether R1→R2 score movement tracks evidence or merely compresses debate
outcomes toward "balanced" — is to be evaluated against the first full
20-ticker run.

**4ea4c75** — `fix: anchor Chief Analyst to screened archetype; record archetype provenance in journal; document two-score distinction`
Three related fixes in one commit:

1. *Archetype anchoring*: The Chief Analyst was free to confirm or reclassify
   the investment archetype without any knowledge of the Stage 01 screened
   value. During the PODD test run, the Chief Analyst reclassified
   deep_value → long_term_compounder without a stated basis, violating the
   philosophy filter. The chief_analyst.md prompt now receives a
   screening_archetype field and is instructed to treat it as an anchor —
   reclassification requires an explicit stated reason.

2. *Archetype provenance in journal*: The Stage 07 decision record now records
   both screening_archetype (Stage 01's fundamental-signal value) and
   investment_archetype (the Chief Analyst's confirmed or reclassified value),
   enabling outcome tracking to distinguish cases where the Chief Analyst
   diverged from Stage 01.

3. *Two-score distinction documented*: Stage 05 produces mechanical
   evidence_score and confidence_score from debate signal weights and clamp
   logic. Stage 06's Chief Analyst produces final_evidence_score and
   final_confidence_score — reasoned narrative numbers reflecting the full
   synthesis (debate outcome, risk officer flags, contention adjudications,
   philosophy fit). The two sets deliberately differ. Chief Analyst scores are
   the ones used in Stage 07 and the journal. Stage 05 scores are preserved in
   the debate record for traceability. This distinction is now documented in
   CLAUDE.md.

**40c366f** — `feat: Architecture B — debate scores business merit only, valuation moves to Chief Analyst entry-price adjudication`
**UNVALIDATED.** Restructures the Stage 05 / Stage 06 division of labor. The
prior design had the debate carry a hybrid mandate — bull defended valuation,
bear's mandatory `valuation_challenge` could elevate its tier to 4 on
valuation alone (Tier 4 path c). An empirical discrimination test (CRM/PTC at
DTS +82.6/+80.9 alongside four tickers at DTS 63–82) found five of six bulls
clustering at exactly +3.0 regardless of evidence strength. Diagnosis: the
bull was self-capped by the bear's mandatory valuation lane that the bull's
tier ladder acknowledged but could not surmount.

Architecture B:
- Stage 05 debate = pure business merit. Bull argues upside / quality;
  bear argues fundamental risk (execution, moat erosion, concentration,
  growth durability). Neither analyst scores valuation. The bear's
  `valuation_challenge` field is removed, along with Step 4 "Address
  Valuation Explicitly" and Tier 4 path (c). The mandatory
  `valuation_rebuttal` (bull R2) and `valuation_defense` (bear R2) are
  also removed.
- Each analyst emits a grounded `scenario_price` — `{price, mechanism,
  grounding}` — representing where the stock goes if their business-merit
  case plays out. Mechanism must cite disclosed inputs (guided EPS ×
  multiple, intrinsic-value math, deceleration × compression). R1-only;
  rebuttals do not emit or revise scenario_price. Same grounding
  discipline as `raised_strengths` / `raised_risks`.
- Stage 06 Chief Analyst = valuation adjudicator. Reads
  `bull_scenario_price` + `bear_scenario_price` + `current_price`,
  computes the up/down ratio at the current price, and emits an entry
  price band using a fixed 2:1 favorable-ratio threshold. New journal
  fields: `entry_price`, `entry_range`, `entry_price_rationale`,
  `current_price_used`. Three output cases — in-band (entry = current),
  above-band (solve for X), and inverted-ordering (bull_scenario ≤
  current → entry = null; the solve-for-X formula does not apply under
  inversion and would produce nonsense numbers, so emit null and state
  the inversion in rationale).

Absorbs the earlier discrimination-thread commits (4478857 Path B, b1404d5
Path B.2). Those addressed rubric anchoring and opponent-decoupling but did
not solve the valuation-asymmetry root cause; Architecture B does. Path B
and Path B.2 are not separately validated.

Score commensurability: bull and bear `score_adjustment` now measure the
same thing — business-merit conviction beyond Layer 4 — on the same ±15
scale with the same evidence-anchored rubric. `PREVAIL_THRESHOLD = 3.5`
and `INCONCLUSIVE_GAP = 12.0` now mean "does the business-merit picture
lean bull or bear", not "does the all-things-considered investability
lean." Valuation is the Chief Analyst's separate downstream computation.

Deep_value bull's Step 2 (Quantify the Discount to Intrinsic Value)
preserved by design — that IS the bull case for deep_value and naturally
becomes the mechanism producing scenario_price. Compounder /
quality_compounder bull lose the "Valuation relative to growth/quality"
paragraphs entirely.

Scope guards: numeric tier ranges, ±15/±10 clamps, PREVAIL/INCONCLUSIVE
thresholds, raised_strengths/raised_risks lanes, Q&A weighting, parser
retry-then-flag, not_computable short-circuit, rebuttal down-only —
all unchanged. No Stage 04 changes.

Validation pending. The Chief Analyst's entry_price computation has
never been exercised end-to-end against real scenario_price inputs.

**a844d3e** — `fix: Stage 06 Chief Analyst — case-1 formula mandatory, case-3 bear-above-current added, recommendation logic prioritizes favorable price math`
**ROLLED BACK in 909b59a.** First attempt to fix Architecture B's
all-watch + case-1 prose-vs-JSON drift. Added a Step-8 case 3 for
bear-above-current (separate from the bull-side inversion case, which
was renumbered to case 4). Rewrote Step 5 enter/watch criteria so that
favorable price math + ≥moderate business merit defaults to
moderate_conviction_enter rather than watch. Made the case-1 mechanical
formula a Hard Constraint. Validation on six tickers showed mixed
results: cases 1 and 3 emitted correct entry/range.low; case 4 (VRT)
regressed — Chief emitted non-null entry despite the unchanged null
Hard Constraint and despite its own rationale stating null; case 2
(NVDA) emitted current_price as entry (case-1-style) with the
case-2 X formula value placed in range.high, producing an inverted
range; case 1 range.high drifted 0.8-2.8% from formula on BSX and PTC.
Recommendation distribution shifted from 6/6 watch to 6/6
moderate_conviction_enter — including VRT case 4 and NVDA case 2 where
the prompt explicitly says watch. The rebalance worked on cases 1 and
3 but bled into cases 2 and 4.

**d378be2** — `fix: Stage 06 Chief Analyst — positive Hard Constraints on cases 2 and 4, anti-drift on case 1 range.high`
**ROLLED BACK in 909b59a.** Second attempt: tightened Hard Constraints
to give cases 2 and 4 explicit positive mechanical structure
(previously case 4 was null-only, case 2 had no Hard Constraint at
all), and added anti-drift language on case 1 range.high. Validation
on the same six tickers showed the tightening backfired across the
board. Case 4 VRT: Chief still emitted numbers, this time $172.75
(exactly the case-2 X formula applied to VRT's bull and bear) despite
the new explicit "If your rationale identifies case 4, the structured
entry_price and entry_range MUST be null — no exceptions" clause.
Case 2 NVDA: same inverted-range field-confusion, no change. Case 1
BSX: entry regressed from $57.78 (= current, correct) to $56.43 (not
matching any formula); range became entry × ±3% (case-2-style applied
to case-1 inputs). Case 1 PTC range.high drift worsened from 2.8%
to 13% off formula. Case 3 CRM: range.high broken — Chief applied
case-1 formula instead of `bull_scenario_price`. Recommendations
became inconsistent: 3 watch + 3 moderate_conviction_enter, but the
wrong tickers in each bucket. Adding more Hard Constraints made the
LLM's four-case formula execution worse, not better.

**909b59a** — `revert: Stage 06 Chief Analyst prompt to 40c366f baseline`
Rolls back both prompt iterations (a844d3e + d378be2). Three prompt
iterations attempted to fix Architecture B's all-watch + mechanical-
field issues by tightening case-formula constraints; each regressed
into a new failure mode. The 40c366f baseline has a known limitation
(all-watch under inconclusive outcomes; case 1 prose-vs-JSON drift
on entry_price) but is a consistent, characterized state. The
follow-up commits introduced inconsistent edge-case behavior that
worsened with each attempt.

Architecture B plumbing remains at HEAD: `AnalystPosition.scenario_price`
dataclass field, Stage 05 schema, position_builder output_format,
analyst prompts (bull/bear/rebuttals) with scenario_price emit and
valuation removal, synthesizer.py current_price + market_cap + 52w
threading, decision_capture.py journal threading for entry_price /
entry_range / entry_price_rationale / current_price_used, Stage 07
schema declarations — all unchanged by the revert. Only the Chief
Analyst prompt was reverted.

Next step (deferred, separate task): move entry-price computation from
LLM to Python. Chief Analyst's role becomes business-merit reasoning +
recommendation off a Python-computed entry-price case; the
deterministic arithmetic (case identification + entry_price /
entry_range formulas) moves into synthesizer.py or a new
entry_price_calculator.py. This finishes Architecture B's design
intent without asking the LLM to execute four-case conditional
arithmetic with field-name discipline, which three iterations
demonstrated it cannot do reliably.

**b5e5d24** — `feat: move entry-price computation to Python (entry_price_calculator); Chief writes recommendation off deterministic band`
Finishes Architecture B's design intent by moving the four-case
entry-price arithmetic out of the Chief Analyst LLM and into a pure
Python module (`pipeline/06_synthesis/entry_price_calculator.py`,
13/13 tests pass). The calculator consumes
bull_scenario_price + bear_scenario_price + current_price +
screening_archetype and returns case_label
(IN_BAND / ABOVE_BAND / BELOW_BEAR / INVERTED / DEGENERATE),
entry_price, entry_range (`{low, high}` object), target_2to1_price
`X = (bull + 2*bear) / 3`, ratio_at_current, archetype_min_rr
(deep_value 2.0 / quality_compounder 1.5 / long_term_compounder 1.2),
price_gate_passed, and a one-line rationale. Wired into Stage 06's
`run.py` pre-Chief; result persists as `synthesis.computed_entry`;
Stage 07's `decision_capture._build_record` reads journal entry
fields from there, not from the Chief output.

The Chief Analyst prompt is slimmed: Step 8 is now read-only ("Read
the Entry-Price Band, no computation"). Step 5 is rewritten as a
matrix on (`price_gate_passed` × business-merit lean) that maps to
the existing recommendation enum:
  gate pass + merit_bull       → ENTER (strong or moderate per a
                                  second test on final_evidence_score
                                  and bull R1)
  gate pass + merit_balanced   → watch
  gate pass + merit_bear       → pass (default); watch only on a
                                  named, credible, management-driven
                                  pivot addressing the bear's core
                                  thesis with at least early evidence
  gate fail + merit_bull       → watch
  gate fail + merit_balanced   → pass
  gate fail + merit_bear       → pass
INVERTED and DEGENERATE case_labels are treated as gate-fail rows
unconditionally — never ENTER.

This removes the all-watch default that the 40c366f baseline produced
under inconclusive debates. Inconclusive + Tier 4 + gate pass now
lands in ENTER, not watch. The Chief no longer emits entry_price,
entry_range, current_price_used, target_2to1_price, ratio_at_current,
price_gate_passed, or archetype_min_rr — Python writes those to the
journal directly. The Chief contributes `recommendation` (matrix
outcome) and `entry_price_rationale` (business-merit prose).

VRT end-to-end validation: bull $222.25 < current $327.46 →
case_label=INVERTED → entry_price=null, target_2to1_price=172.75,
gate_passed=false → recommendation=watch. Journal entry fields all
populated from `synthesis.computed_entry`; Chief omitted the
calculator-supplied number fields per the slimmed schema.

Resolves the iteration cycle a844d3e → d378be2 → 909b59a: the
prompt-level constraints cycle demonstrated that LLM-driven four-case
conditional arithmetic with field-name discipline is unreliable. The
arithmetic is now deterministic Python; the LLM judges only the
recommendation off the resolved band, which is a job it can do.

**a4a5792** — `feat: Debate Moderator drives outcome + weighting (ε=0.5); self-scores demoted to audit-only; Chief lean is a named-override anchor`
The structural cause behind the persistent "all debates resolve
balanced / all-watch under inconclusive" pattern was that the bull and
bear were each scoring their own case in isolation — both routinely
saturated their own conviction (bull at +6/+7, bear at −5/−6), leaving
the R1-net classifier (PREVAIL_THRESHOLD = 3.5, INCONCLUSIVE_GAP =
12.0) systematically over-clustering at BALANCED or INCONCLUSIVE.
Architecture B (40c366f) re-anchored what the analysts argue but did
not change the structural problem: the agents that produced the scores
were not the agents that judged the relative weight of evidence.

This commit adds a neutral evidence referee — the Debate Moderator —
that runs after the two rebuttals. It reads both R1 positions, both R2
rebuttals, and the contentions WITH SELF-SCORES STRIPPED so the
analysts' allocations cannot anchor it. It allocates a fixed pool of
10 points between bull and bear: sum-10 makes the judgment relative
(points denied one side go to the other), and the prompt forces a
direction unless the points are a true near-tie, requiring a single
`decisive_evidence` citation for the leaning side. The Moderator
output also reports a `lean` label, but the system recomputes lean in
code from the two scores so the LLM cannot mint its own "balanced"
escape hatch.

The code-side lean derivation uses an epsilon band of ±0.5 on the
normalised-to-10 score difference (`pipeline/05_debate/run.py:derive_lean`,
kept in sync with `run_moderator_only.py`). Tightened from 1.0 to 0.5
after a 21-ticker Moderator-harness sample showed the wider band
suppressed four real bear-leaning reads (DXCM/FSLR/GEN/PAYX at 5.5/4.5)
and three thin bull reads.

The decision wiring is now:
  outcome label:
    `bull_leans` → `bull_prevails`
    `bear_leans` → `bear_prevails`
    `balanced`   → `balanced`
    null         → `inconclusive` (Moderator parse-failure only)
  weighting (margin-scaled, in `debate_scorer.compute_debate_scores`):
    `winner_w = 0.50 + min(|margin|, 10) / 10 × 0.30`  → 0.50..0.80
    `loser_w  = 1 − winner_w`
    Self-scores still feed `net_score_adjustment` via
    `w_bull × bull_self_adj + w_bear × bear_self_adj`, but the weight
    RATIO is no longer derived from them.
The prior `PREVAIL_THRESHOLD`, `INCONCLUSIVE_GAP`, and
`_PREVAIL_WEIGHTS` are removed. `INCONCLUSIVE` is now a failure state
only — it fires when the Moderator block is missing.

Stage 06's synthesizer threads `merit_lean` / `merit_margin` /
`decisive_evidence` into the Chief Analyst brief. The Chief's Step 5
prompt (`pipeline/05_debate/prompts/chief_analyst.md`) is rewritten so
that `merit_lean` is the business-merit anchor (same status as
`screening_archetype` from 4ea4c75). Overriding the Moderator's lean
requires a NAMED, SPECIFIC reason: a critical contention adjudicated
against the leaning side, a live Risk Officer blocking flag, or a
`philosophy_fit = does_not_fit` downgrade. "The debate was close" and
"merits to both sides" are explicitly invalid overrides. `bull_leans +
gate-pass → ENTER unless a named blocker is stated.` The strong-vs-
moderate split inside the ENTER cell now uses `merit_margin ≥ 4.0`
(Moderator decisiveness) rather than the prior `bull R1 ≥ +6` test,
since R1 self-scores are now audit-only.

Stage 07's `decision_capture._build_record` persists `merit_lean`,
`merit_margin`, and `decisive_evidence` to the journal record, with
schema declarations in `pipeline/07_output/schemas/output.json` and
the moderator block declared in `pipeline/05_debate/schemas/output.json`.

Validated end-to-end on six tickers from the 2026-05-24 shortlist
(VRT long_term_compounder, BSX quality_compounder, CRM
quality_compounder, NVDA long_term_compounder, PODD deep_value, PTC
quality_compounder). All six produced `merit_lean = bull_leans` with
margins 2.0 or 3.0. Distribution: 4 `moderate_conviction_enter` (BSX,
CRM, PODD, PTC) + 2 `watch` (VRT ABOVE_BAND, NVDA INVERTED). Both
watches fired on gate-fail, not on a Chief override of the Moderator's
lean. No `bull_leans + gate-pass` was blocked by a Chief override. The
strong-vs-moderate threshold held everyone at moderate (no margin
cleared 4.0), as designed. The all-watch default from the 40c366f
baseline is gone.

---

### 2026-05-29 Session

**857258a** — `fix: Stage 01 file-handle leak — hoist ThreadPoolExecutor out of per-ticker loop, close yfinance sessions`
Stage 01 was leaking ~6 file descriptors per ticker. The `ulimit -n 8192`
per-terminal workaround was required to survive 500-ticker S&P 500 runs and
the "must fix before unattended/scheduled run" item gated the next full
screen. Diagnosis (read-only sweep) traced the leak to two sources, with
file/DB handles ruled out:

  Type   Slope/ticker  Source
  REG       flat       (sqlite caches close cleanly)
  IPv6      ~3.3       unclosed yfinance sessions
  PIPE      ~2.1       per-iteration ThreadPoolExecutor

Source 1 — `ThreadPoolExecutor(max_workers=1)` was being created inside the
per-ticker loop in `run_screening.py`. On Python 3.14/Darwin, the executor's
internal wakeup pipe FDs lingered until GC even after the `with` block's
`shutdown(wait=True)`. Fixed by hoisting a single executor around the whole
loop. The 20-ticker harness saw zero 30s timeouts in practice, so the
shared `max_workers=1` executor is safe; if a real hang ever occurs, the
queued ticker will time out and surface the problem rather than mask it.

Source 2 — `data_fetcher.fetch_market_data` instantiated `yf.Ticker(...)` for
the primary ticker plus SPY and the sector ETF on every call. Each `Ticker`
carried a `curl_cffi.requests.Session` whose connection pool kept idle HTTPS
sockets alive with no explicit close path. Fixed by binding each `yf.Ticker`
to a local, wrapping the use site in `try / finally`, and calling
`_close_yf_ticker(t)` in the finally clause. A future optimization noted in
a comment is to hoist the SPY + sector-ETF fetches out of the per-ticker
loop entirely (they currently re-fetch per call), but that is a performance
improvement, not a leak fix.

Validation: instrumented `count_fds()` between tickers on a 20-name run.

  Before fix:  154 → 152 → 158 → ... → 253  (slope ~6/ticker, monotonic)
  After fix:   152 → 152 → 152 → ... → 152  (slope 0/ticker, flat)

Full Stage 01 run on 20 tickers at `ulimit -n 256` completed clean
including the transcript prefetch (492 transcripts cached). The
`ulimit -n 8192` guidance in CLAUDE.md and README remains in place as a
belt-and-suspenders safety net but is no longer load-bearing for the
500-ticker screen.

**7ae2272** — `fix: mid-cycle FCF normalization for commodity-cyclicals — peak-cycle FCF no longer reads as durable quality/cheapness (energy-gated)`
EQT (natural-gas E&P) still screened #1 on the S&P 500 harness at 64.6,
even though the commodity-cyclical archetype override (04260c0) had already
force-routed it to deep_value and the advisory FLAG_CYCLICAL_PEAK_RISK was
firing. That earlier entry's "EQT is no longer an open issue" was premature:
the override changed the archetype label and lit a flag, but nothing acted on
the flag, so EQT's peak-cycle free cash flow was still scored as durable.

A read-only diagnose (this session) separated the two suspected causes and
ranked them:
- The gross-profit/depletion path was NOT the active lever. `energy_upstream`
  already disables `gross_margin` (E&P gross profit excludes DD&A/depletion),
  so the inflated margin contributed 0 to EQT's score. Confirmed: EQT's
  mispricing hypothesis carried no gross-margin line.
- The lever was peak-cycle FCF, surfacing in three FCF-derived signals at
  once — VG 96 (P/FCF 9×, the value-trap signature: a cyclical trades cheap on
  peak cash flow precisely because the market prices mean reversion), EQ 61.7
  (FCF/NI), and BQ's fcf_margin. One root cause, three symptoms.

A second read-only check confirmed the data to fix it was already in hand: the
cached EDGAR companyfacts blob holds 15+ years of CFO/CapEx; only `_extract`'s
`n_annual=2` default was truncating it. EQT clean window FY2021–25 FCF
[607, 2065, 1160, 573, 2838]M → 5yr mid-cycle ≈ $1.45B vs a TTM (trailing 4q)
of $4.05B = 2.80× peak. No new fetching, no paid feed (distinct from the
data-blocked DCF/reverse-DCF anchors).

The fix (gated on `is_commodity_cyclical` — the same predicate that
force-routes the archetype and fires the flag, so the flag and the
normalization are now the same event):
- `common/edgar_client.py` `fetch_financials`: `n_annual` 2 → 6 for the
  cash-flow concepts (CFO, capex) only.
- `signal_scorer.py` `_mid_cycle_fcf`: mean of the consecutive clean trailing
  FY window (CapEx present and > 0 — deep history has XBRL concept-switch gaps,
  e.g. EQT CapEx tagged 0 in FY2015), min 3 / max 5 years. Fewer than 3 clean
  years → fall back to TTM and do not normalize.
- `compute_fundamental_metrics`: for cyclicals only, substitute mid-cycle FCF
  into P/FCF, fcf_margin and FCF/NI (which also moves the pfcf-derived
  historical-discount signal). Raw `fcf_ttm` + `mid_cycle_fcf` both kept; the
  mispricing hypothesis discloses "TTM FCF $X vs Nyr mid-cycle $Y (Z× peak)".
- `reason_codes.py`: FLAG_CYCLICAL_PEAK_RISK now fires off `fcf_peak_ratio >
  1.2` (TTM vs mid-cycle), with the old raw-TTM `fcf_margin > 15` proxy as the
  sparse-history fallback so a peak cyclical is never un-flagged.

Validated on the EQT/XOM/CVX/MSFT/NVDA harness:
- EQT 64.6 #1 → 51.2 #4 (NVDA now #1). VG 96 → 82, EQ 61.7 → 33.7,
  P/FCF 9× → 24×. Dethroned. ✓
- MSFT 54.6, all six sub-scores identical — the gate leaves compounders alone.
- NVDA untouched despite a 1.94× FCF peak: it is semiconductor_platform, not a
  commodity cyclical, so the gate correctly ignores a secular grower. This is
  the gate-leak test, and it is the whole safety story.

Two deliberate, documented properties:
- SYMMETRIC (user decision: keep): normalization also RAISED trough cyclicals
  whose TTM FCF sits below mid-cycle (XOM 29.4 → 43.4 at 0.52× peak, CVX
  41.8 → 51.6 at 0.63×). The mid-cycle figure is the honest estimate
  regardless of cycle position; this is "normalize through the cycle," not a
  one-way peak penalty.
- PEG NOT normalized: in this codebase PEG is P/E ÷ revenue-growth
  (earnings-based, no FCF term), so the FCF substitution is mechanically a
  no-op on it. EQT's PEG stayed 0.2× on peak NET INCOME, which is why VG only
  fell 96 → 82 rather than collapsing; EQT was dethroned mainly via EQ and the
  historical-discount signal. Closing the value-trap on VG itself needs
  mid-cycle EARNINGS normalization — recorded as a follow-up.

Why it mattered: the shortlist is the artifact the book actually trades off. A
peak cyclical ranking #1 would have routed a mean-reverting commodity producer
into Stages 02–07 as the top idea. Untested path: the <3-clean-years TTM
fallback was not exercised by live data (all three energy names had a full 5yr
window) — the logic is in place but unverified against a real sparse-history
cyclical.

**1f04754** — `fix: extend commodity-cyclical gate to metals + fertilizer (Gold/Copper/Steel/Aluminum/Other Metals/Ag Inputs); guard mid-cycle FCF against near-zero denominators`
The mid-cycle FCF machinery (7ae2272) was gated on `is_commodity_cyclical`, but
that gate contained energy only. A read-only diagnose of the broader cyclical
universe (metals, chemicals, homebuilders, autos, machinery) found NEM (gold,
at all-time highs) was the live EQT-analog: TTM FCF 3.28× its 5yr mid-cycle,
sitting on the `unknown` profile (the metals GICS strings were on the
deliberately-unmapped list), so its peak-cycle FCF went unnormalized and NEM
screened #1 at 67.1 with the full EQT signature (STRONG_FCF, UNDERVALUED_PEG,
LOW_PFCF, HIGH_EARNINGS_QUALITY).

The diagnose's key structural finding was that the specialty/commodity (and
cyclical/secular) line cuts THROUGH single yfinance GICS industry strings, so a
GICS-only gate can only safely sweep the strings confirmed clean:
- `Specialty Chemicals` is shared by genuine specialty (LIN/SHW/ECL/APD/PPG —
  pricing power) and commodity producers (LYB petrochemicals, ALB lithium).
- `Auto Manufacturers` is shared by cyclical (F/GM) and secular (TSLA).
- Metals/fertilizer strings (Gold/Copper/Steel/Aluminum/Other Industrial Metals
  & Mining/Agricultural Inputs) are clean — no specialty hides under them.

This pass swept only the clean strings. Two surgical changes:

1. New `commodity_cyclical` economic profile, mirroring energy_upstream:
   `gross_margin` disabled (metals/fertilizer share E&P's extractive cost
   structure — EDGAR gross profit excludes depletion/DD&A, so gross margin
   isn't comparable), multipliers gm 0.55 / rev 0.50 / fcf 0.55. The six clean
   GICS strings route to it, and it is added to `commodity_cyclical_profiles`
   so the mid-cycle FCF normalization + FLAG_CYCLICAL_PEAK_RISK fire.

2. Mid-cycle FCF denominator guard in `_mid_cycle_fcf`: returns None (→ TTM
   fallback, no normalization) when the clean-year mean is <= 0, below a
   revenue floor (< 0.01 × rev_ttm), or a meaningless boom/bust straddle. A
   near-zero denominator makes P/FCF and FCF/NI explode or flip sign — worse
   than not normalizing. ALB (lithium, 5yr mean ≈ −$0.1B → −10.25× ratio)
   exposed this; it was latent in the energy fix too, just never triggered.

Validated (NEM FCX NUE STLD MOS CF EQT MSFT NVDA DOW CE F DHI ALB):
- NEM 67.1 #1 → 49.1 FAIL. commodity_cyclical; VG 76 → 50, EQ 70 → 42, P/FCF
  13× → 42× (TTM $9.24B vs 5yr mid-cycle $2.81B, 3.28× peak); flag fires.
- Trough metals rise symmetrically (FCX 24.5 → 28.5, NUE 25.0 → 44.9, STLD
  26.8 → 39.8); CF and MOS, at cyclical lows, normalize up and now pass. Same
  approved symmetric behavior as XOM/CVX — the gate can lift a depressed
  commodity name into the shortlist on its mid-cycle economics.
- Held strings unchanged: DOW, CE (Chemicals), F (Auto), DHI (Residential
  Construction) all still industrial_manufacturer, identical sub-scores — the
  mapping did not leak beyond the six intended strings.
- Non-cyclicals + energy regression-clean: MSFT 54.6, NVDA 77.2 (composite),
  EQT 51.2 — unchanged.
- ALB guard: routes to industrial_manufacturer (Specialty Chemicals is held,
  not swept) and `_mid_cycle_fcf` returns None → TTM fallback, no garbage.

Still pending (per-ticker passes, deliberately out of scope): chemicals
(DOW/CE verification + LYB/ALB ticker_overrides) and Bucket 2
(homebuilders/autos/machinery/building materials, each needing a
cyclical-vs-secular call and a TSLA-style exclusion). The gate remains the
safety boundary — only GICS-confirmed-clean strings are swept per pass.

---

## Open Issues (as of 2026-05-29; Architecture B re-scoped 2026-05-28; Chief prompt reverted 2026-05-28; entry-price refactor landed 2026-05-28; Debate Moderator added 2026-05-28; Stage 01 FD leak fixed 2026-05-29)

**Must fix before relying on shortlist**

- ~~Stage 01 file-handle leak~~ — **FIXED.** See chronological entry below.
  ~6 FDs/ticker leak (3.3 sockets + 2.1 pipes) traced to a per-iteration
  `ThreadPoolExecutor` and unclosed `yf.Ticker.session` urllib3 pools.
  Resolved; post-fix per-ticker slope is ~0. `ulimit -n 8192` guidance is
  kept as a safety net but no longer load-bearing.

**Pending**

- ~~**NEW TOP PRIORITY — Entry-price computation in Python.**~~
  **DONE in `b5e5d24`.** New module
  `pipeline/06_synthesis/entry_price_calculator.py` (pure function,
  13/13 tests pass) consumes bull_scenario_price + bear_scenario_price
  + current_price + screening_archetype and returns case_label
  (IN_BAND / ABOVE_BAND / BELOW_BEAR / INVERTED / DEGENERATE) +
  entry_price + entry_range + ratio_at_current + price_gate_passed +
  archetype_min_rr + target_2to1_price + rationale. Wired into
  `synthesizer`/`run.py` before the Chief LLM call; result persists
  as `synthesis.computed_entry`; Stage 07 `decision_capture._build_record`
  reads entry-price numbers from there and writes them to the journal
  top-level. The Chief Analyst prompt is slimmed: Step 8 is now
  read-only ("Read the Entry-Price Band, no computation"); Step 5 is
  a matrix on (price_gate_passed × business-merit lean) that maps to
  the existing enum, replacing the all-watch default under
  inconclusive outcomes. The Chief no longer emits entry_price,
  entry_range, current_price_used, target_2to1_price,
  ratio_at_current, price_gate_passed, or archetype_min_rr — it
  writes only `recommendation` + `entry_price_rationale` (business-
  merit prose) on the entry-price side. VRT end-to-end validated:
  INVERTED case → entry_price=null, target_2to1=$172.75,
  gate_passed=false, rec=watch (correct matrix outcome).

- Architecture B status: committed (40c366f). Plumbing validated end-
  to-end. Entry-price computation refactored to Python in b5e5d24.
  Three prompt iterations (a844d3e, d378be2 → 909b59a revert)
  attempted to fix recommendation/field-mechanics at the prompt level
  before the refactor; each regressed and was rolled back. The Chief
  prompt now drives recommendation off the deterministic band rather
  than computing it.

- SYF misclassification: GICS "Credit Services" maps to payments_network, but
  SYF is a consumer-credit lender. Needs a banking ticker_override (same
  pattern as COF).

- Electronic Components profile gap: APH, TEL, GLW route to unknown/neutral.
  The bucket warrants a dedicated economic profile — without it, DTS scores
  for electronic components names are suppressed by neutral multipliers.

- Expand commodity-cyclical classification — per-ticker passes still pending.
  Done: energy (7ae2272) and metals & mining + fertilizer (1f04754 — new
  `commodity_cyclical` profile; Gold/Copper/Steel/Aluminum/Other Industrial
  Metals & Mining/Agricultural Inputs). Still OUT of the gate, each needing
  its own review because GICS cannot make the call cleanly:
    - Chemicals: `Chemicals` (DOW, CE) not yet verified free of specialty
      names; `Specialty Chemicals` collides commodity (LYB petrochem, ALB
      lithium) with genuine specialty (LIN/SHW/ECL/APD/PPG, pricing power) →
      needs ticker_overrides, not a GICS sweep.
    - Bucket 2 (homebuilders/residential construction, autos, heavy machinery,
      building materials): cyclical but not pure price-takers; each needs a
      cyclical-vs-secular call and a TSLA-style exclusion (`Auto Manufacturers`
      collides F/GM with secular TSLA).
  A false positive would wrongly normalize a secular grower (cf. NVDA at 1.94×
  FCF peak, correctly left alone). The residual risk lives here — the gate is
  the safety boundary, so only GICS-confirmed-clean strings are swept per pass.

- Mid-cycle EARNINGS normalization (follow-up to 7ae2272): PEG is
  earnings-based (P/E ÷ rev-growth), so the FCF normalization is a no-op on it
  — a peak cyclical's PEG stays cheap on peak net income, leaving the VG
  signal partially saturated. Closing the value-trap on VG itself needs
  mid-cycle earnings, parallel to the mid-cycle FCF approach.

- Contradiction channel wired but never validated with live data. Requires two
  consecutive Stage 02 runs on the same ticker (first run populates
  transcript_cache; second run diffs against it and produces contradictions).

- ~~Test-run debate outcomes: all four test-run syntheses (CRM, NVDA, PODD,
  APH — 2026-05-26) resolved "balanced". May indicate debate scoring is
  systematically underpowered or that high-quality S&P 500 names genuinely
  produce ambiguous evidence. Worth reviewing after 10+ ticker runs.~~
  **Resolved by the Debate Moderator (a4a5792).** Architecture B (40c366f)
  re-anchored what the analysts argue but left the structural problem
  in place — bull and bear each scored their own case in isolation and
  both saturated their own conviction. The Moderator does the relative
  judgment the self-scorers structurally cannot. Validated on six
  tickers: 4 ENTER + 2 watch (both gate-fail), no all-watch / all-
  balanced clustering. Self-scores demoted to audit-only; outcome and
  weighting now driven by Moderator.lean + Moderator.margin.

- Stage 04 fundamentals wiring deferred to V2: signal thresholds and economic
  profiles are live, but forward guidance-vs-consensus comparison needs a
  dedicated data source before Stage 04 can score it.

- V1.5 — native financial-company signals: banking/insurer/REIT profiles
  currently work by disabling misleading signals (FCF margin, gross margin)
  rather than scoring native metrics (NIM, ROE, FFO, combined ratio). Candidate
  new profiles: health_insurer, it_services, commodity_cyclical.

- Rebuttal activation (6d215ee) reverses the earlier DUKE-13 decision against
  Round 2 rebuttals. With self-scores now audit-only (a4a5792), the question
  of whether R1→R2 movement tracks evidence is no longer load-bearing for
  the outcome — but R2 content still flows to the Moderator (it reads both
  rebuttals), so rebuttal quality continues to affect the verdict
  indirectly through what evidence survives. Worth evaluating against the
  first full 20-ticker Moderator-driven run.

- DUKE-16: Multi-period trend analysis
- DUKE-19: TAM share-gain and ROIC signals

- DCF valuation anchor (V2, data-blocked): intrinsic-value entry price via
  discounted cash flow. Requires multi-year cash-flow projections DUKE does
  not generate plus a paid fundamentals feed (previously declined). Future
  option pending data.

- Reverse-DCF / expectations anchor (V2, data-blocked): compute the
  growth/margin trajectory implied by current price and judge achievability.
  Best-fit for priced-for-perfection names. Same data dependency as DCF
  valuation anchor.

- yfinance plumbing + multiple-check panel: Architecture B's Chief Analyst
  anchors entry price against `current_price` from the existing screening
  raw file. The follow-up that was deliberately deferred from Architecture B
  is a yfinance-backed daily-current-price refresh (so the Chief sees a
  current price that isn't days old) plus a "multiple-check panel" that
  reads trailing/forward P/E and peer-multiple distributions, giving the
  Chief a sanity check on the analysts' scenario-price multiples. Required
  before V2 valuation anchors (DCF, reverse-DCF) become useful.

- Thread `debate_invalid` to journal top-level: when Round 1 parse-failure
  produces an `outcome: "not_computable"` debate record (7b33f34), the
  flag lives in the source debate file and in
  `chief_analyst_output.metadata.debate_outcome_used` but does not appear
  at the journal record's top level. A casual reader of the journal sees
  a plausible-looking `watch` recommendation without the failure-mode
  signal. Minimal fix: thread `debate_invalid` from the synthesis source
  through `decision_capture._build_record`, parallel to the
  `philosophy_fit_notes` / `entry_price` patterns. Cosmetic, not
  load-bearing — the safety net itself works.

**Do last**

- DUKE-17: Master orchestrator duke.py
- Sector z-score upgrade (needs 500-ticker data)
