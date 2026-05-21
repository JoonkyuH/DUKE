# DUKE Archetype Rationale

## Purpose

This document records the investment edge claim for each 
screening archetype. Each archetype must answer four 
questions to be considered active:

1. What specific inefficiency does it exploit?
2. Who is on the other side of the trade, and why are 
   they selling for non-fundamental reasons?
3. What does the screener do versus what do the analyst 
   stages do?
4. What would make the thesis wrong — and does the 
   falsification condition work on names other than 
   the obvious one?

An archetype that cannot sustain credible answers to all 
four gets reworked or cut. This document exists to 
interrogate the weights, not justify them.

---

## Screener vs. Analyst Boundary

This boundary applies to all archetypes and is stated 
once here rather than repeated inside each section.

The screener finds quality businesses at non-peak prices. 
Stage 01 uses quantitative signals from EDGAR and Yahoo 
Finance — revenue growth, margins, ROIC proxies, FCF 
conversion, valuation ratios. It cannot make qualitative 
judgments about whether a headwind is cyclical or 
structural, whether a moat is deepening or eroding, or 
whether management's capital allocation will create or 
destroy value. It produces a candidate list, not a 
conviction signal.

The analyst stages adjudicate the thesis. Stages 02-05 
acquire primary source evidence, compress it into an 
analyst brief, and run an adversarial debate. The Bull 
argues the discount is a mispricing. The Bear argues the 
discount is a correct read on structural deterioration. 
The Chief Analyst synthesizes both. This is where the 
actual investment judgment lives.

The screener's job is to make sure the analyst stages are 
looking at the right names. A name that passes the 
screener but fails the analyst debate is correctly 
handled. A name the screener misses entirely is a 
coverage gap. The screener's error rate should be 
measured by coverage gaps, not by how many passing names 
receive buy recommendations.

---

## Cross-Archetype Rules

**Same-market / winner-take-most rule:**
When two shortlisted companies compete in the same market 
with winner-take-most dynamics, DUKE holds the market 
leader only unless there is explicit evidence the market 
bifurcates. NVDA and AMD cannot both be long-term 
compounder holds under a winner-take-most assumption. The 
analyst debate for the challenger must argue either that 
the market bifurcates or that the challenger can displace 
the leader — not simply that the challenger is a good 
business.

**Dual-candidate rule:**
When a name scores within 5 points under two archetypes, 
it is a dual-candidate. The archetype label determines 
which falsification condition the Bear Analyst attacks — 
a mislabeled name gets the wrong bear case. For 
dual-candidates, the Bear Analyst tests both archetypes' 
falsification conditions explicitly. Do not assign a 
dual-candidate to a single archetype by a coin-flip 
score margin.

**Counterparty ranking:**
Not all non-fundamental sellers create equal inefficiency. 
Rank the counterparty type when assessing conviction:

1. Forced mechanical sellers — index rebalancing, 
   mandate-triggered exits at price-insensitive moments. 
   Strongest inefficiency. Seller has no view.
2. Yield and rule-mandate funds — FCF yield floors, 
   dividend payout requirements. Strong inefficiency. 
   Rule-driven exit disconnected from business judgment.
3. Short-horizon sellers — structurally unable to capture 
   a 3-5 year payoff regardless of near-term read. 
   Weakest inefficiency. Still chose to sell this name 
   on this news.

A name being sold primarily by category 1 is a 
higher-conviction setup than one being sold by category 
3. The analyst stage should note which counterparty type 
is dominant.

---

## V1 Known Limitations

**TAM share-gain signal deferred to V1.5.**
The strongest signal for the long-term compounder 
archetype — market growing AND company growing faster 
than market — directly measures share capture and 
survives a bad quarter. V1 proxies this via 3-year CAGR 
and gross margin trend. Until direct TAM-share 
measurement is implemented, the analyst stages carry more 
of the share-gain judgment than the screener does. V1 
long-term compounder output should be treated as a 
candidate list with higher analyst-stage dependence than 
the other archetypes.

**Incremental ROIC not computed in V1.**
V1 cannot distinguish a moat being defended from a moat 
being harvested. The FCF-to-net-income proxy used in V1 
is biased toward harvesters — a company milking a 
depreciating asset base and under-reinvesting produces 
strong FCF relative to net income, which is the IBM 
signature, not a moat signal. V1 quality compounder 
screening therefore rests primarily on gross margin trend 
plus trailing ROIC as a qualifier. The moat-intact 
judgment falls entirely on the analyst stages in V1. V1 
quality compounder output should be treated as a 
candidate list, not a conviction signal, until V1.5 
implements incremental ROIC tracking.

---

## Long-Term Compounder

**What the screener does:**
Identifies businesses with evidence of durable structural 
growth — measured by multi-year revenue CAGR, gross 
margin trajectory, and earnings quality — trading below 
their growth-adjusted fair value. Uses 3-year CAGR and 
gross margin trend as primary signals, not 
current-quarter YoY growth, because the entry opportunity 
appears precisely when near-term growth decelerates and 
mandate-driven sellers exit. A screener gated on >20% 
current growth would fire the same exit trigger as the 
forced sellers it is trying to buy from. Valuation 
measured relative to growth-adjusted fair value (PEG), 
not relative to the stock's own historical multiple.

**What the analyst stages do:**
Answer the central question: is the headwind compressing 
the multiple temporary or structural? The screener finds 
the candidate. The analysts adjudicate whether the 
candidate is a mispricing or a correctly-priced 
deterioration.

**The specific inefficiency:**
Growth-mandate institutional funds exit when YoY revenue 
growth decelerates below their mandate threshold. Index 
rebalancing forces selling when a stock drops a 
market-cap bracket. Risk parity funds mechanically reduce 
equity exposure when volatility spikes. These are 
mandate-driven sellers executing rules rather than views. 
A family office with a 3-5 year horizon and no mandate 
can hold through this selling when the analyst stages 
confirm the structural growth driver is intact.

**Falsification condition:**
The thesis is wrong when the headwind permanently 
compresses the addressable market or destroys the 
competitive moat — not just the next four quarters. 
Intel's manufacturing execution failure was structural 
moat erosion. Meta's iOS privacy impact was a temporary 
headwind on an intact social graph moat. The Bear 
Analyst's primary mandate is to argue the structural 
case, not just list risk factors.

**Mutually exclusive theses — same market rule:**
When two shortlisted companies compete in the same market 
with winner-take-most dynamics, DUKE holds the market 
leader only unless there is explicit evidence the market 
bifurcates. AMD's thesis must argue either that the AI 
accelerator market bifurcates or that AMD can displace 
NVDA — not simply that AMD is a good business.

**Current shortlist names:**
- NVDA: China ban = temporary restriction on intact AI 
  infrastructure TAM, or permanent market loss + 
  open-source commoditization? Central question.
- PLTR: Government budget cycles = temporary friction on 
  a durable data platform, or civilian AI alternatives 
  making the approach obsolete?
- AMD: AI accelerator market large enough for two 
  winners, or winner-take-most with NVDA dominant? 
  Bear must argue this explicitly.
- GOOGL: LLM disruption = temporary search adjustment 
  on a durable advertising moat, or structural revenue 
  compression?

**Known limitations (V1):**
TAM share-gain signal deferred to V1.5. V1 screener 
approximates share capture via CAGR and margin trend; 
direct TAM-share measurement deferred — until then, 
analyst stages carry more share-gain judgment. When a 
name scores within 5 points under both long-term 
compounder and quality compounder, Bear tests both 
falsification conditions.

---

## Quality Compounder

**What the screener does:**
Identifies businesses with evidence of durable 
competitive moats — measured by incremental ROIC, 
reinvestment intensity, and gross margin trend — at 
moderate growth rates. Trailing ROIC is a qualifying 
signal only. A screener gated on trailing ROIC alone 
shares IBM's blind spot: high trailing ROIC is precisely 
what a moat-eroding business posts as it stops 
reinvesting.

Three screener signals that survive moat erosion:

**Incremental ROIC** — return on capital invested in 
last 1-3 years. Average ROIC is dominated by legacy 
assets; incremental ROIC tells you whether new dollars 
still earn the spread.

**Reinvestment intensity** — R&D plus capex as % of 
revenue, trending stable or rising. High trailing ROIC 
with collapsing reinvestment is the IBM signature.

**Gross margin trend** — moat erosion shows up in 
margins before ROIC. Sustained >50% gross margin with 
stable/improving trend is the primary qualitative signal.

**What the analyst stages do:**
Answer whether the moat is still intact and how long the 
above-cost return runway extends. The screener identifies 
candidates. The analysts adjudicate duration.

**The specific inefficiency:**
The market systematically undervalues the duration of 
above-cost returns. Standard DCF models truncate at 
5-10 years and assign terminal value assuming reversion 
to cost of capital. When a business has a genuinely 
durable moat, the actual return runway is longer. The 
mispricing is about duration, not current earnings.

A secondary inefficiency applies to moat-defending 
investment cycles — capex and R&D that depress near-term 
FCF while strengthening an existing competitive position, 
not expanding TAM. AAPL's Apple Silicon and AVGO's 
VMware integration are moat-defending cycles. This is 
distinct from long-term compounder: the investment 
defends an existing moat, does not expand into new 
market.

**Who is on the other side — ranked:**
1. Forced mechanical sellers (strongest) — index 
   rebalancing, price-insensitive. Strongest inefficiency.
2. Yield and mandate funds (strong) — FCF yield floors, 
   dividend payout requirements. Rule-driven exit.
3. Short-horizon sellers (weakest) — structurally unable 
   to hold through a 3-5 year moat-deepening cycle. 
   Time-horizon constraint, not pure mandate. Weakest 
   inefficiency — conviction should be lower when this 
   is the primary seller type.

**How this differs from long-term compounder:**
Long-term compounder bets on TAM expansion. Quality 
compounder bets on moat duration. The investment-cycle 
inefficiency belongs in quality compounder only when the 
cycle is moat-defending. When the cycle is 
moat-expanding, it belongs in long-term compounder. 
AAPL's Apple Silicon is moat-defending. MSFT's Azure 
buildout is moat-expanding.

**Falsification condition:**
The thesis is wrong when ROIC mean-reverts toward cost 
of capital. IBM is the canonical failure — high ROIC 
narrative sustained long after pricing power eroded. The 
tell was declining gross margins and collapsing 
reinvestment intensity, both observable before ROIC 
moved.

**The Bear Analyst's specific test:** Is this investment 
deepening the moat or paying rent on it? Management 
describes all capex as strategic. The distinction: does 
the investment widen the competitive gap or merely 
prevent falling behind? A treadmill that every competitor 
must also run compresses long-run returns even when it 
looks like moat defense in the MD&A. The AAPL question: 
is Apple Silicon widening the gap over Android, or is it 
table stakes every phone maker now funds?

**MSFT — dual-candidate:**
Azure/Copilot = TAM-expansion = long-term compounder 
thesis. Office/Teams moat duration = quality compounder 
thesis. Bear tests both falsification conditions.

**Current shortlist names:**
- MSFT: Dual-candidate. Bear tests both.
- AAPL: Apple Silicon moat-deepening or moat-renting? 
  Services gross margin sustaining ROIC above 100%, or 
  hardware cycle dependence returning?
- AVGO: VMware integration moat-defending or 
  moat-renting? Near-term FCF compression while 
  infrastructure position strengthens, or acquisition 
  complexity permanently diluting incremental ROIC?

**Known limitations (V1):**
Incremental ROIC not computed. V1 proxies via earnings 
quality score and FCF-to-net-income ratio. FCF-to-NI is 
biased toward harvesters — IBM posted strong FCF-to-NI 
while dying. V1 quality compounder screening rests 
primarily on gross margin trend plus trailing ROIC as 
qualifier. Moat-intact judgment falls entirely on analyst 
stages in V1. Treat as candidate list, not conviction 
signal, until V1.5.

---

## Deep Value — Not Yet Active

Deep value screens for mean-reversion candidates: 
businesses trading below tangible book value or at 
trough-cycle earnings multiples where the discount 
implies permanent impairment the evidence does not 
support. The central bet is price normalization.

This archetype requires a different universe — 
financials, energy, industrials, real estate at cycle 
lows — and different screener signals than the current 
quality-oriented screen produces. It also requires 
different analyst prompts: the Bear argues the business 
is structurally impaired and reversion will not occur; 
the Bull argues the discount is excessive relative to 
tangible asset value or normalized earnings power.

No deep value candidates surfaced from the current 
S&P 500 run. Writing the rationale without real candidate 
names would produce exactly what this document exists to 
prevent — a plausible-sounding edge claim that has never 
been pressured against a real name. The rationale will 
be written when real candidates exist to test it against.

**Activation trigger:** Universe expansion into sectors 
where genuine deep value candidates exist, or a market 
dislocation that produces such candidates in the current 
universe. When deep value names surface from Stage 01, 
open this document and write the full four-question 
rationale against those names before running them 
through Stages 02-05.

**Explicit decision:** Deep value archetype is defined 
in the screener weight framework but produces no 
shortlisted candidates from the current S&P 500 quality 
universe. This is not an oversight.

---

## Planned Archetypes — Not Yet Active

**Catalyst / Special Situation**
Deferred until after V1 pipeline is complete. Requires 
new data sources (8-K Item 1.01, DEF 14A, short interest 
data), new Perplexity query type (catalyst_event), and 
new screener weight set. Rationale will be written when 
the archetype is built into Stage 01 and tested against 
real candidate names. The SpaceX/TSLA situation is the 
motivating example — DUKE cannot confirm unannounced 
catalysts from primary sources; the system will correctly 
show catalyst_map: [] until something is filed.
