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

---

## Open Issues (as of 2026-05-26)

**Must fix before relying on shortlist**

- Stage 01 file-handle leak: Stage 01 does not release file/DB handles between
  tickers. Worked around with `ulimit -n 8192` per-terminal. Must be fixed
  before any unattended or scheduled run.

**Pending**

- SYF misclassification: GICS "Credit Services" maps to payments_network, but
  SYF is a consumer-credit lender. Needs a banking ticker_override (same
  pattern as COF).

- Electronic Components profile gap: APH, TEL, GLW route to unknown/neutral.
  The bucket warrants a dedicated economic profile — without it, DTS scores
  for electronic components names are suppressed by neutral multipliers.

- Contradiction channel wired but never validated with live data. Requires two
  consecutive Stage 02 runs on the same ticker (first run populates
  transcript_cache; second run diffs against it and produces contradictions).

- Test-run debate outcomes: all four test-run syntheses (CRM, NVDA, PODD, APH
  — 2026-05-26) resolved "balanced". May indicate debate scoring is
  systematically underpowered or that high-quality S&P 500 names genuinely
  produce ambiguous evidence. Worth reviewing after 10+ ticker runs.

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

**Do last**

- DUKE-17: Master orchestrator duke.py
- Sector z-score upgrade (needs 500-ticker data)
