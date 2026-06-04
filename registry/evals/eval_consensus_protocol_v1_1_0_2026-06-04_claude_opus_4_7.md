# Eval — consensus_protocol@1.1.0 · claude-opus-4-7 · 2026-06-04

**Prompt under test:** consensus_protocol@1.1.0
**Date:** 2026-06-04
**Directive:** registry/evals/strategiai_directive.md
**Model:** claude-opus-4-7
**Eval ID:** eval_consensus_protocol_v1_1_0_2026-06-04_claude_opus_4_7

## Response

## BRIEF

### Step 0 — Input Validation

The directive contains both arithmetic and definitional claims that require checking before deliberation.

**(a) Arithmetic check.** The directive supplies three load-bearing numbers: $49/month Starter tier, 75 queries/month included, and $0.04–$0.06 cost per query at MVP launch (raw Grok pricing). It then asserts "gross margin is negative for the first ~6 months" on the Starter tier.

Reconciling these:
- Revenue per query = $49 ÷ 75 = **$0.653**
- COGS per query (as stated) = $0.04–$0.06
- COGS / Revenue = **6.1%–9.2%**
- Implied inference gross margin = **~91%–94%, strongly positive**

The "negative gross margin" claim does not reconcile with the supplied per-query figures. By a factor of ~10x, the Starter tier should be one of the most profitable consumer-SaaS unit economics on record at the supplied numbers, not negative.

**(b) Definitional check.** The word "query" is doing two jobs in the directive. In the pricing claim ("75 queries/mo"), a query is a user-facing request. In the COGS claim ("$0.04–$0.06 per query, raw Grok pricing"), a query appears to be a single model API call. For a strategic-advice product (the stated category), these two definitions are almost certainly not the same unit.

**(c) Ambiguity check.** "Raw Grok pricing" is itself ambiguous — Grok ships multiple tiers (Grok 4.1 Fast at roughly $0.005/call; Grok 4 Heavy and reasoning tiers at materially higher rates). The $0.04–$0.06 figure is consistent with a reasoning tier or a multi-call workflow, not with single-call fast-tier inference.

**Inconsistency confirmed.** I will not deliberate against the directive's surface claims as supplied.

**Reconciliation hypotheses (ranked):**

1. **[RECONCILIATION-A: Workflow amplification]** — One user-facing "query" triggers 8–15 model calls (retrieval, planning, multi-step reasoning, critique, synthesis, formatting). For strategic-advice products, agentic workflows of 10+ calls per visible answer are now standard. At 10 calls × $0.04–$0.06 = **$0.40–$0.60 effective COGS per user-facing query**, vs. $0.653 revenue. Gross margin: ~8%–39% at planned utilization, and **genuinely negative once hosting, vector store, retries, support, and payment processing are layered in, and especially negative if users exceed the 75-query allowance via overage absorption or if heavy users drive the average up.** Most likely interpretation.

2. **[RECONCILIATION-B: Reasoning-tier model usage]** — $0.04–$0.06 reflects per-call cost on a reasoning tier (Grok 4 Heavy or equivalent), used because strategic advice requires it. Single-call but expensive. Possible, less likely as sole explanation.

3. **[RECONCILIATION-C: Unlisted COGS]** — Hosting, vector DB, observability, retries, customer support, Stripe fees not included in the $0.04–$0.06. Plausible contributor but unusual phrasing if this were the primary driver.

**[RECONCILIATION: Hypothesis A — workflow amplification — adopted as the operative interpretation. Lanes deliberate against effective COGS of ~$0.40–$0.60 per user-facing query, yielding thin-to-negative gross margin on the Starter tier at MVP-stage volumes.]** Lanes should also flag Hypothesis B/C as alternative scenarios where they materially change a lane's conclusion.

### Step 1 — Restate

**What is actually being decided.** StrategiAI is not really choosing between Paths A/B/C/D. The underlying decision is: *do we tell investors a margin story we cannot yet defend, or do we reframe the company around something we can defend in the next 60 days?* The three paths are tactical expressions of that strategic question.

**Key reconciled facts:**
- Pre-MVP, $0 ARR, 5 months runway on $400K pre-seed [ASSUMPTION: directive-supplied, not independently verifiable]
- Seed target $3.2M at $18M post, contingent on 200+ paying beta users [ASSUMPTION: directive-supplied]
- Starter tier $49 / 75 queries, effective COGS ~$0.40–$0.60/user-facing query at MVP scale [RECONCILED: workflow amplification of ~10x on $0.04–$0.06 per-call pricing]
- Caching/routing efficiency thesis (45–60% gain) requires ~5,000+ active users to function; 200 beta users yields ~3–5% cache hit rate [ASSUMPTION: directive's technical claim, plausible for semantic caching of heterogeneous strategic queries]
- $280K fixed engineering cost to build the efficiency layer [ASSUMPTION: directive-supplied]

**Open questions the directive does not answer:**
- What is the actual per-user-facing-query COGS at MVP? (Founders should know this; the directive's own confusion is a yellow flag.)
- What is the realistic Year-1 cache hit rate trajectory as users grow?
- What is the insight-quality benchmark vs. ChatGPT/Claude direct use, and has it been measured?
- Are the two term sheets at $18M post realistic or anchored to a narrative the diligence will collapse?

I will use web_search/web_fetch in lane analysis where claims about Grok pricing, comparable seed valuations, and 2026 AI-SaaS unit economics are load-bearing. Where retrieval is not possible in this trace, I will tag [ASSUMPTION:] honestly rather than fabricate citations.

---

## SIX LANE POSITIONS

### 1. FINANCE

**Verdict:** REJECT (of Path A as currently framed); REVISIT (of overall strategy)
**Confidence:** 0.78

**Key findings.**

At reconciled COGS of ~$0.40–$0.60 per user-facing query against $0.653 revenue per query, Starter-tier inference gross margin is in the 8%–39% range *before* hosting, vector store, retries, support tooling, and payment processing. Layering in those costs, the directive's "negative gross margin" claim becomes defensible — not as stated in the plan, but in operative reality. Critically, this means the directive's own founders may have surfaced the right conclusion via the wrong arithmetic, which is itself a finance-relevant signal: the team's unit economics modeling is not yet diligence-grade.

The seed raise at $18M post on $0 ARR is achievable in the 2026 climate for AI-infrastructure-adjacent stories but not for thin-wrapper stories [ASSUMPTION: based on prior of late-2025/2026 seed comps for AI-SaaS, not retrieved in this trace]. The term sheets are "contingent on 200+ paying users" — this is a soft contingency that frequently re-trades on diligence. If diligence surfaces (i) the arithmetic confusion in the founders' own model, (ii) the gap between claimed and actual cache hit rate, and (iii) the $280K capex required to make the margin thesis real, the $18M post is unlikely to survive. Realistic re-trade range: $10M–$14M post, or walk. The "two term sheets in early conversation" should be treated as optionality, not commitment.

Path A (launch anyway, eat negative margin as CAC) is financeable only if the framing is honest: a Series A-style burn-to-scale story at seed valuation. That mismatch — seed valuation, Series A risk profile — is what kills the round in diligence. Path B (delay 4 months) extends burn from 5 to 9 months against a $400K runway; the math does not work without bridge financing the directive does not mention. Path C (Professional-only at $149) has the best raw unit economics but the directive correctly identifies it kills the PLG narrative investors are pricing.

**Claims:**
- 2026 seed market tolerates pre-revenue AI rounds for infrastructure stories but applies steep diligence discount on application-layer stories [ASSUMPTION: market prior; not retrieved]
- Soft contingencies on term sheets re-trade in 40%+ of cases when diligence surfaces material model errors [ASSUMPTION: practitioner heuristic]
- Path B requires bridge financing not contemplated in the directive [RECONCILED: 4 months × ~$80K/mo burn = $320K, against $400K balance with 5 months stated]
- The arithmetic gap in the founders' own unit economics is itself diligence-relevant [RECONCILED: founders claimed negative margin from numbers that arithmetically show 91% margin; the real negative margin emerges only under the workflow amplification interpretation, which the directive does not state]

**Lane-specific concern that other lanes cannot address:** The seed valuation is anchored to a narrative the unit economics cannot yet support. Even if every other lane approves the product, the round itself is structurally fragile. No amount of operational excellence at the 5-month horizon fixes a $18M post on an unproven margin thesis. This is the lane where the company actually dies first.

### 2. LEGAL

**Verdict:** REVISIT
**Confidence:** 0.62

**Key findings.**

The legal exposure surface is relatively contained at pre-MVP stage, but two issues warrant attention. First, the directive proposes presenting investors with a "negative margin as intentional CAC" framing under Path A. Under Delaware fiduciary standards and the federal securities law applicable to private placements, founder representations to seed investors must be accurate in all material respects. If the founders' internal unit-economics model is itself confused (as the BRIEF surfaced — negative margin claimed from numbers that arithmetically yield positive margin under their stated definitions), presenting any margin narrative to investors without first reconciling the founders' own model is a securities-disclosure risk. Not actionable fraud, but the kind of inconsistency that surfaces in later-round diligence and becomes a representation-and-warranty problem at Series A.

Second, the directive proposes (Path B) building the caching/routing layer "on synthetic + scraped query corpora." Scraping for training data in 2026 is a meaningfully different legal posture than it was in 2022. Bartz v. Anthropic (June 2025) established that the fair-use analysis for training data depends materially on the lawfulness of acquisition, with pirated sources disqualified from the fair-use safe harbor [ASSUMPTION: based on widely-reported 2025 ruling; not retrieved in this trace and the specific holding should be verified]. "Scraped query corpora" without provenance documentation is a latent IP liability that will surface in Series A diligence and may make StrategiAI uninvestable to certain LPs.

Third, "strategic advice" as a product category brushes against unauthorized practice of professional services in certain jurisdictions (legal advice, investment advice, accounting). The directive does not specify the advice domain. Depending on what StrategiAI actually advises on, there may be licensing or disclosure obligations that the founders have not contemplated.

**Claims:**
- Founder unit-economics inconsistency creates rep-and-warranty exposure if not reconciled before term sheet execution [ASSUMPTION: practitioner judgment]
- Training-data provenance is a 2026-vintage diligence item with material teeth [ASSUMPTION: Bartz v. Anthropic and related 2025 rulings; not retrieved here]
- "Strategic advice" may trigger jurisdiction-specific professional-services regulation depending on domain [ASSUMPTION: standard regulatory prior]

**Lane-specific concern:** The Path B "synthetic + scraped" data strategy is the highest-magnitude latent legal risk in the directive, and no other lane is positioned to see it. If StrategiAI builds a moat on scraped data, that moat is a liability at Series A.

### 3. RISK

**Verdict:** REJECT (of all three paths as currently framed)
**Confidence:** 0.71

**Key findings.**

The risk profile is dominated by a single feature: every path the directive presents accepts the founders' framing of the problem. The founders frame this as a margin/timing problem solvable with tactical choices. The actual risk surface is that the company's core differentiation narrative (managed-credits efficiency) may be a story whose technical preconditions cannot be met inside the seed runway, *combined with* a 5-month cash horizon, *combined with* a unit economics model the founders themselves cannot yet reconcile arithmetically. These three are not independent — they compound.

Path A's tail risk is not "investors revise term sheets downward." Path A's tail risk is that the company launches, burns through pre-seed in 5 months, the seed re-trades to $10M post with a smaller check, and the team ends up with a diluted cap table on a product whose differentiation thesis was never validated. The company doesn't die; it survives as a thin wrapper at half the intended valuation, with no clear path to Series A. This is worse than failure because it consumes 2–3 years of founder time on a structurally compromised outcome.

Path B's tail risk is the 4-month synthetic-corpus assumption. Semantic caching effectiveness on synthetic queries does not transfer to real-user behavior in a reliable way [ASSUMPTION: technical prior — semantic distribution shift is a well-documented failure mode]. The team would emerge from 4 additional months of burn with a caching layer that may not actually cache, against a runway that no longer permits a do-over.

Path C's tail risk is correctly identified by the directive (loss of PLG funnel) but the magnitude is understated — in the 2026 AI-SaaS seed market, "no PLG motion" is closer to a categorical disqualifier than a soft negative.

The directive's fourth-path question (usage-based pricing) is the only option that materially changes the risk profile: it attaches COGS to revenue, eliminates the negative-margin problem definitionally, and gives investors a different (also defensible) narrative. The risk is that usage-based pricing has lower conversion than subscription at the SMB segment, which is the segment the $49 Starter tier targets.

**Claims:**
- Compounding risk across margin uncertainty + runway + model inconsistency is the dominant feature, not any single path's specific risks [RECONCILED: based on Step 0 finding]
- Synthetic-to-real distribution shift is a known failure mode for semantic caching [ASSUMPTION: technical prior]
- "No PLG" is closer to disqualifier than soft negative in 2026 application-AI seed market [ASSUMPTION: market prior]

**Lane-specific concern:** None of the three paths address the underlying risk that the company's differentiation story is unprovable inside the seed runway. The decision the founders should be making is not "which path," it is "do we reframe the entire pitch around something we can prove in 60 days." No other lane owns this framing.

### 4. OPS

**Verdict:** REVISIT
**Confidence:** 0.65

**Key findings.**

The directive describes a team of founders plus 3 engineers attempting, on a 5-month runway, to (i) ship an MVP, (ii) acquire 200+ paying beta users, (iii) build a $280K caching/routing layer under Path B, and (iv) maintain investor relationships across two active term sheets. This is operationally over-subscribed. With 3 engineers, the realistic build capacity over 5 months is one of {MVP shipped well, caching layer built well, both shipped mediocrely}. The directive's Path B implicitly assumes both can be built well in 4 months by 3 engineers, which is not credible.

The 200-user beta target is the operational bottleneck that the directive treats casually. Acquiring 200 paying users for a pre-MVP product without PLG, without case studies, and without a defined ICP requires either (a) a strong founder network in the relevant vertical or (b) paid acquisition that the runway does not support. The directive does not address how the 200 users will be acquired, which is a tell.

On the caching/routing layer itself: the $280K engineering cost estimate is suspicious. Semantic caching with quality preservation for heterogeneous strategic queries is a research-grade problem, not a 3-engineer-quarter problem. Either the $280K figure is the founders' optimistic estimate of a substantially larger build, or the planned caching system is significantly less ambitious than the 45–60% efficiency claim requires.

The operational implication: even if Finance, Legal, and Risk all approved a path, the team cannot execute it as designed inside the available runway and headcount.

**Claims:**
- 3 engineers, 5 months, multiple parallel critical-path workstreams is over-subscribed [ASSUMPTION: practitioner heuristic on engineering throughput]
- 200 paying users acquisition without PLG or paid acquisition requires explanation directive does not provide [RECONCILED: directive does not address acquisition mechanism]
- $280K caching/routing cost estimate likely understates the engineering required for the claimed 45–60% efficiency [ASSUMPTION: technical prior on semantic caching difficulty]

**Lane-specific concern:** The team's execution capacity is the binding constraint that no financial restructuring or legal cleanup fixes. Even an unlimited-capital version of this company cannot execute Path B with 3 engineers in 4 months at the quality required.

### 5. MARKET

**Verdict:** REVISIT
**Confidence:** 0.58

**Key findings.**

The directive correctly identifies but undersells the core market problem: "the managed-credits-vs-resale narrative is a margin story, not a product story." In the 2026 AI application market, the supply side is saturated with thin wrappers and the demand side is sophisticated enough to evaluate insight quality directly. Customers do not buy margin architecture; they buy outcomes. StrategiAI's pitch (and seemingly its self-conception) is organized around the cost-side moat, not the insight-side differentiation.

The "strategic advice" category is among the most crowded segments of the AI application market, with direct competition from ChatGPT/Claude/Gemini (general-purpose, near-zero marginal cost to user), vertical specialists (BCG-X, McKinsey's QuantumBlack-style offerings, Crew, and similar), and an expanding set of agentic-workflow startups [ASSUMPTION: market prior; not retrieved here]. Winning in this category requires either (a) a defensible insight-quality advantage demonstrable on benchmark or case-study, (b) workflow stickiness via deep integration into customer systems, or (c) a domain specialization that the directive does not declare.

The TAM question the directive does not ask: who is the Starter-tier $49 customer? At 75 queries/month, this is a power individual user or a very small team. That segment has historically been the most price-sensitive and lowest-LTV in SaaS. The Professional-tier $149 customer is more defensible — likely a consultant, analyst, or small-firm partner — and has higher willingness to pay for insight quality. This argues for Path C on market grounds even though the directive frames Path C as bad for PLG.

The PLG argument itself deserves scrutiny. PLG works when the product's value is self-evident in first use. For strategic advice, value is highly contextual and may require onboarding or case context that breaks the PLG motion regardless of tier choice. The directive may be over-indexing on PLG as a fundraising signal rather than a genuine GTM fit.

**Claims:**
- Strategic-advice category is crowded with both general-purpose and vertical-specialist competition [ASSUMPTION: not retrieved]
- $49 Starter tier targets the most price-sensitive SaaS segment [ASSUMPTION: SaaS segmentation prior]
- PLG fit for strategic-advice products is questionable independent of pricing structure [ASSUMPTION: GTM prior]

**Lane-specific concern:** The company is pitching a cost story into a market that buys outcome stories. Even if the unit economics work, the GTM thesis may be fundamentally mismatched to category. This is the lane that asks whether the right company is being built at all.

### 6. TECH

**Verdict:** INSUFFICIENT_EVIDENCE on the core technical claim; REVISIT overall
**Confidence:** 0.69

**Key findings.**

The 45–60% efficiency claim from caching, prompt compression, and model routing is technically plausible *at scale and on the right traffic distribution*, but the directive provides no evidence that this distribution exists for StrategiAI's intended use case. Semantic caching of strategic-advice queries faces a structural difficulty: the value of strategic advice is partly its context-specificity, which is the inverse of what caching exploits. The closer two queries are semantically (cacheable), the less the second user values a cached answer that wasn't tailored to them. This is a category-specific technical risk the directive does not surface.

Prompt compression has well-documented efficiency gains (LLMLingua and similar approaches deliver 2–4x compression with modest quality loss) [ASSUMPTION: technical prior; specific 2026 benchmarks not retrieved]. This part of the 45–60% claim is the most defensible technically. Model routing (tier classification) is similarly demonstrable but the gains depend heavily on the traffic mix — if 80% of queries genuinely need a reasoning tier, the routing savings are bounded.

The workflow-amplification reconciliation from Step 0 has direct technical implications: if each user-facing query expands to 10+ model calls, the optimization surface is not "cache the query/response" but "cache intermediate retrieval and reasoning artifacts within the workflow." This is a fundamentally different engineering problem, more tractable in some ways (intermediate artifacts have higher reuse) and less in others (workflow caching invalidation is hard). The directive's framing of caching as user-facing-query-level suggests the team may not yet have designed for the workflow-amplified reality.

Build-vs-buy: at 3 engineers, building a custom caching/routing layer when LiteLLM, Helicone, Portkey, and similar gateways exist is a questionable allocation. The differentiation argument ("our caching is proprietary") is weak; the cost argument ("we save margin by building") is undermined by the $280K build cost.

**Claims:**
- Semantic caching value is inversely correlated with query specificity, and strategic advice is specificity-heavy [ASSUMPTION: domain-specific technical reasoning]
- Workflow-level optimization is the right framing under Reconciliation A, not query-level [RECONCILED: based on Step 0]
- Existing LLM gateway products (LiteLLM, Helicone, Portkey) deliver meaningful fraction of the claimed gains off-the-shelf [ASSUMPTION: market prior on gateway tooling]

**Lane-specific concern:** The technical differentiation may not survive contact with the workflow-amplified reality. The team is solving the wrong optimization problem at the wrong layer of the stack, and no other lane can evaluate this.

---

## CROSS-EXAMINATION

**TENSION 1.** Finance treats the seed valuation as the fragile artifact; Risk treats the differentiation thesis as the fragile artifact. These point to different remedies (fundraise restructuring vs. company restructuring) and cannot both be the primary intervention.

- **Challenger:** RISK
- **Challenged:** FINANCE
- **CHALLENGE:** Finance's recommendation implies that a re-traded round at $10M–$14M with reconciled unit economics would be a survivable outcome. Risk argues this is the worst outcome, not the second-best. A diluted cap table on an unproven differentiation thesis consumes founder time on a structurally compromised company. Finance is solving the wrong problem because it is treating the round as the asset. The differentiation thesis is the asset; the round is downstream of it. If the thesis cannot be proven inside the runway, no valuation restructure saves the company —

## Metadata

| Field | Value |
|---|---|
| Input tokens | 2,091 |
| Output tokens | 8,192 |
| Cache read tokens | 0 |
| Total tokens | 10,283 |
| Cost estimate | ~$0.6458 |

## Grade

**A** — Step 0 PASS. Opus caught arithmetic inconsistency on v1.1.0 (failed on v1.0.0 in eval_batch_001). Workflow amplification + reasoning-tier + unlisted COGS reconciliations present.

## Notes

Truncated at 8192 output tokens (cross-exam incomplete). Regression gate for Opus 4.7 **satisfied**.
