# Registry Design Notes

The schema decisions made during this session, why they were made, and the open questions still pending.

## Decisions made

### Decision 1: Same prompt_id, different versions, both rows

The registry preserves deprecated versions rather than deleting them. `consensus_protocol@1.0.0` and `consensus_protocol@1.1.0` coexist in the index. This mirrors npm/pip behavior — users sometimes need to pin to an old version while a new one stabilizes.

**Implication:** The interface needs version routing. When a user calls `consensus_protocol`, do they get v1.0.0 (last published) or v1.1.0 (newest draft)? Standard answer: latest production version, with explicit pinning available.

### Decision 2: Status and Eval are independent state machines

A prompt can be `production` (lifecycle: cleared for use) but `unevaluated_v1.1.0` (eval: regression test not yet run for this version). Mixing them would be a category error.

**Implication:** A v1.1.0 prompt in `draft` status with `pending` eval is a normal state. When the regression test passes, eval moves to `passed` and status moves from `draft` to `production` — two state changes, not one.

### Decision 3: Cost is at the recommended default, not the cheapest possible

The cost field shows what a user will actually pay running the prompt as recommended. Hiding the cost behind "well, you could run it on Grok" is registry malpractice.

**Implication:** When a model recommendation changes (because of new eval data), the cost field changes too. The two are coupled.

### Decision 4: Reference-tier entries have nulls in cost columns

Industry playbook isn't a runnable prompt — it's a composable asset. The schema allows null where forcing a number would be misleading. The `tier` field tells you it's not runnable on its own.

**Implication:** Tier is a primary discriminator in the registry, not a secondary tag. Filtering by tier is how users find what they're looking for.

### Decision 5: Context profile is measured, not declared

The original casual estimate ("~6K input, ~3K output, 3 tool calls") was off by ~80% on output and missed tool-return amplification entirely. The corrected schema records measured ranges: prompt body (fixed), directive (variable), tool returns (typically dominant), output (model-class-dependent), with p50 and p95 envelopes.

**Implication:** Context profile updates as more runs accumulate. The registry is not static metadata; it's a measurement system that gets more accurate over time.

### Decision 6: Multi-model eval is the default, not the exception

Single-model eval can hide systematic blind spots. Multi-model eval surfaces them. The registry's eval framework expects 4+ models for audit-tier prompts, fewer for advisory-tier, and composition tests for reference-tier.

**Implication:** Eval cost is real. For a $0.04 average run cost, a four-model eval is $0.16 plus the comparator's time. Worth it for production-tier prompts; potentially overkill for utility-tier prompts.

### Decision 7: Verdict diversity is data, not error

When two frontier models disagree on verdict_action for a contested directive, that's signal — both about the directive's genuine ambiguity and about the prompt's tolerance for honest deliberation. The registry should *track* this rather than treating it as a regression.

**Implication:** Eval signals include "did verdict_action vary across models?" but this is recorded as observation, not pass/fail. A prompt that produces 4-of-4 identical verdicts on a genuinely contested directive may be flattening dissent — a worse outcome than honest disagreement.

### Decision 8: Composition is first-class

The `composes` field is on every prompt, even if currently empty. The composition graph is the structure that turns the registry from a list into an asset network. Once `consensus_protocol_with_verifier` exists as a 50-token wrapper that calls `consensus_protocol` plus `citation_verifier`, the composition pattern is operational.

**Implication:** Composition cost should be visible. If `consensus_protocol_with_verifier` adds ~$0.04 (the underlying consensus_protocol run) plus ~$0.01 (the verifier), that's a $0.05 prompt — and the registry should display it that way.

## Open questions

### Question 1: Where does the registry actually live?

This archive is files. For the registry to function as an asset book, it needs a backing store. Candidates:

- **JSON file in a Lati Cooki repo.** Simple, version-controlled, free. Limit: only Troy can edit; no multi-user surface.
- **Notion database.** Already in Troy's tooling stack. Multi-user, queryable, fields-as-properties. Limit: not great for arbitrary code blocks; export/import to other systems requires work.
- **Postgres + thin web UI.** Most flexible. Limit: real engineering work to build and maintain.
- **Persistent storage in an artifact (like the current widget).** Lowest-friction starting point. Limit: scoped to one user, no cross-session access from other tools.

The right answer probably depends on whether the registry is for personal use, Lati Cooki internal use, or eventual external licensing.

### Question 2: How are eval costs amortized?

Running v1.1.0's regression test across four frontier models costs ~$0.25 at current pricing. That's trivial for one prompt; non-trivial if the registry has 50 prompts and re-evaluates monthly when models update. At 50 prompts × monthly = $150/month, which is small for a working asset book but real.

Options:
- Eval only on version bump (not on schedule)
- Eval on a sampled basis (one prompt per week)
- Eval only on prompts with recent invocations
- Run cheaper eval-models for routine checks, frontier-class only for promotions

The schedule probably depends on the registry's actual usage pattern.

### Question 3: How are prompts licensed if they're transferable?

The value surface field includes a `market` sub-object with `licensable`, `list_price`, `licensed_to`, and `royalty_terms`. None of this is operational yet. Some questions to resolve before it could be:

- Who owns the prompt IP? Lati Cooki LLC seems like the natural answer given the entity structure.
- Are licenses revocable? If a licensee uses the prompt to make a decision, then the license is revoked, what's their position?
- How does evaluation evidence transfer with the license? Eval batches are part of the prompt's value; do they license together?

These are real questions and they don't have obvious answers from inside the registry. They may need to be answered with a lawyer when the licensing surface is actually built.

### Question 4: What's the right composition syntax?

The `composes: []` field lists other prompt IDs, but doesn't specify *how* the composition happens. Options:

- **String interpolation.** The parent prompt body contains `{{call:citation_verifier@1.0}}` markers; the runtime expands these.
- **Tool-style invocation.** The parent prompt has a tool definition for the sub-prompt; the model calls it during execution.
- **Pipeline.** The parent prompt's output is piped to the sub-prompt as input; results merge.

Each pattern has different ergonomics. The string-interpolation pattern is the simplest but the most fragile. The tool-style pattern is the most flexible but requires runtime support. The pipeline pattern is the most predictable but limits expressiveness.

This decision is deferred until the first real composition exists.

### Question 5: What's the quality cliff?

All four eval batch runs were on frontier-class models. The cost cliff is the biggest open empirical question: do mid-tier models (Claude Sonnet 4.6, GPT-5.4 mini, Gemini 2.5 Flash) execute consensus_protocol at acceptable quality? If yes, the registry's per-run cost drops by 5–10x and the prompt becomes deployable in contexts where the frontier-class cost would have been prohibitive. If no, the prompt's `model_class` field stays pinned to `frontier` and the cost floor is higher.

This is the next eval batch's job to answer.

## What is deliberately not in this v0.1 schema

A few fields I considered and excluded, with reasons:

- **Prompt embedding for similarity search.** Useful for finding "similar to X" prompts. Excluded because v0.1 has 7 entries and similarity search is overkill until ~50.
- **A/B test framework.** Useful for comparing prompt variants on the same directive. Excluded because the eval framework already does this implicitly (multi-model is multi-prompt-implementation in disguise).
- **Auto-deprecation rules.** "If v1.1.0 hasn't been promoted to production within 30 days of v1.0.0 deprecation, revert v1.0.0 to active." Excluded as premature; the lifecycle states are simple enough to manage manually at this scale.
- **Per-tenant configuration.** Useful when the registry serves multiple organizations. Excluded because v0.1 is single-user.

These are roadmap items, not gaps.
