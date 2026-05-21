# DUKE Stage 05 — Analyst Debate

## What This Stage Is

Stage 05 is one stage. It takes one input contract and
emits one output contract. Internally it runs five
prompts across two rounds. The internal structure does
not make it multiple stages — a stage boundary in DUKE
is where the data contract changes, and Stage 05 has one
contract in and one contract out.

Input contract: the Stage 03 analyst brief plus the
Stage 04 score.
Output contract: six analyst outputs, passed to the
Stage 06 Chief Analyst.

## Orchestration

Round 1 — three parallel, independent calls. Bull
Analyst, Bear Analyst, Risk Officer. No cross-visibility:
none of the three sees another's output. Independence is
a property of the design and is enforced by the three
being co-equal parallel calls that share an input and
cannot see each other.

Round 2 — two calls. Bull rebuttal and Bear rebuttal.
Each sees only the other analyst's Round 1 output. The
Risk Officer is not invoked in Round 2.

The round cap is one. Hard. There is no Round 3. A
single rebuttal round forces the clash between Bull and
Bear; a second round would manufacture convergence
between two instances of the same model.

The Stage 06 Chief Analyst receives all six outputs:
Bull Round 1, Bear Round 1, Risk Officer, Bull rebuttal,
Bear rebuttal — and reconciles them.

## The Five Prompts

### bull_round1
Three sections. Section 1 Bull Case — argues the
archetype's falsification condition does NOT hold, every
claim cites an evidence_id, states what would falsify the
bull thesis, fenced from the score's bearish items.
Section 2 Evidence Score Observation — forensic not
argumentative; the admissible unit is item-level
weight-versus-outcome reasoning; no canonical move; may
conclude the score is substantially correct. Section 3
Conviction — STRONG / MODERATE / WEAK / NO-CASE, binding
two-direction consistency rule: a favorable Section 2 is
necessary but not sufficient for STRONG.
Inputs: brief, Stage 04 score, scoped falsification
condition.

### bear_round1
Deliberate mirror of the Bull, not a sign-flip. Section 1
is structural-claim-THEN-reverse-DCF-derivation
conditioned on the structural claim. The derivation is in
relative form (company multiple versus a fixed,
upstream-computed peer median) with no discount rate. The
valuation finding is DERIVED, never selected, as one of:
priced-against-negation, compensation-absent,
genuinely-cheap. Missing-data branch caps conviction at
MODERATE unconditionally. Neither-resolves branch: if no
structural claim is established, the valuation step does
not run. Section 2 inverted question — what the score
FAILS to capture. Coasting fence — restating the score is
inadmissible. Section 3 — GENUINELY-CHEAP denies STRONG;
conviction gate requires the structural claim decisively
established AND the multiple not low enough to compensate.
Inputs: brief, Stage 04 score, scoped falsification
condition, valuation_inputs (company multiple, peer
median, historical range).

### risk_officer
Deliberately not a mirror. No score critique, no
falsification burden, no conviction. Inputs: brief, Stage
04 score, archetype label as calibration context (NOT the
falsification condition), thesis-invalidation conditions.
Does NOT see Bull or Bear output. Output: a risk
assessment, a sizing constraint (NORMAL / REDUCED / ZERO
— a constraint, not a percentage), and a three-tier
verdict. Four-test veto bar: thesis-independent, binary,
unmanageable-by-sizing, downside-skewed — with the
explicit test-3/test-4 interaction (material upside does
not lift a veto if sizing cannot rescue the downside).
Risk Officer judges payoff shape, never probability. A
veto is an escalated entry in the risk assessment, never
free-floating. Honesty floor: NO-TRADE-KILLING-RISK is a
fully valid verdict. Every veto carries a structured
four-field reassessment_trigger — detection of a filing
event triggers re-evaluation and never by itself lifts
the veto.

### bull_rebuttal and bear_rebuttal
A rebuttal is not a fresh case. No new evidence — only
the other side's reading of the same brief. Part 1:
point-by-point engagement, each opposing claim classified
DEFEATED / WEAKENED / STANDS, citing the evidence_id the
claim rested on. Part 2: conviction, down-only. Round 1
conviction is a categorical ceiling; the floor is
NO-CASE. Three branches each with a stated reason. The
classification-conviction consistency rule binds: if a
load-bearing opposing claim is conceded DEFEATED or
WEAKENED, conviction must move down. Both conviction
numbers sit in one object so round_2 <= round_1 is
locally enforceable. The bear rebuttal carries a
concession-propagation note — a concession on the
structural leg propagates to the valuation leg; the Bull
has no equivalent because it has no two-leg structure.

## Gradeable Outputs

Every Stage 05 prompt emits horizon-tagged falsifiable
predictions. The Bull and Bear emit learning_hooks; the
Risk Officer emits risk_track_record_hooks. Each hook is
tagged 90, 180, or 365 days. Stage 05 outputs carry
gradeable predictions by design — this is the hook the
recommendation track-record system grabs later.

## Validation (Backlog — Not Yet Built)

Stage 05 analyst-output validation, deterministic
post-processing: every evidence_id cited by any analyst
must exist in the brief that was passed to that analyst.
Nested within it, a rebuttal-specific check: if any
rebuttal entry is classified DEFEATED or WEAKENED, the
conviction movement must be "down". This is the
enforcement teeth the classification-conviction
consistency rule otherwise lacks.

## Status

Stage 05 design is locked. The five prompt files —
bull_round1, bear_round1, risk_officer, bull_rebuttal,
bear_rebuttal — are to be created under
pipeline/05_debate/prompts/. No further design work on
Stage 05 until the Stage 01 screener backtest is run and
read.
