# DUKE Architecture

## Stage Map

Stage 01 — Fundamental Screener
  Job: Filter 3,000+ stocks to ~20 shortlisted tickers
  Input: Universe of tickers
  Output: Ranked shortlist with archetype labels
  Tools: SEC EDGAR, Yahoo Finance
  Rule: Quantitative only. No LLM.

Stage 02 — Evidence Acquisition
  Job: Gather all primary source material per ticker
  Input: Ticker + archetype from Stage 01
  Output: Raw evidence packet
  Tools: SEC EDGAR (10-K, 10-Q, 8-K), transcript
         fetcher, Perplexity discovery, quote
         extractor, evidence validator
  Rule: Acquire and validate. No interpretation.
        No truncation of primary sources.
        Stage 02 preserves. Stage 03 compresses.

Stage 03 — Evidence Refinery
  Job: Compress raw evidence into analyst brief
  Input: Raw evidence packet from Stage 02
  Output: Structured analyst brief
  Tools: Deterministic scoring only. No LLM.
  Rule: Rank, filter, budget, organize.
        Enforce evidence budgets:
          management_quotes: max 8
          filing_quotes: max 8
          external_bull: max 4
          external_bear: max 4
          uncertainties: max 3
        Tag coverage gaps. Tag source limitations.
        Items beyond budget stay in raw packet
        but do not enter analyst brief.

Stage 04 — Scoring
  Job: Score each ticker on quantitative metrics
  Input: Financial data + archetype weights
  Output: Numeric scores per dimension
  Tools: Deterministic math. No LLM.
  Rule: Pure quantitative. No narrative.

Stage 05 — Analyst Debate
  Job: Three independent analysts reason from brief
  Input: Analyst brief from Stage 03
  Output: Bull case, Bear case, Risk assessment
  Tools: Claude (one call per analyst role)
  Analysts:
    Bull Analyst: strongest case for buying
    Bear Analyst: strongest case against
    Risk Officer: what could go wrong even if
                  bull case is right
  Rule: Each analyst sees the same brief.
        Each call is independent.
        No analyst sees another's output.

Stage 06 — Synthesis
  Job: Chief Analyst produces final recommendation
  Input: Bull case + Bear case + Risk assessment
  Output: Investment recommendation with conviction
  Tools: Claude (one call)
  Rule: Must explicitly address the bear case.
        Must quantify conviction (High/Med/Low).
        Must list top 3 risks even if bullish.

Stage 07 — Output
  Job: Format final output for consumption
  Input: Recommendation from Stage 06
  Output: Structured report per ticker
  Tools: Formatting only
  Rule: No new analysis. Full evidence lineage.

## Core Design Principles

1. Stage 02 preserves. Stage 03 compresses.
   Never truncate primary source material in Stage 02.

2. Evidence integrity over convenience.
   Every quote must be verbatim-validated against
   its source document before entering the pipeline.

3. Separation of concerns.
   Acquisition (02) ≠ Compression (03) ≠
   Reasoning (05) ≠ Synthesis (06)

4. Source hierarchy (source_priority field):
   primary_sec > official_company_material >
   external_discovery > analyst_commentary

5. Symmetric evidence acquisition.
   Six discovery query types: bear_case, bull_case,
   competitive_risk, competitive_advantage,
   sector_risk, sector_opportunity.
   No pre-loading of bull or bear bias.
