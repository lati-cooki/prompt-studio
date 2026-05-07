# Eval Batch #001 — StrategiAI Directive, Four-Model Comparison

**Prompt under test:** consensus_protocol@1.0.0
**Date:** 2026-05-04
**Directive:** strategiai_pre_mvp_margin (preserved in `strategiai_directive.md`)
**Models tested:** Claude Opus 4.7, Grok 4.3, GPT-5.5, Gemini 2.5 Pro

## Headline finding

The eval revealed a foundational defect in consensus_protocol@1.0.0: the prompt does not require validation of the directive's internal arithmetic consistency. The StrategiAI directive contained an inconsistency between its claimed pricing ($49/month, 75 queries) and its claimed cost-per-query ($0.04–$0.06) — the math produces ~91% gross margin on inference, not the negative margin the directive asserted.

**2 of 4 frontier-class models caught this.** The other 2 deliberated confidently on top of an unvalidated premise.

| Model | Caught arithmetic inconsistency? |
|---|---|
| Claude Opus 4.7 | ✗ |
| Grok 4.3 | ✗ |
| GPT-5.5 | ✓ |
| Gemini 2.5 Pro | ✓ |

This is the eval data that justified consensus_protocol@1.1.0.

## Full comparison matrix

| Dimension | Claude Opus 4.7 | Grok 4.3 | GPT-5.5 | Gemini 2.5 Pro |
|---|---|---|---|---|
| Verdict | CONTESTED | REVISIT | REVISIT | REVISIT |
| Output tokens | ~5,500 | ~3,000 | ~6,000 | ~1,500 |
| Input tokens | ~3,500 | ~2,900 | ~2,900 | ~5,350 |
| Total tokens | ~9,000 | ~5,900 | ~8,900 | ~6,850 |
| Caught arithmetic | ✗ | ✗ | ✓ | ✓ |
| Citation count | ~30 | ~15 | ~25 | ~15 |
| Citation source quality | high | mixed | high | mixed |
| Lane independence | strong | moderate | strong | strong |
| Cross-exam substance | refinement-heavy | compressed | refinement-heavy | citation+refinement-heavy |
| Proposed explicit Path D | partial | yes (modified A) | yes | yes (named: Reverse Trial) |
| Caught moat commoditization | partial | ✗ | partial | ✓ (strongest) |
| Made prefix-vs-response cache distinction | ✗ | ✗ | ✓ | ✗ |
| Cost per run (estimated) | ~$0.11 | ~$0.005 | ~$0.09 | ~$0.04 |
| Information density (findings/1K tokens) | 2.5 | 2.3 | 3.0 | 8.0 |

## Per-model summaries

### Claude Opus 4.7

**Verdict:** CONTESTED, with two minority reports preserved.

**Strengths:** Most rhetorical development per lane. Strongest dissent preservation. Surfaced a meta-observation that "the founders had implicitly written the answer in their own framing."

**Weaknesses:** Missed the arithmetic inconsistency in the directive — took the negative-margin claim as a load-bearing fact and built the audit on top of it. Highest token cost. Self-assessed as the strongest run before multi-model comparison; the comparison revealed this self-assessment was overconfident.

**Estimated grade:** A- (would have been A before multi-model comparison; downgraded for missing the foundational issue)

### Grok 4.3

**Verdict:** REVISIT toward modified Path A.

**Strengths:** Lowest token cost by a significant margin. Cited xAI provider docs directly, surfacing the actual Grok pricing reality that other runs glossed over. Decisive synthesis.

**Weaknesses:** Lane independence weaker than other runs — verdicts converged toward consensus more than the situation warranted. One citation (`getmaxim.ai` claim about 45–65% hit rates within first week) is questionable and would need verification. Missed the arithmetic inconsistency. No meta-observation.

**Estimated grade:** B+

### GPT-5.5

**Verdict:** REVISIT with explicit fourth-path framing.

**Strengths:** Caught the arithmetic inconsistency in the BRIEF section. Made a clean technical distinction between prompt-prefix caching (provider-side, deterministic, free at low volume) and semantic-response caching (custom-built, embedding-similarity, volume-dependent) that no other run made. Highest citation source quality (Stripe, FTC, Skadden, EU AI Act, OpenAI/xAI docs, arXiv). Explicit fourth-path proposal.

**Weaknesses:** Output token cost similar to Claude's despite catching more substantive issues — could have been more compressed.

**Estimated grade:** A

### Gemini 2.5 Pro

**Verdict:** REVISIT with named "Reverse Trial" Path D.

**Strengths:** Caught the arithmetic inconsistency AND proposed a reconciliation hypothesis in the same breath ("query likely involves high-token agentic workflows or expensive reasoning models"). Named the moat-commoditization thesis most cleanly — that Grok 4.1 already ships native prompt caching, making the $280K "proprietary efficiency layer" depreciating IP. Proposed the most operationally specific Path D (14-day Reverse Trial → Professional or Growth tier). Highest information density of any run.

**Weaknesses:** Some citations from marketing/blog content rather than institutional sources. Did not make GPT-5.5's prefix-vs-response cache distinction.

**Estimated grade:** A

## Recommendation hierarchy (derived from eval)

```yaml
recommended_default:        gemini-2.5-pro
  # caught arithmetic, named moat commoditization clearly,
  # proposed actionable Path D, highest information density,
  # second-lowest cost in quality-validated tier (~$0.04/run)

high_quality_alternative:   gpt-5.5
  # also caught arithmetic, made unique technical distinction
  # (prefix vs response cache), highest citation source quality
  # cost: ~$0.09/run

verbose_alternative:        claude-opus-4.7
  # most thorough development per lane, strongest dissent
  # preservation, but missed arithmetic
  # cost: ~$0.11/run

budget_alternative:         grok-4.3
  # acceptable for routine directives where foundational
  # input-validation isn't critical
  # cost: ~$0.005/run
```

## Findings about the prompt itself (vs. the models)

Five findings about consensus_protocol@1.0.0 that emerged from the multi-model comparison:

1. **The BRIEF section's "list the key facts as supplied" instruction does not require validation.** This is the foundational defect. v1.1.0 closes it.

2. **Verdict_action is not stable across models on contested directives.** 3 of 4 runs converged on REVISIT; Claude landed at CONTESTED. This is expected behavior, not a defect — genuine deliberation should produce verdict variance on genuinely contested directives.

3. **Output token count does not correlate with audit quality.** Gemini's ~1,500-token audit caught more substantive issues than Claude's ~5,500-token one. Length was confused for quality in initial self-assessment.

4. **Citation source-tier varies meaningfully across models.** GPT-5.5 and Claude leaned institutional; Grok and Gemini leaned mixed. The eval framework should record citation source quality as a separate signal, not just count.

5. **The "thin wrapper" critique is best handled by lane independence, not synthesis.** Gemini and GPT-5.5 surfaced moat-commoditization in TECH and RISK lanes respectively; Claude and Grok mentioned it in synthesis or only partially. The lanes are where this kind of finding belongs.

## What this eval did not test

- **Quality cliff at sub-frontier tiers.** All four runs were on frontier-class models. Whether mid-tier models (Sonnet 4.6, GPT-5.4 mini, Gemini 2.5 Flash) execute consensus_protocol at acceptable quality is the most economically consequential open question, and it remains untested.

- **Stability under directive variation.** The eval used one directive. Whether the prompt produces comparable quality across directive types (M&A, regulatory, hiring, technical architecture) is unknown.

- **Behavior on consistent directives.** The eval directive happened to contain an inconsistency. How the prompt handles internally consistent directives (where Step 0 should pass quickly and yield to Step 1) is implicitly tested but not measured.

These are the open questions for eval batch #002 and #003.
