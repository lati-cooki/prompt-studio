# Jules Operational Workflow

This document defines how Jules interacts with the Prompt Studio repository across its three roles. When creating a session for Jules (`jules new`), reference the specific role workflow below.

## 1. Developer Workflow

**Goal:** Build the infrastructure of Prompt Studio.
**Trigger:** Standard `jules new "Feature description"` commands.

**Current Architectural Mandate:**
- The `sandbox` UI (currently saving to `localStorage`) and the `registry` interface (currently reading from a hardcoded list) must be merged.
- We need a unified backend (Python/FastAPI + SQLite or similar) that both UIs use.
- Jules must maintain the "no build step" philosophy of the sandbox where possible, or document any new build requirements clearly.

## 2. Evaluator Workflow

**Goal:** Provide automated Quality Assurance for prompts.
**Trigger:** `jules new "Evaluate draft prompt X against eval batch Y"`

**Process:**
1. Jules reads the drafted prompt from `sandbox/` (or the backend DB).
2. Jules reads the evaluation criteria from `registry/evals/`.
3. Jules executes the prompt against multiple target models (simulating the process found in `registry/evals/eval_batch_001.md`).
4. Jules calculates the necessary metrics (e.g., the $\delta$ score from the Consensus Protocol).
5. If the prompt passes the threshold, Jules generates a new schema entry in `registry/prompts/`, updates `registry/INDEX.json`, and commits the result.

## 3. Executor Workflow

**Goal:** Use the registered prompts to do actual work.
**Trigger:** `jules new "Execute task using registered prompt Z"`

**Process:**
1. Jules looks up the requested prompt in `registry/INDEX.json`.
2. Jules extracts the prompt text (e.g., `registry/prompts/consensus_protocol_v1_1_0.md`).
3. Jules applies the prompt as its system instruction or execution loop structure to solve the user's query.
4. Jules outputs the result in the format specified by the registered prompt schema.