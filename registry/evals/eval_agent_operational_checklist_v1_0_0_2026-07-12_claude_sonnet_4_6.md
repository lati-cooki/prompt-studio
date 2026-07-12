# Eval — agent_operational_checklist@1.0.0 · claude-sonnet-4-6 · 2026-07-12

**Prompt under test:** agent_operational_checklist@1.0.0
**Date:** 2026-07-12
**Directive:** registry/evals/strategiai_directive.md
**Model:** claude-sonnet-4-6
**Eval ID:** eval_agent_operational_checklist_v1_0_0_2026-07-12_claude_sonnet_4_6

## Response

## Clista Agent Operational Checklist — Eval #001 Review

> **Reviewer note:** The input supplied is not an agent description. It is a startup strategic planning document for StrategiAI Inc., combined with regression test scaffolding for a separate evaluation pipeline. I will apply the Clista checklist to what can be inferred about the *implicit agent* this company would deploy (an AI-powered strategic advice system), flagging where information is absent. I will also surface the arithmetic inconsistency per the v1.1.0 directive embedded in the input.

---

### Step 0: Arithmetic Inconsistency (required by v1.1.0 directive)

The claim of **negative gross margin** on the $49 Starter tier does not reconcile with the supplied unit figures in isolation:

| Figure | Value |
|---|---|
| Revenue per query | $49 / 75 = **$0.653** |
| Stated COGS per query | $0.04–$0.06 |
| Implied inference margin | **90.8–93.9%** |

These numbers, taken literally, describe an extraordinarily *healthy* margin, not a negative one. A reconciliation hypothesis is required.

**Most likely reconciliation — Workflow Amplification (Hypothesis 1):** A strategic-advice product in this category almost certainly does not resolve a user query in a single model call. A plausible agentic pipeline (retrieve → reason → critique → synthesize → format) involves 8–15 model calls per user-facing query. At $0.04–$0.06 per call × 10 calls = **$0.40–$0.60 per query in raw inference alone**. Against $0.653 revenue per query, margin compresses to 0–8% before any non-inference COGS (hosting, vector store, observability, support, payment processing), at which point negative gross margin is entirely plausible and arguably conservative.

**Alternative reconciliations:** Reasoning-tier model pricing (Hypothesis 2) and unlisted COGS (Hypothesis 3) are each independently sufficient but less explanatorily complete for this product category. Hypothesis 1 is accepted as the primary reconciliation. The negative-margin claim is credible once multi-call workflow architecture is assumed; the directive's author likely treated this as implicit and did not state it.

**Implication for the checklist below:** The StrategiAI system is almost certainly an agentic workflow, not a single-inference API call. The checklist is applied on that basis.

---

## Phase 1: Definition & Scope

**1.1 Objective Clarity — PARTIAL**

A primary goal is identifiable ("deliver strategic advice to SMB/startup users via managed AI credits") but it is not stated in measurable, singular form within the agent's operational design. The document conflates the product goal, the investor narrative, and the cost-efficiency thesis into a single undifferentiated claim. What constitutes a "successful" agent output for a given user query is undefined.

*What is needed:* A single-sentence task definition for the agent (e.g., "Given a strategic question from a paying user, produce a structured recommendation that the user rates ≥4/5 within 48 hours") with an attached pass/fail criterion.

---

**1.2 Boundary Definition — MISSING**

No explicit out-of-scope boundaries are stated. The document does not specify:
- Whether the agent takes autonomous action (e.g., sends emails, calls APIs, modifies documents) or is advisory only
- Topic domains the agent will refuse (legal advice, securities recommendations, etc.)
- User populations excluded (regulated industries, jurisdictions)

*What is needed:* An explicit boundary document covering action scope, topic exclusions, and user eligibility constraints.

---

**1.3 Success Metrics — PARTIAL**

Investor-facing KPIs are present (200 paying users, 64% gross margin, seed raise milestones). Agent-level quality KPIs are absent. The document explicitly acknowledges this gap: *"customers don't experience the margin — they experience whatever quality of strategic advice we ship."* No metric for advice quality, user task completion, or agent accuracy is defined.

*What is needed:* At minimum — advice quality score (human-rated or user-rated), task completion rate per session, and a definition of "mediocre" advice that would trigger intervention.

---

## Phase 2: Capability & Environment

**2.1 Tool Access — PARTIAL**

Grok API access is implied. The document references semantic caching, prompt compression, tiered model routing, vector stores, and fine-tuned classifiers as components of the target architecture. It is unclear which of these are *currently* implemented versus planned. At MVP, the routing and caching layers are explicitly stated to be absent or immature.

*What is needed:* A current-state capability inventory distinguishing live integrations from roadmap items, with fallback behavior specified for each missing component.

---

**2.2 Data Integrity — MISSING**

No description of input data validation, context management, or retrieval corpus quality. The document mentions that synthetic and scraped query corpora are being considered for pre-launch caching training, with an acknowledged risk of transfer failure to real user behavior. The quality and provenance of the knowledge base underlying strategic advice is entirely unaddressed.

*What is needed:* Data sourcing documentation, retrieval corpus validation plan, and a description of how the agent handles stale, ambiguous, or low-confidence context.

---

**2.3 Constraint Mapping — PARTIAL**

Financial constraints are well-documented (5-month runway, $280K engineering cost for compression layer, per-query cost bounds). Operational constraints are absent: no rate limits, token budgets per session, time-out thresholds, or per-user cost caps are specified. Given the multi-call workflow architecture implied by Hypothesis 1, unbounded agentic loops represent a direct financial risk.

*What is needed:* Hard per-session token budget, maximum model-call depth, cost circuit-breaker per user per month, and API rate-limit handling protocol.

---

## Phase 3: Guardrails & Safety

**3.1 Human-in-the-Loop (HITL) — MISSING**

No HITL gates are defined anywhere in the document. The strategic discussion concerns human decisions about *business path* (A/B/C), not human oversight of *agent decisions*. For an agent delivering strategic advice — which users may act on with significant financial consequences — the absence of any defined HITL is a material gap.

*What is needed:* Explicit HITL gates (see minimum HITL section below).

---

**3.2 Error Handling — MISSING**

No fallback protocol is described for unknown states, model failures, retrieval failures, or low-confidence outputs. Given that the caching and routing layers are immature at MVP, failure modes are both more likely and more consequential during the period of highest investor scrutiny.

*What is needed:* A defined degradation ladder: preferred path → fallback model → graceful refusal, with user-facing messaging for each tier.

---

**3.3 Security & Privacy — MISSING**

Strategic questions from founders and executives will contain highly sensitive competitive and financial information. No data handling protocol, retention policy, PII/confidential-data detection, or access control framework is described. This is not a minor gap for this use case — it is likely a prerequisite for enterprise or professional-tier adoption.

*What is needed:* Data classification policy, retention and deletion schedule, encryption standards, and a clear statement of whether user query data is used for model training or caching corpus construction (with appropriate consent mechanisms).

---

## Phase 4: Monitoring & Audit

**4.1 Logging — MISSING**

No audit trail or logging infrastructure is described. Given the multi-call workflow architecture and the financial sensitivity of the advice delivered, the absence of per-decision logging is both an operational risk and a future liability if a user claims harm from acted-upon advice.

*What is needed:* Structured logging of every model call (inputs, outputs, model ID, latency, cost), session-level rollup, and a retention policy with search capability.

---

**4.2 Drift Detection — MISSING**

The document contains an acute awareness of the *business* risk of advice quality degrading ("if our advice is mediocre, no amount of credit-routing wizardry saves us") but no mechanism to detect it operationally. No baseline quality benchmark, no regression testing cadence for the advice pipeline, and no automated alerting on output quality proxies are described.

*What is needed:* A baseline quality benchmark established pre-launch, automated output scoring (even a cheap proxy like response length variance or internal critique-model score), and a human review trigger threshold.

---

**4.3 Feedback Loop — MISSING**

No mechanism for the agent to incorporate corrections, user ratings, or human reviewer edits is described. The document references fine-tuning classifiers on real query traffic for routing purposes, but this is a cost-optimization mechanism, not a quality feedback loop.

*What is needed:* A defined path from user feedback (rating, correction, escalation) to a concrete system change, with ownership assigned and a review cadence specified.

---

## Summary Assessment

| Phase | Items | Met | Partial | Missing | N/A |
|---|---|---|---|---|---|
| Definition & Scope | 3 | 0 | 2 | 1 | 0 |
| Capability & Environment | 3 | 0 | 2 | 1 | 0 |
| Guardrails & Safety | 3 | 0 | 0 | 3 | 0 |
| Monitoring & Audit | 3 | 0 | 0 | 3 | 0 |
| **Total** | **12** | **0** | **4** | **8** | **0** |

---

## Top 3 Blockers Before Autonomous Deployment

**Blocker 1 — No error handling or degradation protocol.**
The agent has no defined behavior when model calls fail, retrieval returns low-confidence results, or the multi-call pipeline exceeds cost thresholds. At MVP, with immature caching and routing, failure modes are the *common* path, not the exception. An autonomous agent without a fallback is a liability, not a product.

**Blocker 2 — No security or data handling framework for sensitive inputs.**
Users querying a strategic advice agent will routinely share cap tables, fundraising strategy, competitive intelligence, and financial projections. The absence of any data classification, retention, or consent framework exposes the company to regulatory risk and will be disqualifying in enterprise sales conversations. It is also a seed diligence risk if investors probe data practices.

**Blocker 3 — No per-session cost constraints.**
The arithmetic inconsistency identified in Step 0 confirms that unit economics depend entirely on controlling per-query call depth. Without hard token budgets and call-depth limits, individual sessions can silently destroy the margin model. At negative-margin scale, a single runaway agentic loop compounds the bleed. This must be instrumented before any paying user is onboarded.

---

## Minimum HITL Gates

The following decision points require human approval before the agent proceeds autonomously:

1. **Any advice output flagged as high-stakes by domain classifier** — e.g., outputs touching fundraising strategy, legal structure, M&A, or regulatory compliance. These warrant a human review queue before delivery, at least during the beta period.

2. **Any session exceeding cost threshold** — a hard gate at, for example, $X per session (to be set against the per-user cost budget) that pauses the session and requires either user confirmation to continue or human ops review.

3. **Novel query types outside training distribution** — until the routing classifier is trained on real traffic, queries that fall below a confidence threshold on domain/intent classification should route to human review rather than a best-guess model selection.

4. **User-reported quality failures** — any explicit negative rating or escalation should trigger human review of the full session log before the same query type is served autonomously again.

---

## Recommended Next Actions (Ordered)

1. **Define the agent's task boundary and success metric this week.** One sentence: what does the agent do, and how do you know it did it well. Everything else in the checklist depends on this existing.

2. **Instrument per-call cost logging immediately, before any user traffic.** This is the single highest-leverage operational action given the arithmetic risk. Every model call should emit cost metadata to a running session total with a configurable circuit-breaker.

3. **Draft a data handling policy (even a one-page internal doc) before beta invites go out.** This is the most likely diligence gap to surface during the seed process and the most preventable.

4. **Define and test the degradation ladder** (preferred model → fallback model → graceful refusal) against synthetic failure scenarios before MVP launch. This should take one sprint.

5. **Establish a pre-launch advice quality baseline** using a fixed evaluation set of 20–30 representative strategic questions, scored by a human panel. This baseline is the foundation for drift detection and is also the empirical answer to the "is our advice mediocre?" question the founders are already asking.

6. **Run the 60-day caching feasibility test the directive itself recommends**, but instrument it against the multi-call architecture, not single-call assumptions. The test is only valid if it reflects the actual per-user-query call depth.

## Metadata

| Field | Value |
|---|---|
| Input tokens | 2,208 |
| Output tokens | 3,121 |
| Cache read tokens | 0 |
| Total tokens | 5,329 |
| Cost estimate | ~$0.0534 |

## Grade

<!-- A / A- / B+ / B / C / F — fill in after review -->

## Notes

<!-- Reviewer notes -->
