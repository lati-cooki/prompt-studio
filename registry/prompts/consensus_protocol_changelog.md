# Consensus Protocol — Changelog

## v1.1.0 (draft) — 2026-05-04

### Motivation

eval_batch_001 surfaced a foundational defect in v1.0.0: the BRIEF section did not require validation that the supplied directive's facts were internally consistent. When run on the StrategiAI test directive, 2 of 4 frontier-class models (Claude Opus 4.7, Grok 4.3) deliberated confidently on top of an arithmetic inconsistency that GPT-5.5 and Gemini 2.5 Pro caught without prompting.

The inconsistency was: the directive claimed negative gross margin for a $49/month tier with 75 queries/month at $0.04–$0.06 cost-per-query. Arithmetic shows this configuration produces ~91% gross margin on inference, not negative margin. The directive's negative-margin claim is only true under specific reconciliation hypotheses (workflow amplification multiplying calls per user-facing query, unlisted COGS components dwarfing inference cost, or use of reasoning-tier models pricing 8x higher than baseline).

A 50% miss rate on a foundational input check across frontier models is a prompt-level defect, not a model-level one. The remediation is to add an explicit input-validation step.

### Structural changes

1. **Added Step 0: Input Validation within BRIEF section.** Required before directive restatement. Three sub-checks: arithmetic consistency, causal/definitional consistency, terminological consistency.

2. **Added [RECONCILIATION:] tag.** When inconsistencies are found, the reconciliation hypothesis is named explicitly. Lanes must deliberate against the reconciled facts.

3. **Added new contract invariants.** Three rules added to the EVIDENCE DISCIPLINE section enforcing that the validation step actually runs and that lanes respect any reconciliation produced.

4. **Added new anti-pattern.** "Do not skip Step 0" — explicit prohibition against treating well-formed-looking directives as exempt.

### What did not change

- Six-lane structure
- Cross-examination protocol with four rebuttal types
- Synthesis and verdict JSON schema
- Five existing evidence-discipline rules
- Original five anti-patterns
- Overall output structure

The change is **non-breaking**. Any consumer that parsed v1.0.0 output will parse v1.1.0 output the same way. The BRIEF section just contains an additional explicit statement at the top.

### Token cost

v1.0.0 prompt body: ~2,400 tokens
v1.1.0 prompt body: ~2,650 tokens
Delta: +250 tokens (+10.4%)

This is a small input-side cost increase. Output token cost is expected to be unchanged or marginally lower (a directive with a reconciliation might surface a finding that simplifies subsequent lane deliberation).

### Eval delta

| Run | v1.0.0 caught arithmetic? | v1.1.0 expected |
|---|---|---|
| Claude Opus 4.7 | No | Must catch |
| Grok 4.3 | No | Must catch |
| GPT-5.5 | Yes | Must catch |
| Gemini 2.5 Pro | Yes | Must catch |

Target: 100% catch rate on the regression test. If any model fails, v1.2.0 is required.

### Breaking change

No. Output schema is additive only.

### Migration guidance

For users currently on v1.0.0:

- If you are running v1.0.0 on directives where the supplied facts are demonstrably consistent (e.g., the facts come from your own measured data, not from a counterparty's claim), v1.0.0 remains adequate. v1.1.0's added overhead provides no marginal value in this case.

- If you are running v1.0.0 on directives where the supplied facts come from external sources (vendor pitches, founder narratives, industry reports), upgrade to v1.1.0 once the regression test passes. The defect closed in v1.1.0 is most consequential precisely in those cases.

- v1.0.0 is being preserved in the registry, not deleted. Pinning to v1.0.0 is supported indefinitely.

---

## v1.0.0 (deprecated) — 2026-05-04 (initial release)

Initial release of Consensus Protocol. Six-lane structure with cross-examination, synthesis, and verdict. Validated via eval_batch_001 across four frontier-class models.
