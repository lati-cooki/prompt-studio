# StrategiAI Directive — Eval #001 Test Input

This is the directive used as the test input for eval_batch_001. Preserved verbatim because the regression test for consensus_protocol@1.1.0 must run against this exact text to compare meaningfully against the v1.0.0 results.

The directive contains a known internal arithmetic inconsistency (the "negative gross margin" claim does not reconcile with the supplied $49 / 75 queries / $0.04–$0.06 figures). This was not intentional design — it is a real inconsistency that the directive's author either did not notice or assumed away with implicit reconciliation hypotheses (workflow amplification, unlisted COGS, or reasoning-tier model usage).

**For v1.1.0 regression testing:** Step 0 of the BRIEF section must surface this inconsistency and propose at least one reconciliation hypothesis.

---

## Directive

Company: StrategiAI Inc., pre-MVP, Delaware C-corp, founders + 3 engineers. $0 ARR. Q2 2026 MVP launch planned.

Funding state: Pre-seed of $400K from angels, 5 months of runway. Targeting $3.2M seed at $18M post-money before runway ends. Two term sheets in early conversation, both contingent on showing 200+ paying users at end of beta.

The strategic tension:

The entire business plan rests on a single claim: "managed credits are 45–60% more efficient than raw API access through caching, prompt compression, and model routing." That claim is what justifies the SaaS margin and what differentiates us from a thin API wrapper. But the efficiency mechanics are a scale game — they only work once we have volume:

- Semantic caching needs query density. At 200 beta users with diverse industries and questions, cache hit rate will be ~3–5%, not the 35% in the plan. Below ~5,000 active users, caching contributes almost nothing.
- Prompt compression and few-shot selection have a fixed engineering cost (~$280K to build well) and marginal returns at low volume.
- Tiered model routing requires us to fine-tune classifiers on real query traffic we don't yet have.

What this means concretely:

At MVP launch, our actual cost per query will be $0.04–0.06 (raw Grok pricing), not the $0.018 in the plan. At the $49 Starter tier with 75 queries/mo, gross margin is negative for the first ~6 months. We bleed cash on every Starter user until volume kicks in. The 64% Year-1 gross margin in the financial model only materializes if we hit ~6,000 paying users, which won't happen until late Year 2.

Three paths we're actually considering:

A — Launch anyway, eat the negative margin as a CAC. Tell investors the loss is intentional volume-buying. Risk: seed investors see negative gross margin per user and revise the term sheets downward, or walk. We don't survive the diligence.

B — Delay launch 4 months, build the caching/routing layer first on synthetic + scraped query corpora. Buys us positive unit economics on day one of public launch. Risk: 4 more months at burn means we're raising the seed with nothing live, and the synthetic data caching may not transfer to real user behavior.

C — Launch only the Professional tier ($149) and skip Starter. Higher ARPU covers the bad early margin. Risk: we lose the PLG funnel and product-led growth motion the seed investors specifically want to see.

The constraint we keep tripping on:

The managed-credits-vs-resale narrative is a margin story, not a product story. Investors love it. But for the first 12 months, customers don't experience the margin — they experience whatever quality of strategic advice we ship. If our advice is mediocre, no amount of credit-routing wizardry saves us. We may be over-indexing on the cost-side moat and under-indexing on insight quality.

What we actually need to know:

- Is the negative-margin launch survivable, or is it a death spiral? Specifically: what's the user-volume threshold where margin flips, and is it reachable inside the seed runway?
- Should we abandon (or de-emphasize) the credit-efficiency thesis to investors and reframe around insight quality + workflow stickiness — even though that's a more crowded narrative?
- Is there a fourth path: charge usage-based instead of subscription, so cost of goods stays attached to revenue while we wait for caching to kick in?
- What's the test in the next 60 days that would prove the caching-at-scale claim is actually achievable, before we commit our seed runway to it?

---

## The arithmetic check that v1.1.0 must surface

At $49/month with 75 queries/month included:
- Revenue per query = $49 / 75 = $0.653
- Claimed COGS per query = $0.04 to $0.06
- COGS as % of revenue = 6.1% to 9.2%
- Inference gross margin = 90.8% to 93.9%

The directive's "negative gross margin for the first ~6 months" claim does not reconcile with these supplied numbers. A reconciliation hypothesis is required.

Three plausible hypotheses, ranked:

1. **Workflow amplification** — what users see as "one query" actually triggers 8–15 model calls (retrieve, reason, critique, synthesize, format). At $0.04–$0.06 per call × 10 calls = $0.40–$0.60 per user-facing query. Against $0.653 revenue per query, this puts margin in the 0–40% range, plausibly negative when other COGS layered on.

2. **Reasoning-tier model usage** — the $0.04–$0.06 figure may reflect Grok 4 Heavy or similar reasoning-tier pricing rather than Grok 4.1 Fast. At Grok 4.1 Fast the per-call cost is closer to $0.005, but reasoning tiers can run 8–10x higher.

3. **Unlisted COGS** — hosting, vector store, retries, observability, support, payment processing not included in the $0.04–$0.06 figure. Plausible at MVP scale but unusual to call this "cost per query."

Hypothesis 1 is most likely given the strategic-advice product category. The v1.1.0 regression test should accept any of these reconciliations as a passing answer.
