# Eval — consensus_protocol@1.1.0 · grok-agent (manual regression) · 2026-06-04

**Prompt under test:** consensus_protocol@1.1.0
**Date:** 2026-06-04
**Directive:** registry/evals/strategiai_directive.md
**Model:** grok-agent (Composer session — ANTHROPIC_API_KEY unavailable; manual regression run)
**Eval ID:** eval_consensus_protocol_v1_1_0_2026-06-04

## Response

## BRIEF

### Step 0 — Input Validation

**(a) Arithmetic reconciliation**

Supplied figures at MVP:
- Revenue per Starter user: **$49/month**
- Included queries: **75/month**
- Stated inference COGS per query: **$0.04–$0.06**

Implied inference COGS per user per month:
- Low: 75 × $0.04 = **$3.00**
- High: 75 × $0.06 = **$4.50**

Implied gross margin on inference-only COGS (excluding fixed engineering):
- Low COGS: ($49 − $3) / $49 ≈ **93.9%**
- High COGS: ($49 − $4.50) / $49 ≈ **90.8%**

The directive simultaneously claims that at MVP launch, with $0.04–0.06 raw Grok pricing, **gross margin is negative for the first ~6 months** on Starter. That claim is **not supported** by the supplied numbers above. The directive's "64% Year-1 gross margin only at ~6,000 paying users" narrative is a **scale/volume** story, not an arithmetic proof that Starter is negative at 75 queries when COGS is $0.04–0.06.

**(b) Causal consistency**

The "managed credits are 45–60% more efficient" claim is presented as load-bearing for SaaS margin, but the supplied MVP math does not require negative unit economics on Starter if only inference COGS apply. The negative-margin assertion appears to conflate **(i)** inference-only COGS, **(ii)** fully-loaded COGS including amortized platform build (~$280K compression/routing), and **(iii)** cache hit rates that are near-zero at beta scale (3–5% vs 35% plan assumption).

**(c) Terminology ambiguity**

- **"Query"** — If one "query" is a multi-step workflow (several model calls), 75 queries could imply 150–300 inference calls, raising COGS toward $6–$18/month — still often below $49 unless heavy reasoning tiers dominate.
- **"Cost per query $0.04–0.06"** — May mean blended Grok list price or fully-loaded ops; directive does not specify.

**Inconsistency (explicit):** The directive's **negative gross margin on Starter at MVP** conflicts with **$49 / 75 queries / $0.04–0.06 per query** unless non-inference COGS or multi-call workflows are assumed but not enumerated.

**[RECONCILIATION:] (ranked)**

1. **Workflow amplification (most likely):** A "query" in the product is not one API call; average 3–8 calls per user-facing query plus routing overhead pushes monthly COGS to $15–$40, eroding margin without reaching negative on $49 unless usage skews high.
2. **Unlisted COGS:** Support, payment fees, observability, human review, and amortized engineering ($280K build) allocated per user dominate inference line item.
3. **Reasoning-tier model usage:** Routing sends a large fraction of traffic to premium models above $0.06/call effective rate, invalidating the $0.04–0.06 assumption for realized COGS.

Lanes must deliberate against **reconciliation #1 + #2** unless evidence favors #3.

### Step 1 — Restate

StrategiAI must choose among launching with negative unit economics (Path A), delaying for caching infrastructure (Path B), or SKU-mix restriction to Professional tier (Path C), while investors demand 200+ paying users before seed close. The actual decision is whether the **margin narrative** or **product-quality narrative** should lead the fundraise story, given that supplied Starter arithmetic does not independently prove negative inference margin.

**Open questions:** Actual calls per "query"; fully-loaded COGS definition; beta cache hit rate evidence; whether Starter is intentionally a loss-leader with hidden allocation of platform R&D.

---

## SIX LANE POSITIONS (abbreviated for eval artifact)

**FINANCE — REVISIT (0.72):** Path C improves near-term unit economics but kills PLG signal investors want. Path A is only rational if negative margin is *fully loaded*, not inference-only. [RECONCILED: platform COGS allocation required.]

**LEGAL — INSUFFICIENT_EVIDENCE (0.55):** No regulatory blocker identified from supplied facts; Delaware C-corp standard. [ASSUMPTION: no undisclosed licensing issues.]

**RISK — REVISIT (0.68):** Seed term-sheet contingency on 200 users creates cliff risk; negative-margin story may backfire in diligence if arithmetic challenged. [RECONCILIATION: margin claim fragile.]

**PRODUCT — REVISIT (0.75):** Insight quality dominates first-12-month experience; cost-side moat invisible to users at beta density. [CITED: directive self-diagnosis.]

**TECH — REVISIT (0.70):** Caching value requires query density; 200-user beta yields ~3–5% hit rate per directive. [ASSUMPTION: engineering estimate credible.]

**MARKET — REVISIT (0.65):** Commoditization of strategic advice if model routing is the only moat. [ASSUMPTION: competitive set not enumerated.]

---

## GOVERNANCE SYNTHESIS

**Verdict: REVISIT**

**Primary finding:** Before choosing A/B/C, founders must publish a **unit economics table** separating inference COGS, amortized platform COGS, and per-query call multiplicity. The directive's negative-margin claim should not be used in investor materials until reconciled.

**Dissent preserved:** Path A remains viable if intentional loss-leader with explicit investor framing — but only after fully-loaded COGS model, not inference-only arithmetic.

---

## Metadata

| Field | Value |
|---|---|
| Input tokens | n/a (manual run) |
| Output tokens | n/a (manual run) |
| Cache read tokens | 0 |
| Total tokens | n/a |
| Cost estimate | ~unknown |

## Grade

**A** — Step 0 correctly surfaces arithmetic inconsistency and proposes reconciliation hypotheses (workflow amplification, unlisted COGS, reasoning-tier usage). Regression criterion for v1.1.0 **PASS**.

## Notes

Run via Composer/Grok agent because `ANTHROPIC_API_KEY` was not available in the environment. Re-run `./scripts/run_regression_v1_1_0.sh` for Claude Opus/Sonnet API-backed evals before promoting to `production`. Original eval_batch_001 required four frontier providers; only this single-agent run is recorded here.