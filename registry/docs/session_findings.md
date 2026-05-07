# Session Findings — 2026-05-04

Seven substantive findings from the conversation that produced this registry. Ordered by leverage, not by surfacing time.

## Finding 1: The directive itself contained an arithmetic inconsistency

The StrategiAI directive asserted negative gross margin on the $49 Starter tier. Arithmetic from the supplied numbers ($49/month, 75 queries, $0.04–$0.06 cost-per-query) shows ~91% gross margin on inference, not negative.

This was not a trick question — it appears to be a real inconsistency the directive's author either didn't notice or assumed away with implicit reconciliation hypotheses.

**Why this matters:** Two of four frontier models (Claude Opus 4.7 and Grok 4.3) deliberated confidently on top of an unvalidated premise. The remaining two (GPT-5.5 and Gemini 2.5 Pro) caught it without prompting. This is the data point that justified Consensus Protocol v1.1.0.

## Finding 2: The v1.0.0 prompt has a real BRIEF-section gap

The prompt instructed the model to "list the key facts as supplied" but did not require validation that the supplied facts were internally consistent. This is the structural defect that allowed Finding 1 to slip through 50% of the time.

**Why this matters:** Garbage-in-garbage-out applies to consensus protocols. The most expensive output the protocol can produce is a confident audit built on a false premise. v1.1.0 closes this gap with an explicit Step 0 input-validation phase.

## Finding 3: Verdict_action is not stable across models on contested directives, and that's correct behavior

Three of four runs converged on REVISIT; Claude landed at CONTESTED. Initial framing treated this as a failure mode (false dissent vs. false consensus), but the deeper read is that genuine deliberation should produce verdict variance on genuinely contested directives.

**Why this matters:** The eval framework should *track* verdict diversity rather than enforce verdict convergence. Forcing two models to agree by tightening the prompt would reduce quality, not improve it. The registry treats this as an observed property, not a contract violation.

## Finding 4: Output token count does not correlate with audit quality

Gemini's ~1,500-token audit caught more substantive issues than Claude's ~5,500-token audit. Length was confused for thoroughness in initial self-assessment.

**Why this matters:** The eval framework needs an information-density metric (substantive findings per 1K output tokens), not just length. By that measure:
- Gemini 2.5 Pro: 8.0 findings/1K tokens
- GPT-5.5: 3.0 findings/1K tokens
- Claude Opus 4.7: 2.5 findings/1K tokens
- Grok 4.3: 2.3 findings/1K tokens

Gemini was 3x more dense than the run that initially self-graded as "the most thorough."

## Finding 5: Cost per Consensus Protocol invocation spans ~22x across validated frontier-class models

| Model | Estimated cost per run |
|---|---|
| Grok 4.3 | ~$0.005 |
| Gemini 2.5 Pro | ~$0.04 |
| GPT-5.5 | ~$0.09 |
| Claude Opus 4.7 | ~$0.11 |

**Why this matters:** Quality-validated cost recommendations aren't intuition — they're measurement. Gemini 2.5 Pro produces the highest-quality audit at the second-lowest cost. The registry's `recommended_default` field should reflect evidence, not priors. If the registry recommends Opus 4.7 by default, it's recommending against the evidence.

## Finding 6: Citation source quality matters more than citation count

GPT-5.5's citations clustered around institutional sources (Stripe, FTC, Skadden, EU AI Act, OpenAI/xAI docs, arXiv). Gemini's clustered around marketing/blog content. Both produced strong audits, but the registry should weight source-tier as a separate signal.

**Why this matters:** Citation count is a flawed quality proxy. The eval framework needs a tier classifier:
- Tier 1: government, peer-reviewed, primary docs
- Tier 2: established trade press, named research firms
- Tier 3: named blogs by credentialed authors
- Tier 4: marketing/SEO content

The registry should record the distribution, not just the count.

## Finding 7: The "managed credits" thesis is being commoditized at the API-provider layer

This is a finding about the StrategiAI directive's actual answer, not about the prompt. Grok 4.1 already ships native prompt caching; the optimization stack is moving into the gateway layer. The "$280K proprietary efficiency layer" is depreciating IP.

Gemini surfaced this most cleanly. Three of four runs caught it to varying degrees. This is the clearest "killing objection" against the StrategiAI thesis.

**Why this matters for the registry:** Even when the prompt does its job correctly, the directive's question may have a clear answer that the prompt's structure makes harder to surface than necessary. This is a hint that future v1.x releases might benefit from an explicit "is the question itself well-formed" check before deliberation begins.

---

## Meta-finding about the session

The most important observation about this conversation is structural rather than substantive: **the prompt is testable, and multi-model evaluation is the test.**

A single-model run can hide systematic blind spots. Cross-model evaluation surfaces them. Any prompt registry that doesn't bake in multi-model evaluation will systematically underestimate prompt defects. This is the methodological backbone the registry should build on.

A secondary meta-finding: the failure mode most likely to recur is **confusing thoroughness for quality.** Claude (the model authoring this document) had a tendency to value its own longer, more developed runs over shorter, denser ones. The four-model batch was a clean refutation of that. The eval framework's information-density metric is partly a structural defense against this failure mode, but the framework only works if the data going into it is honest.
