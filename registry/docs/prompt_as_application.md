# Prompt as Application

The reframe that made this registry possible.

## The traditional view

Prompts are user inputs. Ephemeral text typed at a model to get an answer. The product is the model — or the wrapper around the model — and prompts are interchangeable. A good prompt is a good sentence; a bad one is a bad sentence. Either way, it's just text.

This view has shaped how most AI tooling thinks about prompts. They live in user input fields, in chat logs, occasionally in libraries of "prompt examples" that no one maintains. They are not versioned. They are not tested. They are not assets.

## The view this registry is built on

Prompts are technical assets that require maintenance, versioning, and investment. The Consensus Protocol prompt is not a sentence — it's a 2,400-word executable specification with internal architecture (six lanes, cross-examination protocol, evidence discipline rules, anti-patterns, output schema). It does work. It produces a structured deliverable. It has a contract with its inputs and a contract with its outputs.

That's not a query. That's an application. And like any application, it has the properties applications have:

**Version history.** v1.0.0 was the initial Consensus Protocol release. v1.1.0 closes a defect surfaced by multi-model evaluation. v1.2.0 will likely happen when v1.1.0's regression test reveals the next gap. Each version exists because of measurable evidence, not aesthetic preference.

**Regression tests.** The same directive run on v1.0.0 vs v1.1.0 should produce comparably-structured audits. If v1.1.0 collapses dissent into false consensus, that's a regression. The eval framework catches it.

**Dependencies.** Consensus Protocol depends on `web_search` and `web_fetch` being available, on the model behaving a certain way at frontier-tier capability, on the output renderer respecting JSON. Dependency changes break it.

**Maintenance cost.** When Anthropic ships Claude 4.8, the prompt may behave differently — confidence calibration shifts, cross-examination depth changes shape. Someone has to re-tune. This is not a cost to be eliminated; it's a cost to be planned for.

**Value surface.** Some prompts are worth $5,000 to construct and yield $500,000 of decision quality across an organization. Others are worth $50. The valuation question is real. Treating prompts as transferable assets makes the question answerable.

## What this registry adds to that view

If prompts are applications, they need the support infrastructure applications need: a registry, a contract system, an eval engine, a versioning discipline, a value surface. Building all of those for the Consensus Protocol case study demonstrated something more general: **prompts that are treated as applications produce better outputs than prompts treated as sentences.**

Three concrete pieces of evidence from this session:

1. The v1.0.0 → v1.1.0 transition was driven by data, not opinion. Multi-model evaluation exposed a structural defect (the missing input-validation step) that no amount of single-model iteration would have surfaced. The registry's eval framework made the defect visible.

2. The recommendation hierarchy (gemini-2.5-pro as default, gpt-5.5 as high-quality alternative, opus-4.7 as verbose alternative, grok-4.3 as budget) is grounded in measured cost-quality tradeoffs across four runs. Without the registry's measurement layer, a prompt author would default to "use the model I happen to have access to," which is how most prompts ship today.

3. The composition pattern — `consensus_protocol` calling `citation_verifier` as a sub-prompt — only becomes natural once prompts have stable contracts. Without contracts, every composition is a string-concatenation hack. With contracts, composition is the same primitive operation that made software engineering scalable.

## What changes if this view is correct

If prompts are applications, then several practices that look optional today are actually load-bearing:

- **Pinning to a version.** Users should pin to `consensus_protocol@1.1.0`, not to "the consensus protocol prompt." Latest-version drift is exactly the source of regressions package managers were invented to solve.

- **Reading the changelog before adopting a version.** A v1.1.0 → v1.2.0 bump might be non-breaking and great, or it might silently change behavior on the dimension that matters to a particular user. Releases need to communicate.

- **Running evals before deploying.** A new prompt version that hasn't been evaluated is a deployment risk, not just an unknown. The registry's eval status is informational; users should treat unevaluated prompts the way developers treat un-tested code.

- **Recording value.** Which decisions did this prompt inform? What did it save? What did it surface that wouldn't have surfaced otherwise? The value surface field exists because prompts that produce uncaptured value are prompts that get under-invested.

- **Treating models as runtimes, not products.** The interesting unit is the prompt-running-on-a-model pair, not either alone. Gemini 2.5 Pro running consensus_protocol@1.1.0 is a different product than Claude Opus 4.7 running consensus_protocol@1.0.0, and the registry should distinguish them.

## What this view does not claim

A few things the prompt-as-application thesis is *not* claiming, to keep the framing honest:

- It does not claim every prompt should be registered. Conversational prompts are perfectly fine; they're just not registry-shaped. The schema's "When a prompt is not eligible for the registry" section is real.

- It does not claim prompts replace traditional software. They live alongside it. A registered prompt that calls Stripe's API is still depending on Stripe, not replacing Stripe.

- It does not claim the registry replaces the model providers. The model providers ship the runtime; the registry curates the assets that run on it. Different layer of the stack.

- It does not claim "prompt engineering" as a discipline is finished. The opposite: this view treats prompt engineering as a discipline in its first decade rather than a passing technique. The registry is the infrastructure that lets the discipline mature.

## Where the term "playable prompt" came from

In the conversation that produced this registry, Consensus Protocol was initially called a "game" and then a "playable prompt." The shift is small but worth noting: a game has win conditions and player agency over moves. A playable prompt has neither. What it has is *replayability across directives* — the same protocol, executed against different inputs, producing different outputs. The closer analogy is **an instrument**, in the music sense. A piano is not a song; it's a thing you play songs on. The prompt is the instrument; each directive is a song.

That framing is durable enough to build a registry on.
