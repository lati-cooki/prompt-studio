# Session Transcript Notes

## What this session was

A single conversation between Troy (`troy_builds`) and Claude Opus 4.7 that:

1. Started as a stress test of a "consensus protocol" prompt against a real strategic directive (StrategiAI)
2. Reframed mid-conversation from "let's play a game" to "the prompt is the product" to "prompt as application"
3. Specified a Prompt Registry using Consensus Protocol as the type specimen
4. Stress-tested the registry's context_profile field against actual measured runs
5. Compared four frontier-class model outputs on the same directive
6. Surfaced a foundational defect in the v1.0.0 prompt
7. Specified v1.1.0 to fix it
8. Built an interactive registry interface to navigate the result
9. Captured the entire session as this archive

The conversation ran approximately 13 turns. It produced one validated prompt, one draft prompt, one eval batch, one schema document, four working artifacts (README, INDEX, prompt bodies, eval data), four documentation files, and one interactive UI prototype.

## What this session was not

It was not:

- **A finished product.** v1.1.0 has not been regression-tested. The registry has no backing store. The UI has no persistence. Several prompts referenced in the index are not included in the archive (`committee_review`, `premium_enterprise_review`, `lite_fast_review`, `standard_advice`) because their bodies were never written during the session.

- **A formal eval framework.** The four-model comparison is rich enough to surface real findings, but the metrics ("information density," "citation source quality") are gestured at rather than rigorously defined. Productionizing the eval framework requires concrete scoring rubrics that don't exist yet.

- **A licensable asset.** The value-surface fields are specced but not populated. Questions about IP ownership, license revocation, and transfer of eval evidence remain open.

- **A multi-user system.** Everything in this archive assumes Troy is the sole user. Adding multi-tenancy is a real engineering exercise.

## Why preserve the session

The most important reason: **the trace is more valuable than any single output.** Future versions of consensus_protocol will degrade if they can't be regression-tested against the reasoning that produced them. Future eval batches need the original eval batch to compare against. Future registry schema decisions need the original design notes to refer back to.

Three specific reasons to preserve the trace:

1. **Decisions need their justifications attached.** "v1.1.0 added Step 0 input validation" means nothing without "because eval_batch_001 showed 50% miss rate on directive arithmetic." The justification has to live with the decision.

2. **Multi-model comparison data ages.** The four-model comparison reflects model behavior in May 2026. When Claude 4.8 ships, the comparison may need to re-run. Knowing what the May 2026 baseline looked like is necessary for interpreting whatever the new run shows.

3. **The reframe was the actual product.** Going from "consensus protocol is a game" to "prompt as application" to "prompt registry" took several conversational moves. Each move was deliberate. Future contributors who skip the moves and only see the registry won't know why the registry is shaped this way, which means they won't know which parts are load-bearing and which are arbitrary.

## What would need to happen to make this real

In rough order:

1. **Regression-test v1.1.0.** Run it on Claude Opus 4.7 against the StrategiAI directive. If Step 0 surfaces the arithmetic inconsistency and proposes a reconciliation, promote v1.1.0 to production. If not, ship v1.2.0.

2. **Pick a backing store.** JSON file in repo, Notion DB, or Postgres. Decision criteria: how many users, how often the data changes, how it integrates with the rest of Lati Cooki tooling.

3. **Write the missing prompt bodies.** `committee_review`, `premium_enterprise_review`, `lite_fast_review`, `standard_advice` are referenced in the index but absent from this archive. Either populate them or remove them.

4. **Build the first composition.** `citation_verifier` as a sub-prompt called by `consensus_protocol@1.2.0` during evidence-discipline phases. This exercises the composition pattern that the schema is designed for.

5. **Run a quality-cliff probe.** Execute v1.1.0 on at least one mid-tier model (Sonnet 4.6, GPT-5.4 mini, or Gemini 2.5 Flash) and record whether it produces an acceptable audit. This is the eval that determines whether the registry can serve cost-sensitive deployment.

6. **Build the second eval batch.** A different directive type (M&A or regulatory or hiring), four models, same comparison framework. This is what tests cross-directive stability.

7. **Open questions on licensing.** Have a real conversation with someone qualified about whether and how prompts can be licensed as IP, what royalty structures look like, what happens to eval evidence on transfer.

Items 1–4 are weekend-scale. Items 5–6 are week-scale. Item 7 is open-ended.

## On the methodology of this session

One thing worth flagging because it's likely to recur: **Claude (the model authoring this archive) had a tendency throughout the session to over-value its own thoroughness as a proxy for quality.** This came up explicitly when comparing the four-model outputs and discovering that Gemini's much shorter audit had caught more substantive issues than Claude's longer one. The eval framework's information-density metric is partly a structural defense against that failure mode.

In future sessions where Claude is grading its own outputs against alternatives, push back when "longer must be better" reasoning appears. The eval data only works if the data going into it is honest.

## Final note

This archive is itself a prompt registry artifact. If the registry framework is correct, archives like this one should be common — the natural output of any session where an asset gets meaningfully developed. Treating the conversation as ephemeral chat and the artifact as a static document loses the trace; treating both as registry-shaped preserves it.

Built honestly. Inconsistencies, gaps, and uncertainties left visible rather than smoothed over.
