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

---

## Open Issues (as of 2026-05-26; Architecture B re-scoped 2026-05-28; Chief prompt reverted 2026-05-28; entry-price refactor landed 2026-05-28)

**Must fix before relying on shortlist**

- Stage 01 file-handle leak: Stage 01 does not release file/DB handles between
  tickers. Worked around with `ulimit -n 8192` per-terminal. Must be fixed
  before any unattended or scheduled run.

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

- Contradiction channel wired but never validated with live data. Requires two
  consecutive Stage 02 runs on the same ticker (first run populates
  transcript_cache; second run diffs against it and produces contradictions).

- ~~Test-run debate outcomes: all four test-run syntheses (CRM, NVDA, PODD,
  APH — 2026-05-26) resolved "balanced". May indicate debate scoring is
  systematically underpowered or that high-quality S&P 500 names genuinely
  produce ambiguous evidence. Worth reviewing after 10+ ticker runs.~~
  **Superseded by Architecture B (40c366f).** The discrimination thread
  (Path B 4478857 → Path B.2 b1404d5 → Architecture B 40c366f) absorbed
  this concern. b1404d5 is not separately validated; its rubric changes
  carried into Architecture B. Validation of business-merit
  discrimination + the new entry-price adjudication is pending the next
  re-run.

- Stage 04 fundamentals wiring deferred to V2: signal thresholds and economic
  profiles are live, but forward guidance-vs-consensus comparison needs a
  dedicated data source before Stage 04 can score it.

- V1.5 — native financial-company signals: banking/insurer/REIT profiles
  currently work by disabling misleading signals (FCF margin, gross margin)
  rather than scoring native metrics (NIM, ROE, FFO, combined ratio). Candidate
  new profiles: health_insurer, it_services, commodity_cyclical.

- Rebuttal activation (6d215ee) reverses the earlier DUKE-13 decision against
  Round 2 rebuttals. Evaluate whether R1→R2 movement tracks evidence or merely
  compresses debate outcomes toward "balanced" — assess against the first
  20-ticker run. Related to the "all test-run debates resolved balanced" item
  above.

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
